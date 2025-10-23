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
from packaging.version import Version
from typing import Generator, Tuple
import xml.etree.ElementTree as ET
import re
import subprocess
import tempfile

LOG = logging.getLogger()
logging.basicConfig(level=logging.INFO)

# Output file extension for converted documents
OUTPUT_FILE_EXTENSION = ".txt"


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

        yield Path(file), output_dir / path_title / f"master{OUTPUT_FILE_EXTENSION}"


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
        if match := re.search(rf"{ver_string}-\d+/.*-(\d+).adoc", str(file)):
            minor_ver_string = match.group(1).replace(".", "-")
            yield (
                Path(file),
                output_dir
                / f"release-notes/{ver_string}-{minor_ver_string}{OUTPUT_FILE_EXTENSION}",
            )
        else:
            LOG.warning(f"Failed to detect minor_ver of {file} with regex, skipping.")


def preprocess_adoc_tables(content: str) -> str:
    """Preprocess AsciiDoc content to fix common table issues.

    AI: method generated by Cursor

    Args:
        content: The raw AsciiDoc content as a string

    Returns:
        Preprocessed content with table issues fixed
    """
    lines = content.split("\n")
    new_lines = []
    in_table = False
    table_start_idx = -1
    table_lines = []

    for i, line in enumerate(lines):
        # Detect table start
        if line.startswith("|==="):
            if not in_table:
                # Starting a new table
                in_table = True
                table_start_idx = len(new_lines)
                table_lines = [line]
            else:
                # Ending a table
                table_lines.append(line)

                # Check if table has at least one body row
                # Table structure: |===, optional header row, body rows, |===
                # Body rows are those that contain | and are not the delimiters
                body_rows = [
                    line
                    for line in table_lines[1:-1]
                    if line.strip() and not line.startswith("|===")
                ]

                if len(body_rows) == 0:
                    # Empty table - add a placeholder row
                    LOG.warning(
                        f"Found empty table at line {table_start_idx}, adding placeholder row"
                    )
                    # Insert a placeholder row before the closing |===
                    table_lines.insert(-1, "| N/A | N/A")

                new_lines.extend(table_lines)
                in_table = False
                table_lines = []
        elif in_table:
            table_lines.append(line)
        else:
            new_lines.append(line)

    # Handle case where table wasn't closed
    if in_table and table_lines:
        LOG.warning("Found unclosed table, closing it")
        table_lines.append("|===")
        new_lines.extend(table_lines)

    return "\n".join(new_lines)


def find_adoc_base_dir(input_path: Path) -> Path:
    """Find the base directory for AsciiDoc includes.

    AI: Method generated by Cursor

    This function walks up the directory tree from the input file to find
    a suitable base directory that contains common documentation directories
    like 'assemblies', 'common', 'titles', etc.

    Args:
        input_path: Path to the input .adoc file

    Returns:
        The base directory path for resolving includes
    """
    current = input_path.parent

    # Walk up the directory tree looking for common doc directories
    for _ in range(5):  # Limit search depth to avoid going too far up
        # Check if this directory contains typical doc structure markers
        if any(
            (current / marker).exists()
            for marker in ["assemblies", "common", "titles", "acorns", "manual-content"]
        ):
            return current

        # Move up one directory
        if current.parent == current:  # Reached root
            break
        current = current.parent

    # If we didn't find a suitable base directory, use the input file's parent
    # (this is the fallback for simple cases)
    return input_path.parent


