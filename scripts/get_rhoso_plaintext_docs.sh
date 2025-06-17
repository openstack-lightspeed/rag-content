#!/bin/bash
# Copyright 2025 Red Hat, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

set -eou pipefail

# URL of Git repository storing RHOSO documentation
RHOSO_DOCS_GIT_URL=${RHOSO_DOCS_GIT_URL:-}
[ -z "${RHOSO_DOCS_GIT_URL}" ] && echo "Err: Mising RHOSO_DOCS_GIT_URL!" && exit 1

# URL YAML file which containes RHOSO docs attributes.
RHOSO_DOCS_ATTRIBUTES_FILE_URL=${RHOSO_DOCS_ATTRIBUTES_FILE_URL:-}
[ -z "${RHOSO_DOCS_ATTRIBUTES_FILE_URL}" ] && echo "Err: Mising RHOSO_DOCS_ATTRIBUTES_FILE_URL!" && exit 1

# URL of Git repository for RHOSO release notes
RHOSO_RELNOTES_GIT_URL=${RHOSO_RELNOTES_GIT_URL:-}
[ -z "${RHOSO_RELNOTES_GIT_URL}" ] && echo "Err: Mising RHOSO_RELNOTES_GIT_URL!" && exit 1

# Branch to checkout for RHOSO release notes
RHOSO_RELNOTES_GIT_BRANCH=${RHOSO_RELNOTES_GIT_BRANCH:-main-external}

# Optional URL to download CA certificate for RHOSO Git repositories
RHOSO_CA_CERT_URL=${RHOSO_CA_CERT_URL:-}

# The name of the output directory
OUTPUT_DIR_NAME=${OUTPUT_DIR_NAME:-rhoso-docs-plaintext}

# Download CA certificate if URL is provided
CA_CERT_FILE=""
if [ -n "${RHOSO_CA_CERT_URL}" ]; then
    CA_CERT_FILE="ca.pem"
    echo "Downloading CA certificate from ${RHOSO_CA_CERT_URL}"
    curl -o "${CA_CERT_FILE}" "${RHOSO_CA_CERT_URL}"
fi

# Configure git and curl commands with CA certificate if available
if [ -f "${CA_CERT_FILE}" ]; then
    echo "Git and curl will use CA certificate from ${RHOSO_CA_CERT_URL}"
    git_clone() { git -c http.sslCAInfo="${CA_CERT_FILE}" clone "$@"; }
    curl_download() { curl -L --cacert "${CA_CERT_FILE}" "$@"; }
else
    echo "Warning: No CA certificate provided, skipping certificate validation"
    git_clone() { GIT_SSL_NO_VERIFY=true git clone "$@"; }
    curl_download() { curl -L -k "$@"; }
fi

# Clone RHOSO documentation and generate vector database for it
generate_text_docs_rhoso() {
    local rhoso_docs_folder="./rhoso_docs"
    local attributes_file="attributes.yaml"

    if [ ! -d "${rhoso_docs_folder}" ]; then
        git_clone "${RHOSO_DOCS_GIT_URL}" "${rhoso_docs_folder}"
    fi

    curl_download -o "${attributes_file}" "${RHOSO_DOCS_ATTRIBUTES_FILE_URL}"

    for subdir in "${rhoso_docs_folder}/titles" "${rhoso_docs_folder}"/doc-*; do
        python ./scripts/rhoso_adoc_docs_to_text.py \
            --input-dir "${subdir}" \
            --attributes-file "${attributes_file}" \
            --output-dir "$OUTPUT_DIR_NAME/"
    done
}

generate_relnotes_rhoso() {
    local rhoso_relnotes_folder="./rhoso_relnotes"

    if [ ! -d "${rhoso_relnotes_folder}" ]; then
        git_clone --single-branch -b "${RHOSO_RELNOTES_GIT_BRANCH}" "${RHOSO_RELNOTES_GIT_URL}" "${rhoso_relnotes_folder}"
    fi

    python ./scripts/rhoso_adoc_docs_to_text.py \
        --relnotes-dir "${rhoso_relnotes_folder}/manual-content/" \
        --output-dir "$OUTPUT_DIR_NAME/"
}

generate_text_docs_rhoso
generate_relnotes_rhoso
