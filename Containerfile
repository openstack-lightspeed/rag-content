ARG FLAVOR=cpu

# -- Stage 1a: Generate upstream plaintext formatted documentation ------------
FROM registry.access.redhat.com/ubi9/python-311 as docs-base-upstream

ARG BUILD_UPSTREAM_DOCS=true
ARG NUM_WORKERS=1
ARG OS_PROJECTS
ARG OS_API_DOCS=false
ARG PRUNE_PATHS=""

ENV NUM_WORKERS=$NUM_WORKERS
ENV OS_PROJECTS=$OS_PROJECTS
ENV OS_API_DOCS=$OS_API_DOCS
ENV PRUNE_PATHS=$PRUNE_PATHS

USER 0
WORKDIR /rag-content

COPY ./scripts ./scripts

# Graphviz is needed to generate text documentation for octavia
# python-devel and pcre-devel are needed for python-openstackclient
RUN if [ "$BUILD_UPSTREAM_DOCS" = "true" ]; then \
        dnf install -y graphviz python-devel pcre-devel pip && \
        pip install tox html2text && \
        ./scripts/get_openstack_plaintext_docs.sh; \
    fi

# -- Stage 1b: Generate downstream plaintext formatted documentation ----------
# Use the right CPU/GPU image or it will break the embedding stage as we replace the venv directory
FROM quay.io/lightspeed-core/rag-content-${FLAVOR}:latest as docs-base-downstream

ARG FLAVOR=cpu
ARG NUM_WORKERS=1
ARG RHOSO_CA_CERT_URL=""
ARG RHOSO_DOCS_GIT_URL=""
ARG RHOSO_DOCS_GIT_BRANCH=""
ARG RHOSO_RELNOTES_GIT_URL=""
ARG RHOSO_RELNOTES_GIT_BRANCH=""
ARG RHOSO_EXCLUDE_TITLES=""
ARG RHOSO_REMAP_TITLES="{}"

ENV NUM_WORKERS=$NUM_WORKERS
ENV RHOSO_CA_CERT_URL=$RHOSO_CA_CERT_URL
ENV RHOSO_DOCS_GIT_URL=$RHOSO_DOCS_GIT_URL
ENV RHOSO_DOCS_GIT_BRANCH=$RHOSO_DOCS_GIT_BRANCH
ENV RHOSO_RELNOTES_GIT_URL=$RHOSO_RELNOTES_GIT_URL
ENV RHOSO_RELNOTES_GIT_BRANCH=$RHOSO_RELNOTES_GIT_BRANCH

USER 0
WORKDIR /rag-content

COPY ./scripts ./scripts

# Copy the OKP content to inside the container
COPY ./okp-content ./okp-content

# * Graphviz is needed to generate text documentation for octavia
# * python-devel and pcre-devel are needed for python-openstackclient
# * python-devel was already installed in our base image
# TODO: Make filter work with latest pandoc version (3.8.2) and update version
RUN if [ ! -z "${RHOSO_DOCS_GIT_URL}" ]; then \
        if [ "$FLAVOR" == "cpu" ]; then \
            microdnf install -y graphviz pcre-devel tar pip; \
        else \
            dnf install -y graphviz pcre-devel tar pip libcudnn9 libnccl libcusparselt0 git; \
        fi && \
        pip install lxml && \
        bash -c 'curl -L https://github.com/jgm/pandoc/releases/download/3.1.11.1/pandoc-3.1.11.1-linux-amd64.tar.gz | tar -zx --strip-components=1 -C /usr/local/' && \
        ./scripts/get_rhoso_plaintext_docs.sh; \
    fi

# -- Stage 2: Compute embeddings for the doc chunks ---------------------------
FROM quay.io/lightspeed-core/rag-content-${FLAVOR}:latest as lightspeed-core-rag-builder
COPY --from=docs-base-upstream /rag-content /rag-content
COPY --from=docs-base-downstream /rag-content /rag-content

ARG FLAVOR=cpu
ARG BUILD_UPSTREAM_DOCS=true
ARG DOCS_LINK_UNREACHABLE_ACTION=warn
ARG OS_VERSION=2025.2
ARG INDEX_NAME=os-docs-${OS_VERSION}
ARG NUM_WORKERS=1
ARG RHOSO_DOCS_GIT_URL=""
ARG VECTOR_DB_TYPE="faiss"
ARG BUILD_OKP_CONTENT=false
ARG OKP_CONTENT="all"

ENV OS_VERSION=$OS_VERSION
ENV LD_LIBRARY_PATH=""
ENV OKP_CONTENT=$OKP_CONTENT

WORKDIR /rag-content

RUN if [ "$FLAVOR" = "gpu" ]; then \
        python -c "import torch; exit(0) if torch.cuda.is_available() else exit(1)"; \
    fi && \
    if [ "$BUILD_UPSTREAM_DOCS" = "true" ]; then \
        FOLDER_ARG="--folder openstack-docs-plaintext"; \
    fi && \
    if [ ! -z "${RHOSO_DOCS_GIT_URL}" ]; then \
        FOLDER_ARG="$FOLDER_ARG --rhoso-folder rhoso-docs-plaintext"; \
    fi && \
    if [ "$BUILD_OKP_CONTENT" = "true" ]; then \
        FOLDER_ARG="$FOLDER_ARG --okp-folder ./okp-content --okp-content ${OKP_CONTENT}"; \
    fi && \
    python ./scripts/generate_embeddings_openstack.py \
    --output ./vector_db/ \
    --model-dir embeddings_model \
    --model-name ${EMBEDDING_MODEL} \
    --index ${INDEX_NAME} \
    --workers ${NUM_WORKERS} \
    --unreachable-action ${DOCS_LINK_UNREACHABLE_ACTION} \
    --vector-store-type $VECTOR_DB_TYPE \
    --openstack-version ${OS_VERSION} \
    ${FOLDER_ARG}

# Clean up the OKP content
RUN rm -rf ./okp-content

# -- Stage 3: Store the vector DB into ubi-minimal image ----------------------
FROM registry.access.redhat.com/ubi9/ubi-minimal:latest
COPY --from=lightspeed-core-rag-builder /rag-content/vector_db /rag/vector_db/os_product_docs
COPY --from=lightspeed-core-rag-builder /rag-content/embeddings_model /rag/embeddings_model

ARG INDEX_NAME
ENV INDEX_NAME=${INDEX_NAME}

RUN mkdir /licenses
COPY LICENSE /licenses/

LABEL description="Red Hat OpenStack Lightspeed RAG content"

USER 65532:65532