def fix_xml_nesting_with_parser(xml_content: str) -> str:
    """Fix XML nesting issues using regex to find and repair malformed patterns.

    AI: Method generated by Cursor

    This function specifically targets the pattern where link and literal tags
    are improperly nested due to square brackets in AsciiDoc source:
    <link><literal>text[more</link> more</literal>]

    The fix moves content between </link> and </literal> inside the literal tags.

    Args:
        xml_content: The DocBook XML content as a string

    Returns:
        XML content with nesting issues fixed
    """
    fixes_applied = 0

    # Pattern: <link><literal>content</link>MORE_CONTENT</literal>TRAILING
    # We need to move MORE_CONTENT before </literal> and then add </link>
    # Result: <link><literal>contentMORE_CONTENT</literal></link>TRAILING

    # This regex captures:
    # 1. Opening tags: <link...><literal...>
    # 2. Content before </link>
    # 3. The </link> tag
    # 4. Content between </link> and </literal> (excluding ']' and whitespace at end)
    # 5. The </literal> tag

    # Use a more precise pattern that doesn't consume trailing content
    pattern = r"(<link[^>]*>)(<literal[^>]*>)(.*?)(</link>)\s*([^<]*?)(</literal>)"

    def fix_match(match):
        link_open = match.group(1)
        literal_open = match.group(2)
        content_before = match.group(3)
        link_close = match.group(4)
        content_after = match.group(5)
        literal_close = match.group(6)

        # Only fix if there's actually non-whitespace content between </link> and </literal>
        # This indicates the malformed pattern
        if content_after and not content_after.isspace():
            nonlocal fixes_applied
            fixes_applied += 1
            # Combine content inside literal tags, then close both properly
            # Keep spacing as it was
            return f"{link_open}{literal_open}{content_before}{content_after}{literal_close}{link_close}"
        else:
            # No issue, return original
            return match.group(0)

    result = re.sub(pattern, fix_match, xml_content, flags=re.DOTALL)

    if fixes_applied > 0:
        LOG.info(f"Fixed {fixes_applied} XML nesting issues with parser-based approach")

    return result


def fix_xml_nesting_issues(xml_content: str) -> str:
    """Fix common XML nesting issues in DocBook.

    AI: Method generated by Cursor

    This function fixes malformed nested inline elements that can occur when
    asciidoctor converts AsciiDoc to DocBook. Common issues include:
    - <link><literal>...</link></literal> (wrong closing order)
    - <link><literal>text1</link>text2</literal> (content spans closing tags)
    - Other improperly nested inline elements

    Args:
        xml_content: The DocBook XML content as a string

    Returns:
        XML content with nesting issues fixed
    """
    # Strategy: Handle the most complex cases first, then simpler ones

    # Pattern 1: DISABLED - these patterns break correct XML generated by asciidoctor
    # asciidoctor correctly generates <link><literal>...</literal></link>
    # DO NOT add missing close tags as they don't exist in this codebase
    missing_close_patterns = [
        # Intentionally empty - asciidoctor generates correct closing tags
    ]

    # Pattern 2: Handle cases where content spans the closing tags
    # VERY SPECIFIC: Only matches when there's content BETWEEN </link> and </literal>
    # Example: <link><literal>text1</link>text2</literal> where text2 is non-empty
    # Solution: Move </link> to after </literal>
    spanning_patterns = [
        # <link><literal>text</link>MORE_TEXT</literal> -> <link><literal>textMORE_TEXT</literal></link>
        # Use .+ (one or more) instead of .*? to ensure there's content between tags
        (
            r"(<link[^>]*>)(<literal[^>]*>)(.*?)(</link>)(.+?)(</literal>)",
            r"\1\2\3\5\6\4",
        ),
        # Same for other combinations, but only if there's content between
        (
            r"(<literal[^>]*>)(<link[^>]*>)(.*?)(</literal>)(.+?)(</link>)",
            r"\1\2\3\5\6\4",
        ),
        (r"(<link[^>]*>)(<code[^>]*>)(.*?)(</link>)(.+?)(</code>)", r"\1\2\3\5\6\4"),
        (r"(<code[^>]*>)(<link[^>]*>)(.*?)(</code>)(.+?)(</link>)", r"\1\2\3\5\6\4"),
        (
            r"(<link[^>]*>)(<emphasis[^>]*>)(.*?)(</link>)(.+?)(</emphasis>)",
            r"\1\2\3\5\6\4",
        ),
        (
            r"(<emphasis[^>]*>)(<link[^>]*>)(.*?)(</emphasis>)(.+?)(</link>)",
            r"\1\2\3\5\6\4",
        ),
    ]

    # Pattern 3: DISABLED - these patterns break correct XML
    # asciidoctor generates correct closing order
    simple_patterns = [
        # Intentionally empty
    ]

    # Pattern 4: DISABLED - test with only spanning patterns first
    complex_patterns = [
        # Intentionally empty for now
    ]

    result = xml_content
    total_fixes = 0
    max_iterations = 1  # Single pass to avoid cascading issues

    # Apply fixes iteratively until no more changes occur
    for iteration in range(max_iterations):
        previous_result = result
        iteration_fixes = 0

        # Apply patterns in order: missing close tags first, then spanning cases, then simple, then complex
        for i, (pattern, replacement) in enumerate(missing_close_patterns):
            matches = re.findall(pattern, result, flags=re.DOTALL)
            if matches:
                LOG.debug(
                    f"Iteration {iteration}, Missing close pattern {i} found {len(matches)} matches"
                )
                iteration_fixes += len(matches)
                result = re.sub(pattern, replacement, result, flags=re.DOTALL)

        for pattern, replacement in spanning_patterns:
            matches = re.findall(pattern, result, flags=re.DOTALL)
            if matches:
                iteration_fixes += len(matches)
                result = re.sub(pattern, replacement, result, flags=re.DOTALL)

        # Then simple patterns
        for pattern, replacement in simple_patterns:
            matches = re.findall(pattern, result)
            if matches:
                iteration_fixes += len(matches)
                result = re.sub(pattern, replacement, result)

        # Finally complex patterns with DOTALL flag
        for pattern, replacement in complex_patterns:
            matches = re.findall(pattern, result, flags=re.DOTALL)
            if matches:
                iteration_fixes += len(matches)
                result = re.sub(pattern, replacement, result, flags=re.DOTALL)

        total_fixes += iteration_fixes

        # If no changes were made in this iteration, we're done
        if result == previous_result:
            break

    if total_fixes > 0:
        LOG.info(
            f"Fixed {total_fixes} XML nesting issues in {iteration + 1} iteration(s)"
        )

    return result


