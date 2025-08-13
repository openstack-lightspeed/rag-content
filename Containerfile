ARG FLAVOR=cpu

# -- Stage 1a: Generate upstream plaintext formatted documentation ------------
FROM registry.access.redhat.com/ubi9/python-311 as docs-base-upstream

ARG BUILD_UPSTREAM_DOCS=true
ARG NUM_WORKERS=1
ARG OS_PROJECTS
ARG OS_VERSION=2024.2
ARG PRUNE_PATHS=""

ENV NUM_WORKERS=$NUM_WORKERS
ENV OS_PROJECTS=$OS_PROJECTS
ENV OS_VERSION=$OS_VERSION
ENV PRUNE_PATHS=$PRUNE_PATHS

USER 0
WORKDIR /rag-content

COPY ./scripts ./scripts

# Graphviz is needed to generate text documentation for octavia
# python-devel and pcre-devel are needed for python-openstackclient
RUN if [ "$BUILD_UPSTREAM_DOCS" = "true" ]; then \
        dnf install -y graphviz python-devel pcre-devel pip && \
        pip install tox && \
        ./scripts/get_openstack_plaintext_docs.sh; \
    fi

# -- Stage 1b: Generate downstream plaintext formatted documentation ----------
FROM ghcr.io/lightspeed-core/rag-content-${FLAVOR}:latest as docs-base-downstream

ARG NUM_WORKERS=1
ARG RHOSO_CA_CERT_URL=""
ARG RHOSO_DOCS_GIT_URL=""
ARG RHOSO_DOCS_GIT_BRANCH=""
ARG RHOSO_DOCS_ATTRIBUTES_FILE_URL=""
ARG RHOSO_RELNOTES_GIT_URL=""
ARG RHOSO_RELNOTES_GIT_BRANCH=""

ENV NUM_WORKERS=$NUM_WORKERS
ENV RHOSO_CA_CERT_URL=$RHOSO_CA_CERT_URL
ENV RHOSO_DOCS_GIT_URL=$RHOSO_DOCS_GIT_URL
ENV RHOSO_DOCS_GIT_BRANCH=$RHOSO_DOCS_GIT_BRANCH
ENV RHOSO_DOCS_ATTRIBUTES_FILE_URL=$RHOSO_DOCS_ATTRIBUTES_FILE_URL
ENV RHOSO_RELNOTES_GIT_URL=$RHOSO_RELNOTES_GIT_URL
ENV RHOSO_RELNOTES_GIT_BRANCH=$RHOSO_RELNOTES_GIT_BRANCH

USER 0
WORKDIR /rag-content

COPY ./scripts ./scripts

# Graphviz is needed to generate text documentation for octavia
# python-devel and pcre-devel are needed for python-openstackclient
#   python-devel was already installed in our base image
RUN if [ ! -z "${RHOSO_DOCS_GIT_URL}" ]; then \
        microdnf install -y graphviz pcre-devel && \
        ./scripts/get_rhoso_plaintext_docs.sh; \
    fi

# -- Stage 2: Compute embeddings for the doc chunks ---------------------------
FROM ghcr.io/lightspeed-core/rag-content-${FLAVOR}:latest as lightspeed-core-rag-builder
COPY --from=docs-base-upstream /rag-content /rag-content
COPY --from=docs-base-downstream /rag-content /rag-content

ARG FLAVOR=cpu
ARG BUILD_UPSTREAM_DOCS=true
ARG DOCS_LINK_UNREACHABLE_ACTION=warn
ARG OS_VERSION=2024.2
ARG INDEX_NAME=os-docs-${OS_VERSION}
ARG NUM_WORKERS=1
ARG RHOSO_DOCS_GIT_URL=""
ARG VECTOR_DB_TYPE="faiss"


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
    python ./scripts/generate_embeddings_openstack.py \
    --output ./vector_db/ \
    --model-dir embeddings_model \
    --model-name ${EMBEDDING_MODEL} \
    --index ${INDEX_NAME} \
    --workers ${NUM_WORKERS} \
    --unreachable-action ${DOCS_LINK_UNREACHABLE_ACTION} \
    --vector-store-type $VECTOR_DB_TYPE \
    ${FOLDER_ARG}

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
