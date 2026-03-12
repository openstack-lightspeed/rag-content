# This Containerfile.temp is a TEMPORARY file and may be removed from this repository
# at any time without prior notice. Only those for whom this file was created
# will be notified of its removal. If you are unsure whether this applies to you,
# it most likely does not meaning DO NOT USE this Containerfile please. To build
# vector database image with this Containerfile run:
#
#    make build-image-os \
#       CONTAINERFILE=temporary_gpu.containerfile \
#       BUILD_GPU_ARGS="--device <CDI device reference>"
#

# -- GPU Base: Contains GPU installation of lightspeed-core/rag-content ------
# Take 1:1 from: https://github.com/lightspeed-core/rag-content/blob/main/Containerfile-gpu
FROM nvcr.io/nvidia/cuda:12.9.1-devel-ubi9 AS gpu-base

# Install Python
RUN dnf install -y --nodocs --setopt=keepcache=0 --setopt=tsflags=nodocs \
    python3.12 python3.12-devel python3.12-pip libcudnn9 libnccl libcusparselt0 git && \
    dnf clean all
RUN ln -sf /usr/bin/python3.12 /usr/bin/python

# Install asciidoctor
RUN dnf install -y rubygems && \
    dnf clean all && \
    gem install asciidoctor
# Install uv package manager
RUN pip3.12 install uv==0.7.20

RUN git clone --depth 1 https://github.com/lightspeed-core/rag-content.git
WORKDIR /rag-content

# Configure UV environment variables for optimal performance
# Pytorch backend - cpu. `uv` contains convenient way to specify the backend.
ENV UV_COMPILE_BYTECODE=0 \
    UV_PYTHON_DOWNLOADS=0

# Remove pytorch-cpu dependency from pyproject.toml
RUN uv venv && uv pip install tomlkit
RUN uv run python ./scripts/remove_pytorch_cpu_pyproject.py

# Update uv.lock file and install dependencies
RUN rm -f uv.lock && rm -rf .venv && uv lock && uv sync --locked --no-install-project

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
RUN uv sync --locked

# Add executables from .venv to system PATH
ENV PATH="/rag-content/.venv/bin:$PATH"

# Download embeddings model
ENV EMBEDDING_MODEL=sentence-transformers/all-mpnet-base-v2
RUN python ./scripts/download_embeddings_model.py \
       -l ./embeddings_model \
       -r ${EMBEDDING_MODEL}

# -- Stage 1a: Generate upstream plaintext formatted documentation ------------
FROM registry.access.redhat.com/ubi9/python-311 AS docs-base-upstream

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
FROM gpu-base AS docs-base-downstream

ARG NUM_WORKERS=1
ARG RHOSO_CA_CERT_URL=""
ARG RHOSO_DOCS_GIT_URL=""
ARG RHOSO_DOCS_GIT_BRANCH="main"

ENV NUM_WORKERS=$NUM_WORKERS
ENV RHOSO_CA_CERT_URL=$RHOSO_CA_CERT_URL
ENV RHOSO_DOCS_GIT_URL=$RHOSO_DOCS_GIT_URL
ENV RHOSO_DOCS_GIT_BRANCH=$RHOSO_DOCS_GIT_BRANCH

USER 0
WORKDIR /rag-content

COPY ./scripts ./scripts

# Copy the OKP content to inside the container
COPY ./okp-content ./okp-content

# Clone the RHOSO docs repository if provided
RUN if [ ! -z "$RHOSO_DOCS_GIT_URL" ]; then \
        if [ -n "$RHOSO_CA_CERT_URL" ]; then \
            echo "Adding custom RHOSO CA certificate from $RHOSO_CA_CERT_URL"; \
            curl -o "ca.pem" "${RHOSO_CA_CERT_URL}"; \
            git clone -c http.sslCAInfo="ca.pem" -v --depth=1 --single-branch --branch "$RHOSO_DOCS_GIT_BRANCH" "$RHOSO_DOCS_GIT_URL" rag-docs; \
        else \
            echo "No custom RHOSO CA certificate provided"; \
            GIT_SSL_NO_VERIFY=true git clone -v --depth=1 --single-branch --branch "$RHOSO_DOCS_GIT_BRANCH" "$RHOSO_DOCS_GIT_URL" rag-docs; \
        fi \
    fi

# -- Stage 2: Compute embeddings for the doc chunks ---------------------------
FROM gpu-base AS lightspeed-core-rag-builder
COPY --from=docs-base-upstream /rag-content /rag-content
COPY --from=docs-base-downstream /rag-content /rag-content