def preprocess_xml_list_titles(xml_content: str) -> str:
    """Preprocess XML to convert list titles to formalpara elements.

    AI: Method generated by Cursor

    Pandoc doesn't preserve <itemizedlist><title> or <orderedlist><title> elements
    when converting from DocBook. This function converts them to <formalpara><title>
    elements which pandoc does convert to Div.formalpara-title.

    Args:
        xml_content: The DocBook XML content as a string

    Returns:
        Preprocessed XML with list titles converted to formalpara
    """
    try:
        # Parse the XML
        root = ET.fromstring(xml_content)

        # Define the DocBook namespace
        ns = {"db": "http://docbook.org/ns/docbook"}

        # Find all itemizedlist and orderedlist elements with title children
        for list_type in ["itemizedlist", "orderedlist"]:
            for list_elem in root.findall(f".//{{{ns['db']}}}{list_type}", ns):
                # Check if it has a title child
                title_elem = list_elem.find(f"{{{ns['db']}}}title", ns)
                if title_elem is not None:
                    # Get the parent of the list
                    parent = None
                    for potential_parent in root.iter():
                        if list_elem in potential_parent:
                            parent = potential_parent
                            break

                    if parent is not None:
                        # Get the index of the list in its parent
                        list_index = list(parent).index(list_elem)

                        # Remove the title from the list
                        list_elem.remove(title_elem)

                        # Create a formalpara element with the title
                        formalpara = ET.Element(f"{{{ns['db']}}}formalpara")
                        # Move the title to the formalpara
                        formalpara.append(title_elem)
                        # Add an empty para as formalpara requires it
                        # para = ET.SubElement(formalpara, f'{{{ns["db"]}}}para')

                        # Insert the formalpara before the list
                        parent.insert(list_index, formalpara)

        # Convert back to string
        return ET.tostring(root, encoding="unicode")
    except Exception as e:
        LOG.warning(f"Failed to preprocess XML list titles: {e}")
        # Return original content if preprocessing fails
        return xml_content


