ARG FLAVOR=cpu
FROM ghcr.io/road-core/rag-content-${FLAVOR}:latest as road-core-rag-builder
ARG OS_VERSION=2024.2
ARG INDEX_NAME=os-docs-${OS_VERSION}
ARG OS_PROJECTS
ARG NUM_WORKERS=1
ARG RHOSO_DOCS_GIT_URL=""
ARG RHOSO_DOCS_ATTRIBUTES_FILE_URL=""
ARG BUILD_UPSTREAM_DOCS=true

USER 0
WORKDIR /rag-content

COPY ./scripts ./scripts

# Graphviz is needed to generate text documentation for octavia
# python-devel and pcre-devel are needed for python-openstackclient
RUN dnf install -y graphviz python-devel pcre-devel
RUN pip install tox

RUN if [ "$BUILD_UPSTREAM_DOCS" = "true" ]; then \
        ./scripts/get_openstack_plaintext_docs.sh; \
    fi

RUN if [ ! -z "${RHOSO_DOCS_GIT_URL}" ]; then \
        OUTPUT_DIR_NAME=rhoso-docs-plaintext ./scripts/get_rhoso_plaintext_docs.sh; \
    fi

RUN CMD="python ./scripts/generate_embeddings_openstack.py"; \
    CMD="$CMD --output ./vector_db/"; \
    CMD="$CMD --model-dir embeddings_model"; \
    CMD="$CMD --model-name ${EMBEDDING_MODEL}"; \
    CMD="$CMD --index ${INDEX_NAME}"; \
    CMD="$CMD --workers ${NUM_WORKERS}"; \
    if [ "$BUILD_UPSTREAM_DOCS" = "true" ]; then \
        CMD="$CMD --folder openstack-docs-plaintext/"; \
    fi; \
    if [ ! -z "${RHOSO_DOCS_GIT_URL}" ]; then \
        CMD="$CMD --rhoso-folder rhoso-docs-plaintext"; \
    fi; \
    echo "Running: $CMD"; \
    eval $CMD


FROM registry.access.redhat.com/ubi9/ubi-minimal:latest
COPY --from=road-core-rag-builder /rag-content/vector_db /rag/vector_db/os_product_docs
COPY --from=road-core-rag-builder /rag-content/embeddings_model /rag/embeddings_model

RUN mkdir /licenses
COPY LICENSE /licenses/

LABEL description="Red Hat OpenStack Lightspeed RAG content"

USER 65532:65532