ARG BUILD_UPSTREAM_DOCS=true
ARG DOCS_LINK_UNREACHABLE_ACTION=warn
ARG OS_VERSION=2025.2
ARG INDEX_NAME=os-docs-${OS_VERSION}
ARG NUM_WORKERS=1
ARG RHOSO_DOCS_GIT_URL=""
ARG VECTOR_DB_TYPE="faiss"
ARG BUILD_OKP_CONTENT=false
ARG OKP_CONTENT="all"
ARG HERMETIC=false
ARG BUILD_OCP_DOCS=false

ENV OS_VERSION=$OS_VERSION
ENV LD_LIBRARY_PATH=""
ENV OKP_CONTENT=$OKP_CONTENT
ENV BUILD_OCP_DOCS=$BUILD_OCP_DOCS

USER 0
WORKDIR /rag-content

RUN python -c "import torch, sys; available=torch.cuda.is_available(); print(f'CUDA is available: {available}'); sys.exit(0 if available else 1)"; \
    if [ "$BUILD_UPSTREAM_DOCS" = "true" ]; then \
        FOLDER_ARG="--folder openstack-docs-plaintext"; \
    fi && \
    if [ ! -z "${RHOSO_DOCS_GIT_URL}" ]; then \
        FOLDER_ARG="$FOLDER_ARG --rhoso-folder rag-docs/rhoso-docs-plaintext"; \
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

# Compute embeddings for the OCP docs
# For the latest version we need to set the index as latest unless it's one of the soported ones
# If we only have supported versions then create latest symlink
# Condition checks for the script to run because that is copied from the OLS repo on download
RUN if [ "$BUILD_OCP_DOCS" = "true" ] && [ -f "/rag-content/rag-docs/ocp-product-docs-plaintext/ocp_generate_embeddings.py" ]; then \
        LATEST_VERSION="$(basename $(ls -d1 rag-docs/ocp-product-docs-plaintext/4.* | sort -V | tail -n 1))" && \
        echo "Latest version is ${LATEST_VERSION}" && \
        set -e && for OCP_VERSION in $(cd rag-docs/ocp-product-docs-plaintext && ls -d1 4*); do \
            if [[ "${LATEST_VERSION}" == "${OCP_VERSION}" ]] && [[ "4.16 4.18" != *"${OCP_VERSION}"* ]]; then \
                echo "Version ${OCP_VERSION} used as the latest version"; \
                VERSION_POSTFIX="latest"; \
            else \
                echo "Version ${OCP_VERSION} is not the latest version"; \
                VERSION_POSTFIX="${OCP_VERSION}"; \
            fi && \
            python ./rag-docs/ocp-product-docs-plaintext/ocp_generate_embeddings.py \
                -f ./rag-docs/ocp-product-docs-plaintext/${OCP_VERSION} \
                -r ./rag-docs/ocp-product-docs-plaintext/common_alerts \
                -md embeddings_model \
                -mn ${EMBEDDING_MODEL} \
                -o ocp_vector_db/ocp_${VERSION_POSTFIX} \
                -i ocp-product-docs-$(echo $VERSION_POSTFIX | sed 's/\./_/g') \
                -v ${OCP_VERSION} \
                -hb $HERMETIC; \
        done && \
        if [[ -d ocp_vector_db/ocp_latest ]]; then \
            ln -s -r ocp_vector_db/ocp_latest ocp_vector_db/ocp_${LATEST_VERSION}; \
        fi; \
    else \
        mkdir -p /rag-content/ocp_vector_db; \
    fi

# Clean up the OKP content
RUN rm -rf ./okp-content

# -- Stage 3: Store the vector DB into ubi-minimal image ----------------------
FROM registry.access.redhat.com/ubi9/ubi-minimal:latest
COPY --from=lightspeed-core-rag-builder /rag-content/vector_db /rag/vector_db/os_product_docs
COPY --from=lightspeed-core-rag-builder /rag-content/embeddings_model /rag/embeddings_model
COPY --from=lightspeed-core-rag-builder /rag-content/ocp_vector_db /rag/ocp_vector_db

ARG INDEX_NAME
ENV INDEX_NAME=${INDEX_NAME}

RUN if [ -z "$( ls -A '/rag/ocp_vector_db' )" ]; then \
      rmdir /rag/ocp_vector_db; \
    fi && \
    mkdir /licenses
COPY LICENSE /licenses/

LABEL description="Red Hat OpenStack Lightspeed RAG content"

USER 65532:65532