class RelNotesConverter:
    """Convert AsciiDoc release notes to Markdown using asciidoctor and pandoc."""

    PANDOC_FILTER_PATH = (
        Path(__file__).parent / "filters/pandoc-release_notes-filter.py"
    ).absolute()
    PANDOC_LUA_FILTER_PATH = (
        Path(__file__).parent / "filters/tightlists.lua"
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
                base_dir = find_adoc_base_dir(input_path)

                # If attributes file is provided, create a wrapper file with includes
                # The wrapper file must be in the base directory structure, not /tmp/
                if self.attributes_file:
                    adoc_temp = tempfile.NamedTemporaryFile(
                        mode="w",
                        suffix=".adoc",
                        dir=str(base_dir.absolute()),
                        delete=False,
                    )
                    adoc_temp.write(
                        f"include::{self.attributes_file.absolute()}[]\n\ninclude::{input_path.absolute()}[]\n"
                    )
                    adoc_temp.flush()
                    adoc_temp.close()
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
                    "--base-dir",
                    str(base_dir.absolute()),
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
                    f"--lua-filter={self.PANDOC_LUA_FILTER_PATH}",
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
                if adoc_temp and Path(adoc_temp.name).exists():
                    Path(adoc_temp.name).unlink()


class DocsConverter:
    """Convert AsciiDoc documentation to Markdown using asciidoctor and pandoc.

    AI: Class generated by Cursor
    """

    PANDOC_FILTER_PATH = (
        Path(__file__).parent / "filters/pandoc-docs-filter.py"
    ).absolute()
    PANDOC_LUA_FILTER_PATH = (
        Path(__file__).parent / "filters/tightlists.lua"
    ).absolute()

    def __init__(self, attributes_file: Path | None = None):
        self.attributes_file = attributes_file

    def convert(self, input_path: Path, output_path: Path) -> None:
        """Convert documentation from AsciiDoc to Markdown.

        This method uses a multi-step conversion process:
        1. Preprocess AsciiDoc to fix common table issues
        2. Convert AsciiDoc to DocBook5 XML using asciidoctor
        3. Preprocess XML to convert list titles to formalpara elements
        4. Convert DocBook5 XML to Markdown using pandoc with custom filters

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
        preprocessed_temp = None
        try:
            # Find base directory first, as we need it for temp file creation
            base_dir = find_adoc_base_dir(input_path)

            # Read and preprocess the input file
            with open(input_path, "r", encoding="utf-8") as f:
                content = f.read()

            preprocessed_content = preprocess_adoc_tables(content)

            # Create temporary file with preprocessed content in the base directory
            preprocessed_temp = tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".adoc",
                delete=False,
                encoding="utf-8",
                dir=str(base_dir.absolute()),
            )
            preprocessed_temp.write(preprocessed_content)
            preprocessed_temp.flush()
            preprocessed_temp.close()
            preprocessed_path = Path(preprocessed_temp.name)

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", delete=False
            ) as xml_temp:
                xml_temp_path = Path(xml_temp.name)
                xml_temp.close()

                try:
                    # If attributes file is provided, create a wrapper file with includes
                    # The wrapper file must be in the base directory structure
                    if self.attributes_file:
                        adoc_temp = tempfile.NamedTemporaryFile(
                            mode="w",
                            suffix=".adoc",
                            delete=False,
                            encoding="utf-8",
                            dir=str(base_dir.absolute()),
                        )
                        adoc_temp.write(
                            f"include::{self.attributes_file.absolute()}[]\n\ninclude::{preprocessed_path.absolute()}[]\n"
                        )
                        adoc_temp.flush()
                        adoc_temp.close()
                        input_for_conversion = Path(adoc_temp.name)
                    else:
                        input_for_conversion = preprocessed_path

                    # Step 1: Convert AsciiDoc to DocBook5 XML
                    asciidoctor_cmd = [
                        "asciidoctor",
                        "-b",
                        "docbook5",
                        "-d",
                        "book",
                        "-a",
                        "fn-private=pass",
                        "--base-dir",
                        str(base_dir.absolute()),
                        "-o",
                        str(xml_temp_path.absolute()),
                        str(input_for_conversion.absolute()),
                    ]
                    result = subprocess.run(
                        asciidoctor_cmd, check=True, capture_output=True, text=True
                    )
                    if result.stderr:
                        LOG.warning(
                            "asciidoctor warnings for %s:\n%s",
                            input_path,
                            result.stderr,
                        )

                    # Step 1.5: Preprocess XML to fix nesting issues and convert list titles
                    with open(xml_temp_path, "r", encoding="utf-8") as f:
                        xml_content = f.read()

                    # First fix nesting issues with inline elements
                    # Use targeted parser-based fix for specific malformed patterns
                    xml_content = fix_xml_nesting_with_parser(xml_content)

                    # Then convert list titles to formalpara
                    preprocessed_xml = preprocess_xml_list_titles(xml_content)

                    with open(xml_temp_path, "w", encoding="utf-8") as f:
                        f.write(preprocessed_xml)

                    # Step 2: Convert DocBook5 XML to Markdown using pandoc with filter
                    pandoc_cmd = [
                        "pandoc",
                        "-f",
                        "docbook",
                        "--wrap=preserve",
                        "-t",
                        "markdown_strict",
                        f"--filter={self.PANDOC_FILTER_PATH}",
                        f"--lua-filter={self.PANDOC_LUA_FILTER_PATH}",
                        str(xml_temp_path.absolute()),
                        "-o",
                        str(output_path.absolute()),
                    ]
                    subprocess.run(
                        pandoc_cmd, check=True, capture_output=True, text=True
                    )

                    LOG.info(
                        "Successfully converted: %s -> %s", input_path, output_path
                    )

                except subprocess.CalledProcessError as e:
                    LOG.error("Failed to convert: %s -> %s", input_path, output_path)
                    LOG.error("Command: %s", " ".join(e.cmd))
                    LOG.error("Return code: %s", e.returncode)
                    if e.stdout:
                        LOG.error(
                            "stdout: %s",
                            e.stdout.decode()
                            if isinstance(e.stdout, bytes)
                            else e.stdout,
                        )
                    if e.stderr:
                        LOG.error(
                            "stderr: %s",
                            e.stderr.decode()
                            if isinstance(e.stderr, bytes)
                            else e.stderr,
                        )
                    # Save XML for debugging
                    if xml_temp_path.exists():
                        debug_xml_path = (
                            output_path.parent / f"{output_path.stem}_debug.xml"
                        )
                        debug_xml_path.parent.mkdir(parents=True, exist_ok=True)
                        LOG.error("Saving intermediate XML to: %s", debug_xml_path)
                        import shutil

                        shutil.copy(xml_temp_path, debug_xml_path)
                    raise

                except Exception as e:
                    LOG.error(
                        "Failed to convert: %s -> %s (%s)", input_path, output_path, e
                    )
                    raise

                finally:
                    # Clean up temporary files
                    if xml_temp_path.exists():
                        xml_temp_path.unlink()
                    if adoc_temp and Path(adoc_temp.name).exists():
                        Path(adoc_temp.name).unlink()
                    if preprocessed_temp and preprocessed_path.exists():
                        preprocessed_path.unlink()

        except Exception as e:
            LOG.error("Failed during preprocessing: %s (%s)", input_path, e)
            raise


if __name__ == "__main__":
    parser = get_argument_parser()
    args = parser.parse_args()

    failed_conversions = []
    successful_conversions = []

    if args.input_dir:
        docs_converter = DocsConverter(attributes_file=args.attributes_file)
        for input_path, output_path in red_hat_docs_path(
            args.input_dir,
            args.output_dir,
            args.docs_version,
            args.exclude_titles,
            args.remap_titles,
        ):
            try:
                docs_converter.convert(input_path, output_path)
                successful_conversions.append(str(input_path))
            except Exception as e:
                failed_conversions.append((str(input_path), str(e)))
                LOG.error("Continuing with next document after failure...")

    if args.relnotes_dir:
        relnotes_converter = RelNotesConverter(attributes_file=args.attributes_file)
        for input_path, output_path in red_hat_relnotes_path(
            args.relnotes_dir,
            args.output_dir,
            args.docs_version,
        ):
            try:
                relnotes_converter.convert(input_path, output_path)
                successful_conversions.append(str(input_path))
            except Exception as e:
                failed_conversions.append((str(input_path), str(e)))
                LOG.error("Continuing with next document after failure...")

    # Print summary
    LOG.info("\n" + "=" * 80)
    LOG.info("CONVERSION SUMMARY:")
    LOG.info(f"  Successful: {len(successful_conversions)}")
    LOG.info(f"  Failed: {len(failed_conversions)}")

    if failed_conversions:
        LOG.info("\nFailed conversions:")
        for path, error in failed_conversions:
            LOG.info(f"  - {path}")
            LOG.info(f"    Error: {error[:100]}...")  # First 100 chars of error

    LOG.info("=" * 80)
