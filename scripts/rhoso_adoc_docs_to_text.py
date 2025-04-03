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

LOG = logging.getLogger()
logging.basicConfig(level=logging.INFO)


def get_argument_parser() -> argparse.ArgumentParser:
    """Get ArgumentParser."""
    parser = argparse.ArgumentParser(
        description="Convert RHOSO AsciiDoc formatted documentation to text format.",
    )
    parser.add_argument(
        "-i",
        "--input-dir",
        required=True,
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
    input_dir: Path, output_dir: Path, docs_version: str
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

        yield Path(file), output_dir / path_title / "master.txt"


if __name__ == "__main__":
    parser = get_argument_parser()
    args = parser.parse_args()

    adoc_text_converter = AsciidoctorConverter(attributes_file=args.attributes_file)
    for input_path, output_path in red_hat_docs_path(
        args.input_dir, args.output_dir, args.docs_version
    ):
        adoc_text_converter.convert(input_path, output_path)
