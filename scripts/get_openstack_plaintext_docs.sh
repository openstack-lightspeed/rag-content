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

PYTHON_VERSION=${PYTHON_VERSION:-3.12}
PYTHON="python${PYTHON_VERSION}"

# Check if 'tox' is available
if ! command -v tox &> /dev/null; then
  echo "Error: 'tox' is not installed, please install it before continuing." >&2
  exit 1
fi

if ! command -v "$PYTHON"  &> /dev/null; then
  echo "Error: '$PYTHON' is not installed, please install it before continuing." >&2
  exit 1
fi

# The name of the output directory
OUTPUT_DIR_NAME=${OUTPUT_DIR_NAME:-openstack-docs-plaintext}

# OpenStack Version
OS_VERSION=${OS_VERSION:-2025.2}

# Whether to include API-Ref documentation in the build
# Set to "true" to include API documentation (requires html2text tool)
# Set to "false" (default) to exclude API documentation
OS_API_DOCS=${OS_API_DOCS:-false}

# TODO(lucasagomes): Look into adding the "tacker" project. Document generation
# for this project gets stuck in an infinite loop
# List of OpenStack Projects
_OS_PROJECTS="nova horizon keystone neutron neutron-lib cinder manila glance \
swift ceilometer octavia designate heat placement ironic barbican aodh \
watcher adjutant blazar cyborg magnum mistral skyline-apiserver \
skyline-console storlets venus vitrage zun python-openstackclient tempest \
trove zaqar masakari"
OS_PROJECTS=${OS_PROJECTS:-$_OS_PROJECTS}

# List of paths to prune from final docs set. The default set are pages that
# are no longer published but are still generated from the git source
if [ "${PRUNE_PATHS:-}" == "" ]; then
    PRUNE_PATHS=(
        # 2024.2 projects (add _docs suffix)
        glance/2024.2_docs/contributor/api/glance.common.format_inspector.txt
        neutron/2024.2_docs/contributor/internals/linuxbridge_agent.txt
        neutron/2024.2_docs/contributor/testing/ci_scenario_jobs.txt
        python-openstackclient/2024.2_docs/contributor/api/openstackclient.volume.v1.txt
        python-openstackclient/2024.2_docs/contributor/specs/command-objects/example.txt
        python-openstackclient/2024.2_docs/contributor/specs/commands.txt
        python-openstackclient/2024.2_docs/contributor/specs/network-topology.txt
        # v2 API docs are not being published
        # https://docs.openstack.org/cinder/latest/contributor/api/cinder.api.v2.html
        # https://docs.openstack.org/cinder/latest/contributor/api/cinder.api.v3.html
        cinder/2025.2_docs/contributor/api/cinder.api.v2.limits.txt
        cinder/2025.2_docs/contributor/api/cinder.api.v2.snapshots.txt
        cinder/2025.2_docs/contributor/api/cinder.api.v2.views.txt
        cinder/2025.2_docs/contributor/api/cinder.api.v2.volume_metadata.txt
        cinder/2025.2_docs/contributor/api/cinder.api.v2.volumes.txt
        cinder/2025.2_docs/contributor/api/cinder.api.v2.views.volumes.txt
    )
fi

# Read the environment variable into an array
IFS=' ' read -r -a os_projects <<< "$OS_PROJECTS"

# Working directory
WORKING_DIR="${WORKING_DIR:-/tmp/os_docs_temp}"

# Whether to delete files on success or not.
# Acceptable values are "all", "venv", in other cases they are not deleted
CLEAN_FILES="${CLEAN_FILES:-}"

# The current directory where the script was invoked
CURR_DIR=$(pwd)

# Maximum number of subprocess that should run in parallel
NUM_WORKERS=${NUM_WORKERS:-$(nproc)}

# Files containing logs from subprocesses
declare -a LOG_FILES

# Show content of log files stored in LOG_FILES.
cat_log_files() {
    for log_file in "${LOG_FILES[@]}"; do
        echo "-- ${log_file} ---------------------------------------"
        cat "${log_file}"
        echo
    done
}

# Show content of the log files stored in LOG_FILES and exit with non-zero
# exit code.
# Arguments:
#   $1 - Error message that should be printed out to stderr
# Usage:
#   log_and_die "Sample error message"
log_and_die() {
    cat_log_files
    echo "ERROR: $1" >&2
    exit 1
}

