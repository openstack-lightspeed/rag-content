ARG FLAVOR=cpu
FROM ghcr.io/road-core/rag-content:latest-${FLAVOR} as road-core-rag-builder
ARG OS_VERSION=2024.2
ARG OS_PROJECTS
ARG NUM_WORKERS=1

USER 0
WORKDIR /rag-content

COPY ./scripts/get_openstack_plaintext_docs.sh ./
COPY ./scripts/generate_embeddings_openstack.py ./

# Graphviz is needed to generate text documentation for octavia
RUN dnf install -y graphviz
RUN pip install tox
RUN ./get_openstack_plaintext_docs.sh

RUN python ./generate_embeddings_openstack.py \
        -o ./vector_db/ \
        -f openstack-docs-plaintext/ \
        -md embeddings_model \
        -mn ${EMBEDDING_MODEL} \
        -i os-docs-${OS_VERSION} \
        -w ${NUM_WORKERS}

FROM registry.access.redhat.com/ubi9/ubi-minimal:latest
COPY --from=road-core-rag-builder /rag-content/vector_db /rag/vector_db/os_product_docs
COPY --from=road-core-rag-builder /rag-content/embeddings_model /rag/embeddings_model

RUN mkdir /licenses
COPY LICENSE /licenses/

LABEL description="Red Hat OpenStack Lightspeed RAG content"

USER 65532:65532
