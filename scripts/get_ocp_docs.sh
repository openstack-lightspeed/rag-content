#!/bin/bash
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
set -x

OLS_DOC_REPO=${OLS_DOC_REPO:-"https://github.com/openshift/lightspeed-rag-content.git"}
# OpenShift Versions to create DBs for
# If we set it to empty string, it will generate all the available ones.
OCP_VERSIONS=${OCP_VERSIONS:-"4.16 4.18 latest"}

SCRIPT_DIR="$(realpath "$( dirname -- "${BASH_SOURCE[0]}" )")"

# The current directory where the script was invoked
CURR_DIR=$(pwd)
# The name of the output directory
OUTPUT_DIR_NAME=${OUTPUT_DIR_NAME:-ocp-product-docs-plaintext}
# Ensure OUTPUT_DIR_NAME is an absolute path
if [[ $OUTPUT_DIR_NAME != /* ]]; then
    OUTPUT_DIR_NAME="${CURR_DIR}/${OUTPUT_DIR_NAME}"
fi

# Working directory
WORKING_DIR="${WORKING_DIR:-/tmp/ocp_docs_temp}"

mkdir -p "$WORKING_DIR"
cd "$WORKING_DIR"
echo "Working directory: $WORKING_DIR"

if [ ! -d lightspeed-rag-content ]; then
    git clone -v --depth=1 --single-branch "$OLS_DOC_REPO" lightspeed-rag-content
fi
# If "all" versions, we need to list them ourselves
if [ "$OCP_VERSIONS" == "all" ]; then
    OCP_VERSIONS="$(find lightspeed-rag-content/ocp-product-docs-plaintext/* -maxdepth 0 -printf '%f ')"
fi

# Read the environment variable into an array
IFS=' ' read -r -a ocp_versions <<< "$OCP_VERSIONS"

mkdir -p "${OUTPUT_DIR_NAME}"

# Copy their script instead of implementing it ourselves
mv -f lightspeed-rag-content/scripts/generate_embeddings.py "${OUTPUT_DIR_NAME}/ocp_generate_embeddings.py"
rm -rf "${OUTPUT_DIR_NAME}/common_alerts"
mv lightspeed-rag-content/runbooks/alerts "${OUTPUT_DIR_NAME}/common_alerts"


for ocp_version in "${ocp_versions[@]}"; do
    if [[ ! -f "$SCRIPT_DIR/ocp_exclude_docs.conf" ]]; then
        echo "No exclude docs file found at $SCRIPT_DIR/ocp_exclude_docs.conf, including all docs"
    else
        echo "Removing unwanted docs for ${ocp_version}"
        while IFS= read -r line; do
            # Ignore lines that starts with a # or if it's empty
            if [[ $line == \#* || -z $line ]]; then
                continue
            fi

            echo "Removing ${line} for ${ocp_version}"
            rm -rf "lightspeed-rag-content/ocp-product-docs-plaintext/${ocp_version}/${line}"
        done < "$SCRIPT_DIR/ocp_exclude_docs.conf"
    fi

    if [[ "${ocp_version}" == "latest" ]]; then
        ocp_version="$(find lightspeed-rag-content/ocp-product-docs-plaintext/ -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -V | tail -n 1)"
        echo "Latest version is ${ocp_version}"
    fi

    echo "Moving docs for ${ocp_version}"
    doc_source="lightspeed-rag-content/ocp-product-docs-plaintext/${ocp_version}"
    destination="${OUTPUT_DIR_NAME}/${ocp_version}"
    rm -rf "${destination}"
    mv "${doc_source}" "${destination}"
done

rm -rf lightspeed-rag-content
echo "Done. Documents can be found at $CURR_DIR/$OUTPUT_DIR_NAME"

cd "${CURR_DIR}"
