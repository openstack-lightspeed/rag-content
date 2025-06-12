#!/usr/bin/python3.11
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
"""Convert .adoc formatted RHOSO documentation to text formatted files."""

import argparse
from pathlib import Path
import logging
from lightspeed_rag_content.asciidoc import AsciidoctorConverter
from packaging.version import Version
from typing import Generator, Tuple
import xml.etree.ElementTree as ET
import re

LOG = logging.getLogger()
logging.basicConfig(level=logging.INFO)

DEFAULT_EXCLUDE_TITLES = [
    "hardening_red_hat_openstack_services_on_openshift",  # Replaced by ./configuring_security_services and ./performing_security_operations
    "integrating_openstack_identity_with_external_user_management_services",  # Replaced by configuring_security_services and performing_security_operations
    "firewall_rules_for_red_hat_openstack_platform",  # Not applicable to 18+
    "managing_overcloud_observability",  # Replaced by ./customizing_the_red_hat_openstack_services_on_openshift_deployment/master.txt
    "network_planning_(sandbox)",  # Content (other than MTU details) included in ./planning_your_deployment/master.txt
    "managing_secrets_with_the_key_manager_service",  # Replaced by ./performing_security_operations/master.txt
    "migrating_to_the_ovn_mechanism_driver",  # Not applicable to 18+
    "deploying_red_hat_openstack_platform_at_scale",  # Content is just a stub (WIP)
    "deploying_distributed_compute_nodes_with_separate_heat_stacks",  # Not applicable to 18+
    "installing_ember-csi_on_openshift_container_platform",  # Not applicable to 18+
    "introduction_to_red_hat_openstack_platform",  # Not applicable to 18+
    "red_hat_openstack_platform_benchmarking_service",  # Not applicable to 18+
    "backing_up_and_restoring_the_undercloud_and_control_plane_nodes",  # No content in this doc
    "configuring_dns_as_a_service",  # WIP, expected for RHOSO 18 FR3
]

DEFAULT_REMAP_TITLES = {
    "command_line_interface_(cli)_reference": "command_line_interface_reference"
}


def get_argument_parser() -> argparse.ArgumentParser:
    """Get ArgumentParser."""
    parser = argparse.ArgumentParser(
        description="Convert RHOSO AsciiDoc formatted documentation to text format.",
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "-i",
        "--input-dir",
        required=False,
        type=Path,
    )
    input_group.add_argument(
        "-n",
        "--relnotes-dir",
        required=False,
        type=Path,
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "-v",
        "--docs-version",
        required=False,
        default="18.0",
        type=str,
    )
    parser.add_argument(
        "-a",
        "--attributes-file",
        required=False,
        type=Path,
    )
    parser.add_argument(
        "-e",
        "--exclude-titles",
        required=False,
        type=str,
        nargs="+",
        default=DEFAULT_EXCLUDE_TITLES,
    )

    parser.add_argument(
        "-r",
        "--remap-titles",
        required=False,
        type=str,
        nargs="+",
        default=DEFAULT_REMAP_TITLES,
    )

    return parser


def get_xml_element_text(root_element: ET.Element, element_name) -> str | None:
    """Get text stored in XML element."""
    element = root_element.find(element_name)
    if element is None:
        LOG.warning(f"Can not find XML element => {element_name}")
        return None

    element_text = element.text
    if element_text is None:
        LOG.warning(f"No text found inside of element => {element_name}")
        return None

    return element_text


def red_hat_docs_path(
    input_dir: Path,
    output_dir: Path,
    docs_version: str,
    exclude_list: list,
    remap_titles: list,
) -> Generator[Tuple[Path, Path], None, None]:
    """Generate input and output path for asciidoctor based converter

    This function takes a look at master.adoc formatted files and based on the information
    provided in the docinfo.xml file stored within the same directory as the master.adoc
    file it generates pair of (input_path, output_path).

    The output path matches the path of that file in the published documentation (suffix
    of the URL).

    Args:
        input_dir:
            Directory containing the .adoc formatted files (searched using master.adoc regex)
        output_dir:
            Directory where the converted .adoc file should be stored.
    """
    for file in input_dir.rglob("master.adoc"):
        metadata_file_name = "docinfo.xml"
        docinfo = file.parent.joinpath(metadata_file_name)

        if not docinfo.exists():
            LOG.warning(f"{docinfo} can not be found. Skipping ...")
            continue

        with open(docinfo, "r") as f:
            # This is needed because docinfo.xml is not properly formatted XML file
            # because it does not contain a single root tag.
            docinfo_content = f.read()
            tree = ET.fromstring(f"<root>{docinfo_content}</root>")

            productnumber = get_xml_element_text(tree, "productnumber")
            if Version(productnumber) != Version(docs_version):
                LOG.warning(
                    f"{docinfo} productnumber {productnumber} != {docs_version}. Skipping ..."
                )
                continue

            if (path_title := get_xml_element_text(tree, "title")) is None:
                LOG.warning(f"{docinfo} title is blank. Skipping ...")
                continue

            path_title = path_title.lower().replace(" ", "_")

        if path_title in exclude_list:
            LOG.info(f"{path_title} is in exclude list. Skipping ...")
            continue

        if path_title in remap_titles:
            new_path_title = remap_titles[path_title]
            LOG.info(f"Remapping {path_title} to {new_path_title}.")
            path_title = new_path_title

        yield Path(file), output_dir / path_title / "master.txt"


def red_hat_relnotes_path(
    input_dir: Path, output_dir: Path, docs_version: str
) -> Generator[Tuple[Path, Path], None, None]:
    """Generate input and output path for asciidoctor based converter

    Args:
        input_dir:
            Directory containing the .adoc formatted files (searched for release-information docs)
        output_dir:
            Directory where the converted .adoc file should be stored.
    """
    ver_string = docs_version.replace(".", "-")
    globstring = (
        f"{ver_string}-[0-9]*/assembly_release-information-{ver_string}-[0-9]*.adoc"
    )
    for file in input_dir.rglob(globstring):
        if match := re.search(f"{ver_string}-\d+/.*-(\d+).adoc", str(file)):
            minor_ver_string = match.group(1).replace(".", "-")
            yield (
                Path(file),
                output_dir / f"release-notes/{ver_string}-{minor_ver_string}.txt",
            )
        else:
            LOG.warning(f"Failed to detect minor_ver of {file} with regex, skipping.")


if __name__ == "__main__":
    parser = get_argument_parser()
    args = parser.parse_args()

    if args.input_dir:
        adoc_text_converter = AsciidoctorConverter(attributes_file=args.attributes_file)
        for input_path, output_path in red_hat_docs_path(
            args.input_dir,
            args.output_dir,
            args.docs_version,
            args.exclude_titles,
            args.remap_titles,
        ):
            adoc_text_converter.convert(input_path, output_path)

    if args.relnotes_dir:
        adoc_text_converter = AsciidoctorConverter()
        for input_path, output_path in red_hat_relnotes_path(
            args.relnotes_dir,
            args.output_dir,
            args.docs_version,
        ):
            adoc_text_converter.convert(input_path, output_path)
