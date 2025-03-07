#!/bin/bash
set -eou pipefail

# Check if 'tox' is available
if ! command -v tox &> /dev/null; then
  echo "Error: 'tox' is not installed, please install it before continuing." >&2
  exit 1
fi

# OpenStack Version
OS_VERSION=${OS_VERSION:-2024.2}

# List of OpenStack Projects
_OS_PROJECTS="nova horizon keystone neutron cinder manila glance swift ceilometer \
octavia designate heat placement ironic barbican aodh watcher"
OS_PROJECTS=${OS_PROJECTS:-$_OS_PROJECTS}

# Read the environment variable into an array
IFS=' ' read -r -a os_projects <<< "$OS_PROJECTS"

# Working directory
WORKING_DIR="/tmp/os_docs_temp"

# Tox text-docs target
TOX_TEXT_DOCS_TARGET="

[testenv:text-docs]
description =
    Build documentation in text format.
deps =
  -c{env:TOX_CONSTRAINTS_FILE:https://releases.openstack.org/constraints/upper/$OS_VERSION}
  -r{toxinidir}/doc/requirements.txt
commands =
  sphinx-build --keep-going -j auto -b text doc/source doc/build/text
"

# The current directory where the script was invoked
CURR_DIR=$(pwd)

# Number of availables CPUS
NUM_CPUS=$(nproc)

generate_text_doc() {
    local project=$1

    echo "Generating the plain-text documentation for OpenStack $project"

    # Clone the project's repository, if not present
    if [ ! -d "$project" ]; then
        git clone https://opendev.org/openstack/"$project".git
    fi

    cd "$project"
    git switch stable/"$OS_VERSION"
    git pull origin stable/"$OS_VERSION"

    # TODO(lpiwowar): Remove workarounds. Some of the documentations do not work with
    # the feature of sphinx-build that allows generation of the docs in text format.
    # List of issues:
    #    * designate = with custom ext.support_matrix extension the generation of the
    #                  documentation gets stuck in infinite loop
    #
    #    * ironic    = with sphinxcontrib.apidoc extension the generation of the
    #                  documentation gets stuck in infinite loop
    #
    #    * heat      = AttributeError: 'TextTranslator' object has no attribute '_classifier_count_in_li'
    #                  when doc/source/template_guide documentation is present
    if [ "$project" == "designate" ]; then
        sed -i "/'ext\.support_matrix',/d" "doc/source/conf.py"
    elif [ "$project" == "ironic" ]; then
        sed -i "/'sphinxcontrib\.apidoc',/d" "doc/source/conf.py"
    elif [ "$project" == "heat" ]; then
        rm -rf doc/source/template_guide/
    fi

    if grep -q "text-docs" tox.ini; then
        echo "The text-docs target exists for $project"
        # Add additional actions here if needed
    else
        echo "The text-docs target does not exist for $project. Appending it..."
        echo "$TOX_TEXT_DOCS_TARGET" >> tox.ini
    fi

    # Generate the docs in plain-text
    tox -etext-docs

    # Copy documentation to project's output directory
    local project_output_dir=$WORKING_DIR/openstack-docs-plaintext/$project
    rm -rf "$project_output_dir"
    mkdir -p "$project_output_dir"
    cp -r doc/build/text "$project_output_dir"/"$OS_VERSION"

    # Remove artifacts
    rm -rf "$project_output_dir"/"$OS_VERSION"/{_static/,.doctrees/}

    # Exit project's directory
    cd -
}

mkdir -p $WORKING_DIR
cd $WORKING_DIR
echo "Working directory: $WORKING_DIR"

num_running_proc=0
declare -a log_files
for os_project in "${os_projects[@]}"
do
    os_project_log_file=$(mktemp temp_os_project_XXXXX.log)
    log_files+=("${os_project_log_file}")
    echo "Generating documentation for ${os_project} (logs ${os_project_log_file})"
    generate_text_doc "$os_project" > "${os_project_log_file}" 2>&1 &

    num_running_proc=$((num_running_proc + 1))
    if [ ${num_running_proc} -ge "${NUM_CPUS}" ]; then
        echo "Running ${num_running_proc} processes in ${NUM_CPUS} CPUs environment. Waiting ..."
        wait -n
        num_running_proc=$((num_running_proc - 1))
    fi
done

echo "Waiting for the last process to finish the generation of the documentation."
wait
cat "${log_files[@]}"

rm -rf "$CURR_DIR"/openstack-docs-plaintext/*/"${OS_VERSION}"
cp -r "$WORKING_DIR"/openstack-docs-plaintext "$CURR_DIR"

# TODO(lucasagomes): Should we delete the working directory ?!
echo "Done. Documents can be found at $CURR_DIR/openstack-docs-plaintext"