# Clone repository from OpenDev and generate documentation in text format.
# Arguments:
#   $1 - Name of the OpenDev repository
#   $2 - Project version
# Usage:
#   generate_text_doc "nova" "2025.2"
generate_text_doc() {
    local project=$1
    local _os_version=$2
    local tox_text_docs_target="

[testenv:text-docs]
description =
    Build documentation in text format.
basepython = $PYTHON
commands =
  sphinx-build --keep-going -j auto -b text doc/source doc/build/text
deps =
  -c{env:TOX_CONSTRAINTS_FILE:https://releases.openstack.org/constraints/upper/$_os_version}
  -r{toxinidir}/doc/requirements.txt
"

    # API-Ref tox target definition (only used if OS_API_DOCS=true)
    local tox_text_api_ref_target="
[testenv:text-api-ref]
description =
    Build API reference documentation in HTML format.
commands =
  sphinx-build --keep-going -j auto -b html -d api-ref/build/doctrees api-ref/source api-ref/build/html
deps =
  -c{env:TOX_CONSTRAINTS_FILE:https://releases.openstack.org/constraints/upper/$_os_version}
  -r{toxinidir}/doc/requirements.txt
  os-api-ref
"

    echo "Generating the plain-text documentation for OpenStack $project"
    
    echo "OS_API_DOCS is set to: $OS_API_DOCS"

    # Clone the project's repository, if not present
    local branch_prefix=""
    if [ "$_os_version" != "master" ]; then
        branch_prefix="stable/"
    fi

    if [ ! -d "$project" ]; then
        git clone -v --depth=1 --single-branch -b "${branch_prefix}${_os_version}" https://opendev.org/openstack/"$project".git
    fi

    cd "$project"

    # TODO(lpiwowar): Remove workarounds. Some of the documentations do not work with
    # the feature of sphinx-build that allows generation of the docs in text format.
    # List of issues:
    #    * designate   = with custom ext.support_matrix extension the generation of the
    #                    documentation gets stuck in infinite loop
    #
    #    * ironic      = with sphinxcontrib.apidoc extension the generation of the
    #                    documentation gets stuck in infinite loop
    #
    #    * heat        = AttributeError: 'TextTranslator' object has no attribute '_classifier_count_in_li'
    #                    when doc/source/template_guide documentation is present
    #
    #    * trove/zaqar = The doc/requirements.txt file does not install all deps required to
    #                    generate the docs
    #
    if [ "$project" == "designate" ]; then
        sed -i "/'ext\.support_matrix',/d" "doc/source/conf.py"
    elif [ "$project" == "ironic" ]; then
        sed -i "/'sphinxcontrib\.apidoc',/d" "doc/source/conf.py"
    elif [ "$project" == "heat" ]; then
        rm -rf doc/source/template_guide/
    elif [[ "$project" == "trove" || "$project" == "zaqar" ]]; then
        tox_text_docs_target+="  -r{toxinidir}/requirements.txt"
    fi

    if grep -q "text-docs" tox.ini; then
        echo "The text-docs target exists for $project"
        # Add additional actions here if needed
    else
        echo "The text-docs target does not exist for $project. Appending it..."
        echo "$tox_text_docs_target" >> tox.ini
    fi

    # Build regular documentation (skip for neutron-lib)
    # neutron-lib is a library project that only generates API-Ref documentation.
    # Its regular doc build produces no usable output, but its API-Ref is needed by Neutron.
    if [ "$project" != "neutron-lib" ]; then
        tox -etext-docs
    fi
    [ "${CLEAN_FILES}" == "venv" ] && rm -rf .tox/text-docs

    # Build API-Ref if enabled
    if [ "$OS_API_DOCS" = "true" ] && [ -d "./api-ref/source" ]; then
        if ! grep -q "text-api-ref" tox.ini; then
            echo "$tox_text_api_ref_target" >> tox.ini
        fi

        local api_ref_failed="false"
        echo "Building API-Ref documentation for $project..."
        tox -etext-api-ref || api_ref_failed="true"

        if [ "$api_ref_failed" != "true" ]; then
            echo "Converting API-Ref HTML to plain text..."
            rm -rf ./api-ref/build/text
            mv ./api-ref/build/html ./api-ref/build/text

            # Convert HTML to text
            while read -r html_file; do
                text_file="${html_file%.html}.txt"
                [ -e "$html_file" ] && html2text "$html_file" utf8 > "$text_file"
            done <<< "$(find ./api-ref/build/text -name "*.html")"

            # Cleanup
            find ./api-ref/build/text -type f ! -name "*.txt" -delete
            find ./api-ref/build/text -mindepth 1 -depth -type d -empty -delete

            # Remove unpublished metadata (JIRA OSPRH-19255 requirement #1)
            find ./api-ref/build/text -name "genindex.txt" -delete
            find ./api-ref/build/text -name "search.txt" -delete
            find ./api-ref/build/text -path "*/_sources/*" -delete
            find ./api-ref/build/text -type d -name "_sources" -delete

            # index.txt and api_microversion_history.txt handling to prevent unreachable URLs
            api_file_count=$(find ./api-ref/build/text -name "*.txt" \
                ! -name "index.txt" ! -name "genindex.txt" \
                ! -name "search.txt" ! -name "api_microversion_history.txt" \
                -type f | wc -l)

            if [ "$api_file_count" -gt 0 ]; then
                # Has real API files - remove navigation files
                find ./api-ref/build/text -name "index.txt" -delete
                find ./api-ref/build/text -name "api_microversion_history.txt" -delete
            else
                # Only has index.txt - skip to avoid unreachable URLs
                echo "Skipping API-Ref for $project (no content files)"
                rm -rf ./api-ref/build/text
            fi

            find ./api-ref/build/text -mindepth 1 -depth -type d -empty -delete 2>/dev/null || true
        fi
    fi

    # These projects have all their docs under "latest" instead of "2025.2"
    if  [ "${project}" == "adjutant" ] || [ "${project}" == "cyborg" ] || [ "${project}" == "tempest" ] || [ "${project}" == "venus" ]; then
        _output_version="latest"
    else
        _output_version="${_os_version}"
    fi

    # Copy documentation to project's output directory
    local project_output_dir=$WORKING_DIR/openstack-docs-plaintext/$project
    rm -rf "$project_output_dir"
    mkdir -p "$project_output_dir"
    # Only copy if text docs were built (skipped for neutron-lib)
    [ -d "doc/build/text" ] && cp -r doc/build/text "$project_output_dir"/"$_output_version"_docs
    
    # Copy API-Ref documentation only if OS_API_DOCS is enabled and build succeeded
    if [ "$OS_API_DOCS" = "true" ] && [ -d "./api-ref/source" ] && \
       [ "$api_ref_failed" != "true" ] && [ -d "api-ref/build/text" ]; then
        cp -r api-ref/build/text "$project_output_dir"/"$_output_version"_api-ref
        echo "API-Ref documentation copied for $project"
    fi

    # Exit project's directory
    cd -

    # Remove artifacts
    [ "${CLEAN_FILES}" == "all" ] && rm -rf "$project"
    rm -rf "$project_output_dir"/"$_output_version"*/{_static/,.doctrees/}
}

mkdir -p "$WORKING_DIR"
cd "$WORKING_DIR"
echo "Working directory: $WORKING_DIR"

for os_project in "${os_projects[@]}"; do
    os_project_log_file=$(mktemp -t "${os_project}"_XXXXX.log)
    LOG_FILES+=("${os_project_log_file}")

    echo "Generating documentation for ${os_project}. [logs -> ${WORKING_DIR}/${os_project_log_file}]"
    _os_version=$OS_VERSION
    # The tempest project is branchless
    if [ "${os_project}" == "tempest" ]; then
        _os_version="master"
    fi
    generate_text_doc "$os_project" "$_os_version" > "${os_project_log_file}" 2>&1 &

    num_running_subproc=$(jobs -r | wc -l)
    if [ "${num_running_subproc}" -ge "${NUM_WORKERS}" ]; then
        echo "Using ${num_running_subproc}/${NUM_WORKERS} workers. Waiting ..."
        wait -n || log_and_die "Subprocess generating text documentation failed!"
	echo "Using $(( --num_running_subproc ))/${NUM_WORKERS} workers."
    fi
done

echo "Waiting for the last subprocess to finish the documentation generation."
for subproc_pid in $(jobs -p); do
    wait "${subproc_pid}" || log_and_die "Subprocess generating text documentation failed!"
    echo "Using $(jobs -r | wc -l)/${NUM_WORKERS} workers."
done
cat_log_files

pushd "${WORKING_DIR}/openstack-docs-plaintext"
for path in "${PRUNE_PATHS[@]}"; do
    rm -f -- "$path"
done
popd

rm -rf "$CURR_DIR"/openstack-docs-plaintext/*/"${OS_VERSION}"
cp -r "$WORKING_DIR"/openstack-docs-plaintext "$CURR_DIR/$OUTPUT_DIR_NAME"

# TODO(lucasagomes): Should we delete the working directory ?!
echo "Done. Documents can be found at $CURR_DIR/$OUTPUT_DIR_NAME"
