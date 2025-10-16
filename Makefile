# Default to CPU if not specified
FLAVOR                         ?= cpu
NUM_WORKERS                    ?= $$(( $(shell nproc --all) / 2))
OS_VERSION                     ?= 2024.2
# Check scripts/get_openstack_plaintext_docs.sh to see OS_PROJECTS defaults
OS_PROJECTS                    ?=
PRUNE_PATHS                    ?= ""
INDEX_NAME                     ?= os-docs-$(OS_VERSION)
RHOSO_DOCS_GIT_URL             ?= ""
RHOSO_DOCS_GIT_BRANCH          ?= ""
RHOSO_DOCS_ATTRIBUTES_FILE_URL ?= ""
RHOSO_RELNOTES_GIT_URL         ?= ""
RHOSO_RELNOTES_GIT_BRANCH      ?= ""
RHOSO_CA_CERT_URL              ?= ""
OSLS_CONTAINER                 ?= quay.io/openstack-lightspeed/rag-content:latest
BUILD_UPSTREAM_DOCS            ?= true
DOCS_LINK_UNREACHABLE_ACTION   ?= warn
BUILD_EXTRA_ARGS               ?=
VECTOR_DB_TYPE                 ?= faiss
BUILD_OKP_CONTENT              ?= false
OKP_CONTENT                    ?= "all"
RHOSO_REMAP_TITLES             ?= {}
RHOSO_EXCLUDE_TITLES           ?= ""

# Define behavior based on the flavor
ifeq ($(FLAVOR),cpu)
TORCH_GROUP := cpu
BUILD_GPU_ARGS :=
else ifeq ($(FLAVOR),gpu)
TORCH_GROUP := gpu
# We cannot pass `--gpus all` instead because `podman build` doesn't support it
BUILD_GPU_ARGS ?= --device nvidia.com/gpu=all
else
$(error Unsupported FLAVOR $(FLAVOR), must be 'cpu' or 'gpu')
endif

build-image-os: ## Build a openstack rag-content container image
	podman build -t rag-content-openstack:$(INDEX_NAME) -f ./Containerfile \
	--build-arg FLAVOR=$(TORCH_GROUP) \
	--build-arg NUM_WORKERS=$(NUM_WORKERS) \
	--build-arg OS_PROJECTS=$(OS_PROJECTS) \
	--build-arg OS_VERSION=$(OS_VERSION) \
	--build-arg PRUNE_PATHS=$(PRUNE_PATHS) \
	--build-arg RHOSO_DOCS_GIT_URL=$(RHOSO_DOCS_GIT_URL) \
	--build-arg RHOSO_DOCS_GIT_BRANCH=$(RHOSO_DOCS_GIT_BRANCH) \
	--build-arg RHOSO_DOCS_ATTRIBUTES_FILE_URL=$(RHOSO_DOCS_ATTRIBUTES_FILE_URL) \
	--build-arg RHOSO_RELNOTES_GIT_URL=$(RHOSO_RELNOTES_GIT_URL) \
	--build-arg RHOSO_RELNOTES_GIT_BRANCH=$(RHOSO_RELNOTES_GIT_BRANCH) \
	--build-arg RHOSO_CA_CERT_URL=$(RHOSO_CA_CERT_URL) \
	--build-arg BUILD_UPSTREAM_DOCS=$(BUILD_UPSTREAM_DOCS) \
	--build-arg DOCS_LINK_UNREACHABLE_ACTION=$(DOCS_LINK_UNREACHABLE_ACTION) \
	--build-arg INDEX_NAME=$(INDEX_NAME) \
	--build-arg VECTOR_DB_TYPE=$(VECTOR_DB_TYPE) \
	--build-arg BUILD_OKP_CONTENT=$(BUILD_OKP_CONTENT) \
	--build-arg OKP_CONTENT=$(OKP_CONTENT) \
	--build-arg RHOSO_EXCLUDE_TITLES='$(RHOSO_EXCLUDE_TITLES)' \
	--build-arg RHOSO_REMAP_TITLES='$(RHOSO_REMAP_TITLES)' \
	$(BUILD_GPU_ARGS) .

get-embeddings-model: ## Download embeddings model from the openstack-lightspeed/rag-content container image
	podman create --replace --name tmp-rag-container $(OSLS_CONTAINER) true
	rm -rf embeddings_model
	podman cp tmp-rag-container:/rag/embeddings_model embeddings_model
	podman rm tmp-rag-container

help: ## Show this help screen
	@echo 'Usage: make <OPTIONS> ... <TARGETS>'
	@echo ''
	@echo 'Available targets are:'
	@echo ''
	@grep -E '^[ a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ''
