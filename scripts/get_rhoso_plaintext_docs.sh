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

# The name of the output directory
OUTPUT_DIR_NAME=${OUTPUT_DIR_NAME:-rhoso-docs-plaintext}

# Clone RHOSO documentation and generate vector database for it
generate_text_docs_rhoso() {
    local rhoso_docs_folder="./rhoso_docs"
    local attributes_file="attributes.yaml"

    # TODO(lpiwowar): Remove GIT_SSL_NO_VERIFY
    if [ ! -d "${rhoso_docs_folder}" ]; then
        GIT_SSL_NO_VERIFY=true git clone "${RHOSO_DOCS_GIT_URL}" "${rhoso_docs_folder}"
    fi

    # TODO(lpiwowar): Remove -k (skips validation of the certificate)
    curl -L -k -o "${attributes_file}" "${RHOSO_DOCS_ATTRIBUTES_FILE_URL}"

    for subdir in "${rhoso_docs_folder}/titles" "${rhoso_docs_folder}"/doc-*; do
        python ./scripts/rhoso_adoc_docs_to_text.py \
            --input-dir "${subdir}" \
            --attributes-file "${attributes_file}" \
            --output-dir "$OUTPUT_DIR_NAME/"
    done
}

generate_text_docs_rhoso
