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
        if [ "$FLAVOR" == "gpu" ]; then \
            dnf install -y git; \
        fi && \
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
FROM quay.io/lightspeed-core/rag-content-${FLAVOR}:latest as lightspeed-core-rag-builder
COPY --from=docs-base-upstream /rag-content /rag-content
COPY --from=docs-base-downstream /rag-content /rag-content

ARG FLAVOR=cpu
ARG BUILD_UPSTREAM_DOCS=true
ARG DOCS_LINK_UNREACHABLE_ACTION=warn
ARG OS_VERSION=2026.1
ARG INDEX_NAME=os-docs-${OS_VERSION}
ARG NUM_WORKERS=1
ARG RHOSO_DOCS_GIT_URL=""
ARG VECTOR_DB_TYPE="faiss"
ARG BUILD_OKP_CONTENT=false
ARG BUILD_OPERATORS_DOCS=false
ARG OKP_CONTENT="all"
ARG RHOSO_IGNORE_LIST=""
ARG BUILD_OCP_DOCS=false
ARG RHOSO_DOCS_EXTRA_DOCS=""

ENV OS_VERSION=$OS_VERSION
ENV LD_LIBRARY_PATH=""
ENV OKP_CONTENT=$OKP_CONTENT
ENV BUILD_OCP_DOCS=$BUILD_OCP_DOCS

USER 0
WORKDIR /rag-content

RUN if [ "$FLAVOR" == "gpu" ]; then \
        python -c "import torch, sys; available=torch.cuda.is_available(); print(f'CUDA is available: {available}'); sys.exit(0 if available else 1)"; \
    fi && \
    if [ "$BUILD_UPSTREAM_DOCS" = "true" ]; then \
        FOLDER_ARG="--folder openstack-docs-plaintext"; \
    fi && \
    if [ ! -z "$RHOSO_DOCS_GIT_URL" ]; then \
        FOLDER_ARG="$FOLDER_ARG --rhoso-folder rag-docs/rhoso-docs-plaintext"; \
        if [ ! -z "$RHOSO_DOCS_EXTRA_DOCS" ]; then \
            FOLDER_ARG="$FOLDER_ARG --extra-folder $RHOSO_DOCS_EXTRA_DOCS"; \
        fi; \
        if [ "$BUILD_OPERATORS_DOCS" = "true" ]; then \
            FOLDER_ARG="$FOLDER_ARG --operators-folder rag-docs/openstack-operators-docs-markdown"; \
        fi; \
    fi && \
    if [ "$BUILD_OKP_CONTENT" = "true" ]; then \
        FOLDER_ARG="$FOLDER_ARG --okp-folder ./okp-content --okp-content ${OKP_CONTENT}"; \
    fi && \
    if [ -z "$FOLDER_ARG" ] && [ "$BUILD_OCP_DOCS" != "true" ]; then \
        echo "Error: No documentation sources enabled"; \
        exit 1; \
    fi && \
    if [ -n "$FOLDER_ARG" ]; then \
        python ./scripts/generate_embeddings_openstack.py \
        --output ./vector_db/ \
        --model-dir embeddings_model \
        --model-name ${EMBEDDING_MODEL} \
        --index ${INDEX_NAME} \
        --workers ${NUM_WORKERS} \
        --unreachable-action ${DOCS_LINK_UNREACHABLE_ACTION} \
        --ignore-list ${RHOSO_IGNORE_LIST} \
        --vector-store-type $VECTOR_DB_TYPE \
        --openstack-version ${OS_VERSION} \
        ${FOLDER_ARG}; \
    else \
        echo "No OpenStack/RHOSO doc sources, building OCP-only RAG"; \
        mkdir -p ./vector_db; \
    fi

# Compute embeddings for the OCP docs using the LCORE-based script
# This ensures OCP docs are compatible with both faiss and llamastack vector stores
RUN if [ "$BUILD_OCP_DOCS" = "true" ] && [ -d "/rag-content/rag-docs/ocp-product-docs-plaintext" ]; then \
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
            OCP_ARGS="--ocp-folder ./rag-docs/ocp-product-docs-plaintext/${OCP_VERSION} --ocp-version ${OCP_VERSION}" && \
            if [ -d "./rag-docs/ocp-product-docs-plaintext/common_alerts" ]; then \
                OCP_ARGS="$OCP_ARGS --runbooks-folder ./rag-docs/ocp-product-docs-plaintext/common_alerts"; \
            fi && \
            python ./scripts/generate_embeddings_openstack.py \
                ${OCP_ARGS} \
                --output ocp_vector_db/ocp_${VERSION_POSTFIX} \
                --model-dir embeddings_model \
                --model-name ${EMBEDDING_MODEL} \
                --index ocp-product-docs-$(echo $VERSION_POSTFIX | sed 's/\./_/g') \
                --workers ${NUM_WORKERS} \
                --unreachable-action ${DOCS_LINK_UNREACHABLE_ACTION} \
                --vector-store-type $VECTOR_DB_TYPE; \
        done && \
        if [[ -d ocp_vector_db/ocp_latest ]]; then \
            ln -s -r ocp_vector_db/ocp_latest ocp_vector_db/ocp_${LATEST_VERSION}; \
        fi; \
    else \
        mkdir -p /rag-content/ocp_vector_db; \
    fi

# Download the OKP embeddings model
RUN python ./scripts/download_okp_embeddings.py --output-dir okp_embeddings_model

# Clean up the OKP content
RUN rm -rf ./okp-content

# -- Stage 3: Store the vector DB into ubi-minimal image ----------------------
FROM registry.access.redhat.com/ubi9/ubi-minimal:latest
COPY --from=lightspeed-core-rag-builder /rag-content/vector_db /rag/vector_db/os_product_docs
COPY --from=lightspeed-core-rag-builder /rag-content/embeddings_model /rag/embeddings_model
COPY --from=lightspeed-core-rag-builder /rag-content/okp_embeddings_model /rag/okp_embeddings_model
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
