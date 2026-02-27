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
set -x

# The name of the output directory
OUTPUT_DIR_NAME=${OUTPUT_DIR_NAME:-openstack-operators-docs-plaintext}

# GitHub repository details
OPERATORS_REPO_URL=${OPERATORS_REPO_URL:-https://github.com/openstack-k8s-operators/openstack-operator.git}
OPERATORS_BRANCH=${OPERATORS_BRANCH:-main}

# Working directory
WORKING_DIR="${WORKING_DIR:-/tmp/os_operators_docs_temp}"

# Whether to delete files on success or not.
# Acceptable values are "all", "venv", in other cases they are not deleted
CLEAN_FILES="${CLEAN_FILES:-}"

# The current directory where the script was invoked
CURR_DIR=$(pwd)

echo "Fetching OpenStack operators documentation"

# Check if asciidoctor is available
if ! command -v asciidoctor &> /dev/null; then
  echo "Error: 'asciidoctor' is not installed, please install it before continuing." >&2
  exit 1
fi

# Check if html2text is available
if ! command -v html2text &> /dev/null; then
  echo "Error: 'html2text' is not installed, please install it before continuing." >&2
  exit 1
fi

mkdir -p "$WORKING_DIR"
cd "$WORKING_DIR"
echo "Working directory: $WORKING_DIR"

# Clone the repository if not present
if [ ! -d "openstack-operator" ]; then
    git clone -v --depth=1 --single-branch -b "${OPERATORS_BRANCH}" "${OPERATORS_REPO_URL}"
fi

cd openstack-operator/docs

# Convert AsciiDoc files to plain text
echo "Converting AsciiDoc documentation to plain text..."

# Create output directory structure
mkdir -p "$WORKING_DIR/operators-docs-text/ctlplane"
mkdir -p "$WORKING_DIR/operators-docs-text/dataplane"

# Function to convert adoc to text
convert_adoc_to_text() {
    local adoc_file=$1
    local output_file=$2
    local temp_html="${adoc_file%.adoc}.html"

    # Convert AsciiDoc to HTML
    asciidoctor "$adoc_file" -o "$temp_html"

    # Convert HTML to plain text
    html2text "$temp_html" utf8 > "$output_file"

    # Clean up temporary HTML file
    rm -f "$temp_html"
}

# Process ctlplane documentation
if [ -f "ctlplane.adoc" ]; then
    echo "Converting ctlplane.adoc..."
    convert_adoc_to_text "ctlplane.adoc" "$WORKING_DIR/operators-docs-text/ctlplane/index.txt"
fi

# Process dataplane documentation
if [ -f "dataplane.adoc" ]; then
    echo "Converting dataplane.adoc..."
    convert_adoc_to_text "dataplane.adoc" "$WORKING_DIR/operators-docs-text/dataplane/index.txt"
fi

# Process any additional adoc files in assemblies directory
if [ -d "assemblies" ]; then
    echo "Processing assemblies directory..."
    find assemblies -name "*.adoc" -type f | while read -r adoc_file; do
        # Get relative path and convert to output path
        rel_path="${adoc_file#assemblies/}"
        output_path="$WORKING_DIR/operators-docs-text/assemblies/${rel_path%.adoc}.txt"
        output_dir=$(dirname "$output_path")

        mkdir -p "$output_dir"
        echo "Converting $adoc_file..."
        convert_adoc_to_text "$adoc_file" "$output_path"
    done
fi

# Exit docs directory
cd "$WORKING_DIR"

# Copy to final output directory
rm -rf "$CURR_DIR/$OUTPUT_DIR_NAME"
cp -r "$WORKING_DIR/operators-docs-text" "$CURR_DIR/$OUTPUT_DIR_NAME"

# Remove artifacts if requested
if [ "${CLEAN_FILES}" == "all" ]; then
    rm -rf "$WORKING_DIR"
fi

echo "Done. OpenStack operators documentation can be found at $CURR_DIR/$OUTPUT_DIR_NAME"
