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
OUTPUT_DIR_NAME=${OUTPUT_DIR_NAME:-openstack-operators-docs-markdown}

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

# Check if pandoc is available
if ! command -v pandoc &> /dev/null; then
  echo "Error: 'pandoc' is not installed, please install it before continuing." >&2
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

# Convert AsciiDoc files to markdown
echo "Converting AsciiDoc documentation to markdown..."

# Create output directory structure
mkdir -p "$WORKING_DIR/operators-docs-markdown"

# Function to convert adoc to markdown
convert_adoc_to_markdown() {
    local adoc_file=$1
    local output_file=$2

    # Convert AsciiDoc to HTML using asciidoctor, then HTML to Markdown using pandoc
    local temp_html="${adoc_file%.adoc}.html"
    asciidoctor -o "$temp_html" "$adoc_file"
    pandoc -f html -t markdown "$temp_html" -o "$output_file"
    rm "$temp_html"
}

# Process ctlplane documentation
if [ -f "ctlplane.adoc" ]; then
    echo "Converting ctlplane.adoc..."
    mkdir -p "$WORKING_DIR/operators-docs-markdown/ctlplane"
    convert_adoc_to_markdown "ctlplane.adoc" "$WORKING_DIR/operators-docs-markdown/ctlplane/index.md"
fi

# Process dataplane documentation
if [ -f "dataplane.adoc" ]; then
    echo "Converting dataplane.adoc..."
    mkdir -p "$WORKING_DIR/operators-docs-markdown/dataplane"
    convert_adoc_to_markdown "dataplane.adoc" "$WORKING_DIR/operators-docs-markdown/dataplane/index.md"
fi

# Exit docs directory
cd "$WORKING_DIR"

# Copy to final output directory
rm -rf "$CURR_DIR/$OUTPUT_DIR_NAME"
cp -r "$WORKING_DIR/operators-docs-markdown" "$CURR_DIR/$OUTPUT_DIR_NAME"

# Remove artifacts if requested
if [ "${CLEAN_FILES}" == "all" ]; then
    rm -rf "$WORKING_DIR"
fi

echo "Done. OpenStack operators documentation can be found at $CURR_DIR/$OUTPUT_DIR_NAME"
