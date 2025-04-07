# [OpenStack] RAG content

This repository contains scripts that can be used to generate a vector database
containing information from upstream OpenStack documentation.

There are several ways how to access the OpenStack vector database:

- [Generate OpenStack Vector Database](#generate-openstack-vector-database)

- [Build Container Image Containing OpenStack Vector Database](#build-container-image-containing-openstack-vector-database)

- [Download the Pre-built Container Image Containing OpenStack Vector Database](#download-pre-built-container-image-containing-the-vector-database)


## Generate OpenStack Vector Database

1. Install requirements: `python3.11.*`.

2. Create virtualenv.

```
python3.11 -m venv .venv && . .venv/bin/activate
```

3. Install dependencies.

```
pip install -r requirements.txt
```

4. Generate upstream documentation in text format.

```
./scripts/get_openstack_plaintext_docs.sh
```

5. Download the embedding model.

```
make get-embeddings-model
```

> **Note:**
> The get-embeddings-model target pulls in the embedding
> model from the most recent build. To download it from
> source, use the `download_embeddings_model.py` script from
> [road-core/rag-content](https://github.com/road-core/rag-content):
>
> ```bash
> curl -O https://raw.githubusercontent.com/road-core/rag-content/refs/heads/main/scripts/download_embeddings_model.py
> python ./download_embeddings_model.py \
>     -l ./embeddings_model/ \
>     -r sentence-transformers/all-mpnet-base-v2
> ```

6. Generate the vector database.

```
python ./scripts/generate_embeddings_openstack.py \
        -o ./vector_db/ \
        -f openstack-docs-plaintext/ \
        -md embeddings_model \
        -mn sentence-transformers/all-mpnet-base-v2 \
        -i os-docs \
        -w $(( $(nproc --all) / 2 ))
```

7. Use the vector database stored in `./vector_db`.


## Build Container Image Containing OpenStack Vector Database

1. Install requirements: `make`, `podman`.

2. Generate the container image. If you have GPU available, use `FLAVOR=gpu`.

```
make build-image-os FLAVOR=cpu
```

3. The generated vector database can be found under `/rag/vector_db/os_product_docs`
inside of the image.

```
podman run localhost/rag-content-openstack:latest ls /rag/vector_db/os_product_docs
```


## Download the Pre-built Container Image Containing OpenStack Vector Database

We periodically build the vector database for the upstream OpenStack documentation
as part of this repository. The image containing this vector database is available
at [quay.io/openstack-lightspeed/rag-content](https://quay.io/openstack-lightspeed/rag-content).

You can verify that the image was built within a job triggered by this repository
using the [cosign](https://github.com/sigstore/cosign) utility:

```
IMAGE=quay.io/openstack-lightspeed/rag-content@sha256:<sha256sum>
cosign verify --key https://raw.githubusercontent.com/openstack-lightspeed/rag-content/refs/heads/main/.github/workflows/cosign.pub ${IMAGE}
```
