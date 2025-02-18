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
_OS_PROJECTS="nova neutron cinder keystone glance swift"
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

mkdir -p $WORKING_DIR
cd $WORKING_DIR
echo "Working directory: $WORKING_DIR"

for project in "${os_projects[@]}"; do
    echo "Generating the plain-text documentation for OpenStack $project"

    # Clone the project's repository, if not present
    if [ ! -d "$project" ]; then
        git clone https://opendev.org/openstack/$project.git
    fi

    cd $project
    git switch stable/$OS_VERSION
    git pull origin stable/$OS_VERSION

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
    project_output_dir=$WORKING_DIR/openstack-docs-plaintext/$project
    rm -rf $project_output_dir
    mkdir -p $project_output_dir
    cp -r doc/build/text $project_output_dir/$OS_VERSION

    # Remove artifacts
    rm -rf $project_output_dir/$OS_VERSION/{_static/,.doctrees/}

    # Exit project's directory
    cd -
done

rm -rf $CURR_DIR/openstack-docs-plaintext/*/${OS_VERSION}
cp -r $WORKING_DIR/openstack-docs-plaintext $CURR_DIR

# TODO(lucasagomes): Should we delete the working directory ?!
echo "Done. Documents can be found at $CURR_DIR/openstack-docs-plaintext"