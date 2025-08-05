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
OS_VERSION=${OS_VERSION:-2024.2}

# TODO(lucasagomes): Look into adding the "tacker" project. Document generation
# for this project gets stuck in an infinite loop
# List of OpenStack Projects
_OS_PROJECTS="nova horizon keystone neutron cinder manila glance swift ceilometer \
octavia designate heat placement ironic barbican aodh watcher adjutant blazar \
cyborg magnum mistral skyline-apiserver skyline-console storlets \
venus vitrage zun python-openstackclient tempest trove zaqar masakari"
if [ -z "$OS_PROJECTS" ]; then
    OS_PROJECTS=$_OS_PROJECTS
fi

# List of paths to prune from final docs set. The default set are pages that
# are no longer published but are still generated from the git source
if [ "${PRUNE_PATHS:-}" == "" ]; then
    PRUNE_PATHS=(
        glance/2024.2/contributor/api/glance.common.format_inspector.txt
        neutron/2024.2/contributor/internals/linuxbridge_agent.txt
        neutron/2024.2/contributor/testing/ci_scenario_jobs.txt
        python-openstackclient/2024.2/contributor/api/openstackclient.volume.v1.txt
        python-openstackclient/2024.2/contributor/specs/command-objects/example.txt
        python-openstackclient/2024.2/contributor/specs/commands.txt
        python-openstackclient/2024.2/contributor/specs/network-topology.txt
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
# Usage:
#   generate_text_doc "nova"
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

    echo "Generating the plain-text documentation for OpenStack $project"
    # Clone the project's repository, if not present
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

    # Generate the docs in plain-text
    tox -etext-docs
    [ "${CLEAN_FILES}" == "venv" ] && rm -rf .tox/text-docs

    # These projects have all their docs under "latest" instead of "2024.2"
    if  [ "${project}" == "adjutant" ] || [ "${project}" == "cyborg" ] || [ "${project}" == "tempest" ] || [ "${project}" == "venus" ]; then
        _output_version="latest"
    else
        _output_version="${OS_VERSION}"
    fi

    # Copy documentation to project's output directory
    local project_output_dir=$WORKING_DIR/openstack-docs-plaintext/$project
    rm -rf "$project_output_dir"
    mkdir -p "$project_output_dir"
    cp -r doc/build/text "$project_output_dir"/"$_output_version"

    # Exit project's directory
    cd -

    # Remove artifacts
    [ "${CLEAN_FILES}" == "all" ] && rm -rf "$project"
    rm -rf "$project_output_dir"/"$_output_version"/{_static/,.doctrees/}
}

mkdir -p "$WORKING_DIR"
cd "$WORKING_DIR"
echo "Working directory: $WORKING_DIR"

for os_project in "${os_projects[@]}"; do
    os_project_log_file=$(mktemp "${os_project}"_XXXXX.log)
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
