# Default to CPU if not specified
FLAVOR                         ?= cpu
NUM_WORKERS                    ?= $$(( $(shell nproc --all) / 2))
OS_VERSION                     ?= 2024.2
INDEX_NAME                     ?= os-docs-$(OS_VERSION)
RHOSO_DOCS_GIT_URL             ?= ""
RHOSO_DOCS_ATTRIBUTES_FILE_URL ?= ""
OSLS_CONTAINER                 ?= quay.io/openstack-lightspeed/rag-content:latest

# Define behavior based on the flavor
ifeq ($(FLAVOR),cpu)
TORCH_GROUP := cpu
else ifeq ($(FLAVOR),gpu)
TORCH_GROUP := gpu
else
$(error Unsupported FLAVOR $(FLAVOR), must be 'cpu' or 'gpu')
endif

build-image-os: ## Build a openstack rag-content container image
	podman build -t rag-content-openstack:latest -f ./Containerfile \
	--build-arg FLAVOR=$(TORCH_GROUP) \
	--build-arg NUM_WORKERS=$(NUM_WORKERS) \
	--build-arg OS_PROJECTS=$(OS_PROJECTS) \
	--build-arg OS_VERSION=$(OS_VERSION) \
	--build-arg RHOSO_DOCS_GIT_URL=$(RHOSO_DOCS_GIT_URL) \
	--build-arg RHOSO_DOCS_ATTRIBUTES_FILE_URL=$(RHOSO_DOCS_ATTRIBUTES_FILE_URL) \
	--build-arg INDEX_NAME=$(INDEX_NAME) .

get-embeddings:
	podman create --replace --name tmp-rag-container $(OSLS_CONTAINER) true
	rm -rf vector_db embeddings_model
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
