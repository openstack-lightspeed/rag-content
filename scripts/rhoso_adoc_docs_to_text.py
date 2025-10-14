#!/usr/bin/python3.12
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
import json
from pathlib import Path
import logging
from lightspeed_rag_content.asciidoc import AsciidoctorConverter
from packaging.version import Version
from typing import Generator, Tuple
import xml.etree.ElementTree as ET
import re
import subprocess
import tempfile

LOG = logging.getLogger()
logging.basicConfig(level=logging.INFO)


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
        nargs="*",
        default=[],
        help="List of document titles to exclude from processing (e.g., 'release_notes' 'draft_guide')",
    )
    parser.add_argument(
        "-r",
        "--remap-titles",
        required=False,
        type=json.loads,
        default={},
        help='JSON mapping to rename document titles (e.g., \'{"old_title": "new_title"}\')',
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


class RelNotesConverter:
    """Convert AsciiDoc release notes to Markdown using asciidoctor and pandoc."""

    PANDOC_FILTER_PATH = (
        Path(__file__).parent / "filters/pandoc-release_notes-filter.py"
    ).absolute()

    def __init__(self, attributes_file: Path | None = None):
        self.attributes_file = attributes_file

    def convert(self, input_path: Path, output_path: Path) -> None:
        """Convert release notes from AsciiDoc to Markdown.

        This method uses a two-step conversion process:
        1. Convert AsciiDoc to DocBook5 XML using asciidoctor
        2. Convert DocBook5 XML to Markdown using pandoc with a custom filter

        Args:
            input_path: Path to input .adoc file
            output_path: Path to output .txt (markdown) file

        Raises:
            subprocess.CalledProcessError: If asciidoctor or pandoc command fails
        """
        LOG.info("Processing: %s", str(input_path.absolute()))

        # Create output directory if it doesn't exist
        if not output_path.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            LOG.warning(
                "Destination file %s exists. It will be overwritten!",
                output_path,
            )

        # Create temporary files for the conversion process
        adoc_temp = None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml") as xml_temp:
            try:
                xml_temp_path = Path(xml_temp.name)

                # If attributes file is provided, create a wrapper file with includes
                if self.attributes_file:
                    adoc_temp = tempfile.NamedTemporaryFile(mode="w", suffix=".adoc")
                    adoc_temp.write(
                        f"include::{self.attributes_file.absolute()}[]\n\ninclude::{input_path.absolute()}[]\n"
                    )
                    adoc_temp.flush()
                    input_for_conversion = Path(adoc_temp.name)
                else:
                    input_for_conversion = input_path

                # Step 1: Convert AsciiDoc to DocBook5 XML
                asciidoctor_cmd = [
                    "asciidoctor",
                    "-b",
                    "docbook5",
                    "-a",
                    "fn-private=pass",
                    "-o",
                    str(xml_temp_path.absolute()),
                    str(input_for_conversion.absolute()),
                ]
                subprocess.run(asciidoctor_cmd, check=True, capture_output=True)

                # Step 2: Convert DocBook5 XML to Markdown using pandoc with filter
                pandoc_cmd = [
                    "pandoc",
                    "-f",
                    "docbook",
                    "--wrap=preserve",
                    "-t",
                    "markdown_strict",
                    f"--filter={self.PANDOC_FILTER_PATH}",
                    str(xml_temp_path.absolute()),
                    "-o",
                    str(output_path.absolute()),
                ]
                subprocess.run(pandoc_cmd, check=True, capture_output=True)

                LOG.info("Successfully converted: %s -> %s", input_path, output_path)

            except Exception as e:
                LOG.error(
                    "Failed to convert: %s -> %s (%s)", input_path, output_path, e
                )
                raise

            finally:
                # Clean up temporary files
                if adoc_temp:
                    adoc_temp.close()


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
        relnotes_converter = RelNotesConverter(attributes_file=args.attributes_file)
        for input_path, output_path in red_hat_relnotes_path(
            args.relnotes_dir,
            args.output_dir,
            args.docs_version,
        ):
            relnotes_converter.convert(input_path, output_path)
