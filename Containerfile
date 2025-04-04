ARG FLAVOR=cpu
FROM ghcr.io/road-core/rag-content-${FLAVOR}:latest as road-core-rag-builder
ARG OS_VERSION=2024.2
ARG INDEX_NAME=os-docs-${OS_VERSION}
ARG OS_PROJECTS
ARG NUM_WORKERS=1
ARG RHOSO_DOCS_GIT_URL=""
ARG RHOSO_DOCS_ATTRIBUTES_FILE_URL=""

USER 0
WORKDIR /rag-content

COPY ./scripts ./scripts

# Graphviz is needed to generate text documentation for octavia
# python-devel and pcre-devel are needed for python-openstackclient
RUN dnf install -y graphviz python-devel pcre-devel
RUN pip install tox

RUN if [ -z "${RHOSO_DOCS_GIT_URL}" ]; then \
        ./scripts/get_openstack_plaintext_docs.sh; \
    fi

RUN if [ ! -z "${RHOSO_DOCS_GIT_URL}" ]; then \
        ./scripts/get_rhoso_plaintext_docs.sh; \
    fi

RUN if [ -z "${RHOSO_DOCS_GIT_URL}" ]; then \
        python ./scripts/generate_embeddings_openstack.py \
            --output ./vector_db/ \
            --folder openstack-docs-plaintext/ \
            --model-dir embeddings_model \
            --model-name ${EMBEDDING_MODEL} \
            --index ${INDEX_NAME} \
            --workers ${NUM_WORKERS}; \
    fi

RUN if [ ! -z "${RHOSO_DOCS_GIT_URL}" ]; then \
        python ./scripts/generate_embeddings_openstack.py \
            --output ./vector_db/ \
            --rhoso-folder openstack-docs-plaintext/ \
            --model-dir embeddings_model \
            --model-name ${EMBEDDING_MODEL} \
            --index ${INDEX_NAME} \
            --workers ${NUM_WORKERS}; \
    fi

FROM registry.access.redhat.com/ubi9/ubi-minimal:latest
COPY --from=road-core-rag-builder /rag-content/vector_db /rag/vector_db/os_product_docs
COPY --from=road-core-rag-builder /rag-content/embeddings_model /rag/embeddings_model

RUN mkdir /licenses
COPY LICENSE /licenses/

LABEL description="Red Hat OpenStack Lightspeed RAG content"

USER 65532:65532
