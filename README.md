# [OpenStack] RAG content

This repository contains scripts that can be used to generate a vector database
containing information from upstream OpenStack documentation.

There are several ways how to access the OpenStack vector database:

- [Generate OpenStack Vector Database](#generate-openstack-vector-database)

- [Build Container Image Containing OpenStack Vector Database](#build-container-image-containing-openstack-vector-database)

- [Download the Pre-built Container Image Containing OpenStack Vector Database](#download-pre-built-container-image-containing-the-vector-database)


## Generate OpenStack Vector Database

1. Install requirements: `python3.12.*`.

2. Create virtualenv.

```
python3.12 -m venv .venv && . .venv/bin/activate
```

3. Install dependencies.

```
pip install -r requirements.txt
```

4. Generate upstream documentation in text format.

```
./scripts/get_openstack_plaintext_docs.sh
```

   Useful env vars for this script:
   - `CLEAN_FILES` what to clean on success: `venv`, `all` (whole project), or nothing (default).
   - `NUM_WORKERS` if the default number (`nproc`) is too high
   - `WORKING_DIR` if you don't want to use the default `/tmp/os_docs_temp`.

5. Download the embedding model.

```
make get-embeddings-model
```

> [!NOTE]
> The get-embeddings-model target pulls in the embedding model from the most
> recent build. To download it from source, use the `download_embeddings_model.py`
> script from [lightspeed-core/rag-content](https://github.com/lightspeed-core/rag-content):
>
> ```bash
> curl -O https://raw.githubusercontent.com/lightspeed-core/rag-content/refs/heads/main/scripts/download_embeddings_model.py
> python ./download_embeddings_model.py \
>     -l ./embeddings_model/ \
>     -r sentence-transformers/all-mpnet-base-v2
> ```

6. Generate the vector database.

- For llama-index

```
python ./scripts/generate_embeddings_openstack.py \
        -o ./vector_db/ \
        -f openstack-docs-plaintext/ \
        -md embeddings_model \
        -mn sentence-transformers/all-mpnet-base-v2 \
        -i os-docs \
        -w $(( $(nproc --all) / 2 ))
```

- For llama-stack

```
python ./scripts/generate_embeddings_openstack.py \
        -o ./vector_db/ \
        -f openstack-docs-plaintext/ \
        -md embeddings_model \
        -mn sentence-transformers/all-mpnet-base-v2 \
        -i os-docs \
        --vector-store-type=llamastack-faiss \
        -w $(( $(nproc --all) / 2 ))
```

7. Test the database stored in `./vector_db`

```bash
curl -o /tmp/query_rag.py https://raw.githubusercontent.com/lightspeed-core/rag-content/refs/heads/main/scripts/query_rag.py
python /tmp/query_rag.py -p vector_db -x os-docs -m embeddings_model -k 5 -q "how can I configure a cinder backend"
```

8. Use the vector database stored in `./vector_db`.


## Build Container Image Containing OpenStack & OCP Vector Databases

1. Install requirements: `make`, `podman`.

2. Generate the container image. If you have GPU available, use `FLAVOR=gpu`.

```
make build-image-os FLAVOR=cpu
```

> [!NOTE]
> By default the image will include OCP RAG DBs for versions 4.16, 4.18, and
> latest. This can be changed with the `OCP_VERSIONS` variable by setting it to
> `all` or a space separated list of versions eg.
> `OCP_VERSIONS='4.16 4.18 latest`. We can also disable creating these DBs
> setting `BUILD_OCP_DOCS` to anything other than `true`.

The embedding and databases will be present in the `/rag` directory with the following structure:
```
.
├── embedding_model
├── ocp_vector_db
│   ├── ocp_4.16
│   ├── ocp_4.18
│   ├── ocp_4.21
│   └── ocp_latest
└── vector_db
    └── os_product_docs
```

Things to be aware here are:
- `os_product_docs` database uses DB index id `rhoso-18.0`.
- `ocp_4.16` and `ocp_4.18` databases use DB index id `ocp-product-docs-4_16`
  and `ocp-product-docs-4_18` respectively.
- `ocp_4.21` and `ocp_latest` database use DB index id
  `ocp-product-docs-latest` as the `ocp_4.21` directory is just a symlink to
  the `ocp_latest` database.
- There will be no `ocp_latest` database if we only built the container image
  with documentation for 4.16 and 4.18.

If we have an Nvidia GPU card properly configured in podman we can run:

```bash
make build-image-os FLAVOR=gpu
```

If our GPU is not an Nvidia card and is supported by podman and torch, then we
can override the default value in `BUILD_GPU_ARGS` (here we show de default
value):

```bash
make build-image-os FLAVOR=gpu BUILD_GPU_ARGS="--device nvidia.com/gpu=all"
```

> [!NOTE]
> Using GPU capabilities within a Podman container requires setting up your OS
> to utilize the GPU. [Follow official instructions to create the CDI](https://podman-desktop.io/docs/podman/gpu).

3. The generated vector database can be found under `/rag/vector_db/os_product_docs`
inside of the image.

```
podman run localhost/rag-content-openstack:latest ls /rag/vector_db/os_product_docs
```

## Build with OKP content

To include OKP content in the RAG, copy the non-paywalled OKP content into
the `okp-content` directory of this project, for example:

```bash
cp -r red_hat_content/{documentation,errata,pages} okp-content/
```

Next, set `BUILD_OKP_CONTENT` to true when building the container image,
for example:

```bash
make build-image-os BUILD_OKP_CONTENT="true"
```

By default, all content in the folder will be ingested. To choose specific
items to include in the RAG, use the `OKP_CONTENT` parameter with a
space-separated list of content, for example:

```bash
make build-image-os BUILD_OKP_CONTENT="true" OKP_CONTENT="pages documentation"
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
