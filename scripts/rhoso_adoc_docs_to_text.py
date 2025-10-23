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


def detect_block_language(block_lines: list[str]) -> str:
    """Detect the programming/markup language in a code block.

    AI: Method generated by Cursor

    Args:
        block_lines: Lines of code from the block

    Returns:
        Detected language string (yaml, bash, python, etc.)
    """
    # Join lines for analysis
    content = "\n".join(block_lines)

    # YAML indicators (most common in OpenStack docs)
    yaml_indicators = [
        r"^\s*\w+:\s*$",  # Key with no value (multiline)
        r"^\s*\w+:\s+\S+",  # Key: value pairs
        r"^\s*-\s+\w+:",  # List items with keys
        r"apiVersion:",  # Kubernetes/OpenStack CRD
        r"kind:",  # Kubernetes/OpenStack CRD
        r"metadata:",  # Common YAML structure
        r"spec:",  # Common YAML structure
    ]

    # Bash/shell indicators
    bash_indicators = [
        r"^\s*#\s*!/bin/(ba)?sh",  # Shebang
        r"^\s*\$\s+",  # Command prompt
        r"^\s*(sudo|export|source|echo|cd|ls|cat|grep)\s+",  # Common commands
        r"if\s+\[.*\];\s*then",  # Bash conditionals
    ]

    # INI/config file indicators
    ini_indicators = [
        r"^\s*\[[\w_-]+\]",  # Section headers like [DEFAULT]
        r"^\s*[\w_-]+\s*=\s*",  # Key = value pairs
    ]

    # Python indicators
    python_indicators = [
        r"^\s*import\s+",
        r"^\s*from\s+\w+\s+import",
        r"^\s*def\s+\w+\(",
        r"^\s*class\s+\w+",
    ]

    # XML indicators
    xml_indicators = [
        r"^\s*<\?xml",
        r"^\s*<[\w:-]+>.*</[\w:-]+>",
    ]

    # JSON indicators
    json_indicators = [
        r"^\s*[{\[]",  # Starts with { or [
        r'"\w+"\s*:\s*',  # JSON key-value
    ]

    # Count matches for each language
    scores = {
        "yaml": sum(
            1
            for pattern in yaml_indicators
            if re.search(pattern, content, re.MULTILINE)
        ),
        "bash": sum(
            1
            for pattern in bash_indicators
            if re.search(pattern, content, re.MULTILINE)
        ),
        "ini": sum(
            1 for pattern in ini_indicators if re.search(pattern, content, re.MULTILINE)
        ),
        "python": sum(
            1
            for pattern in python_indicators
            if re.search(pattern, content, re.MULTILINE)
        ),
        "xml": sum(
            1 for pattern in xml_indicators if re.search(pattern, content, re.MULTILINE)
        ),
        "json": sum(
            1
            for pattern in json_indicators
            if re.search(pattern, content, re.MULTILINE)
        ),
    }

    # Get language with highest score
    if max(scores.values()) > 0:
        detected = max(scores.items(), key=lambda x: x[1])[0]
        return detected

    # Default to yaml as it's most common in OpenStack docs
    return "yaml"


def preprocess_adoc_link_brackets(
    content: str, file_path: Path = None
) -> tuple[str, list[str]]:
    """Fix link text containing square brackets using pass macro.

    AI: Method generated by Cursor

    When link text contains square brackets like link:url[text[with]brackets],
    asciidoctor can misinterpret the brackets. This fixes it by wrapping the
    text portion with pass:[] macro: link:url[pass:[text[with]brackets]]

    Args:
        content: The raw AsciiDoc content as a string
        file_path: Path to the file being processed (for logging)

    Returns:
        Tuple of (fixed_content, list of fix descriptions)
    """
    lines = content.split("\n")
    new_lines = []
    fixes = []

    # Pattern to match links with square brackets in the text portion
    # link:url[text] where text contains [ or ]
    link_pattern = re.compile(r"(link:[^\[]+\[)([^\]]*[\[\]][^\]]*?)(\])")

    for i, line in enumerate(lines):
        new_line = line
        line_fixes = []

        for match in link_pattern.finditer(line):
            link_prefix = match.group(1)
            link_text = match.group(2)
            link_suffix = match.group(3)

            # Check if text contains brackets and is not already wrapped with pass:
            if ("[" in link_text or "]" in link_text) and not link_text.startswith(
                "pass:["
            ):
                # Wrap the text with pass:[]
                new_link = f"{link_prefix}pass:[{link_text}]{link_suffix}"
                new_line = new_line.replace(match.group(0), new_link, 1)
                line_fixes.append(
                    f"Line {i + 1}: wrapped link text '{link_text}' with pass:[]"
                )

        if line_fixes:
            fixes.extend(line_fixes)
            new_lines.append(new_line)
        else:
            new_lines.append(line)

    result = "\n".join(new_lines)
    return result, fixes


def preprocess_adoc_callout_numbering(
    content: str, file_path: Path = None
) -> tuple[str, list[str]]:
    """Renumber callouts to be sequential within each list item scope.

    AI: Method generated by Cursor

    AsciiDoctor expects callouts to be numbered sequentially within their scope.
    When callouts appear within list items (like procedure steps), they should
    restart at <1> for each list item. Otherwise, they're numbered globally.

    Args:
        content: The raw AsciiDoc content as a string
        file_path: Path to the file being processed (for logging)

    Returns:
        Tuple of (fixed_content, list of fix descriptions)
    """
    lines = content.split("\n")
    global_callout_number = 1
    renumber_map = {}  # Maps (block_index, local_number) -> global_number
    block_callouts = []  # List of (block_index, list_item_num, [local_numbers_in_order])
    block_index = 0
    in_block = False
    current_block_callouts = []
    current_list_item = 0

    # Pattern to detect list items (numbered or bulleted)
    list_item_pattern = re.compile(r"^(\.|\.{2,}|\*|\*{2,})\s+")

    # First pass: identify all callouts in blocks and build renumber map
    for i, line in enumerate(lines):
        # Check if this is a new list item (resets callout numbering)
        if list_item_pattern.match(line):
            current_list_item += 1
            global_callout_number = 1  # Reset numbering for new list item

        if line.strip() == "----":
            if not in_block:
                in_block = True
                current_block_callouts = []
                block_index += 1
            else:
                in_block = False
                if current_block_callouts:
                    block_callouts.append(
                        (block_index, current_list_item, list(current_block_callouts))
                    )
        elif in_block:
            # Find callouts in this line
            for match in re.finditer(r"<(\d+)>", line):
                local_num = int(match.group(1))
                if local_num not in current_block_callouts:
                    current_block_callouts.append(local_num)
                    renumber_map[(block_index, local_num)] = global_callout_number
                    global_callout_number += 1

    if not renumber_map:
        # No callouts to renumber
        return content, []

    # Second pass: apply renumbering to both block callouts and callout definitions
    new_lines = []
    in_block = False
    block_index = 0
    callout_definition_pattern = re.compile(r"^<(\d+)>\s+")
    # Track which block we're processing definitions for
    definition_block_queue = list(
        block_callouts
    )  # Queue of (block_index, list_item, [local_nums])
    current_definition_block = None
    current_definition_callouts = []
    definition_index = 0

    for i, line in enumerate(lines):
        if line.strip() == "----":
            if not in_block:
                in_block = True
                block_index += 1
            else:
                in_block = False
            new_lines.append(line)
        elif in_block:
            # Renumber callouts in code blocks
            new_line = line
            for match in reversed(list(re.finditer(r"<(\d+)>", line))):
                local_num = int(match.group(1))
                if (block_index, local_num) in renumber_map:
                    global_num = renumber_map[(block_index, local_num)]
                    new_line = (
                        new_line[: match.start()]
                        + f"<{global_num}>"
                        + new_line[match.end() :]
                    )
            new_lines.append(new_line)
        else:
            # Check if this is a callout definition line
            match = callout_definition_pattern.match(line)
            if match:
                local_num = int(match.group(1))

                # If we haven't set up the current definition block yet, or we've
                # processed all callouts for the current block, move to the next block
                if not current_definition_callouts and definition_block_queue:
                    current_definition_block, _, current_definition_callouts = (
                        definition_block_queue.pop(0)
                    )
                    definition_index = 0

                # Check if this callout matches the next expected callout for current block
                if (
                    current_definition_callouts
                    and definition_index < len(current_definition_callouts)
                    and local_num == current_definition_callouts[definition_index]
                ):
                    # Match! Renumber it
                    global_num = renumber_map[(current_definition_block, local_num)]
                    new_line = callout_definition_pattern.sub(f"<{global_num}> ", line)
                    new_lines.append(new_line)
                    definition_index += 1
                    # If we've processed all callouts for this block, clear it
                    if definition_index >= len(current_definition_callouts):
                        current_definition_callouts = []
                        current_definition_block = None
                        definition_index = 0
                else:
                    # Doesn't match expected pattern, keep original
                    new_lines.append(line)
            else:
                new_lines.append(line)

    total_callouts = len(renumber_map)
    fixes = []
    if total_callouts > 0:
        fixes.append(f"Renumbered {total_callouts} callout(s) with proper scoping")

    return "\n".join(new_lines), fixes


def preprocess_adoc_callouts(
    content: str, file_path: Path = None
) -> tuple[str, list[str]]:
    """Preprocess AsciiDoc to add source designation to blocks with callouts.

    AI: Method generated by Cursor

    Detects listing blocks (----) that contain callouts (<1>, <2>, etc.)
    but don't have a [source,...] designation, and adds one.

    Args:
        content: The raw AsciiDoc content as a string
        file_path: Path to the file being processed (for logging)

    Returns:
        Tuple of (fixed_content, list of fix descriptions)
    """
    lines = content.split("\n")
    new_lines = []
    i = 0
    fixes = []
    in_block = False

    while i < len(lines):
        line = lines[i]

        # Check if this is a block delimiter
        if line.strip() == "----":
            if not in_block:
                # This is an opening delimiter
                in_block = True

                # Look back to see if there's already a [source,...] designation
                # Check the previous non-empty line
                has_source_designation = False
                check_idx = len(new_lines) - 1
                while check_idx >= 0:
                    prev_line = new_lines[check_idx].strip()
                    if prev_line:
                        if prev_line.startswith("[source") or prev_line.startswith(
                            "[listing"
                        ):
                            has_source_designation = True
                        break
                    check_idx -= 1

                if not has_source_designation:
                    # Look ahead to see if block contains callouts
                    block_lines = []
                    j = i + 1
                    has_callouts = False
                    while j < len(lines) and lines[j].strip() != "----":
                        block_lines.append(lines[j])
                        # Check for callout pattern: <digit>
                        if re.search(r"<\d+>", lines[j]):
                            has_callouts = True
                        j += 1

                    if has_callouts:
                        # Detect the language of the block
                        language = detect_block_language(block_lines)
                        new_lines.append(f"[source,{language}]")
                        fixes.append(
                            f"Line {i + 1}: Added [source,{language}] for block with callouts"
                        )
            else:
                # This is a closing delimiter
                in_block = False

        new_lines.append(line)
        i += 1

    return "\n".join(new_lines), fixes


def preprocess_adoc_tables(
    content: str, file_path: Path = None
) -> tuple[str, list[str]]:
    """Preprocess AsciiDoc content to fix common table issues.

    AI: method generated by Cursor

    Args:
        content: The raw AsciiDoc content as a string
        file_path: Path to the file being processed (for logging)

    Returns:
        Tuple of (fixed_content, list of fix descriptions)
    """
    lines = content.split("\n")
    new_lines = []
    in_table = False
    table_start_idx = -1
    table_lines = []
    fixes = []

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
                    fixes.append(
                        f"Line {table_start_idx}: Added placeholder row to empty table"
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
        fixes.append(f"Line {table_start_idx}: Closed unclosed table")
        table_lines.append("|===")
        new_lines.extend(table_lines)

    return "\n".join(new_lines), fixes


def fix_adoc_file(file_path: Path) -> list[str]:
    """Apply all AsciiDoc fixes to a source file and report changes.

    AI: Method generated by Cursor

    This function reads an .adoc file, applies all preprocessing fixes,
    writes the changes back to the file if any fixes were made, and
    returns a list of descriptions of what was fixed.

    Args:
        file_path: Path to the .adoc file to fix

    Returns:
        List of fix descriptions (empty if no fixes were needed)
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            original_content = f.read()
    except Exception as e:
        LOG.error(f"Failed to read {file_path}: {e}")
        return []

    content = original_content
    all_fixes = []

    # Apply all preprocessing steps
    content, fixes = preprocess_adoc_link_brackets(content, file_path)
    all_fixes.extend(fixes)

    content, fixes = preprocess_adoc_callout_numbering(content, file_path)
    all_fixes.extend(fixes)

    content, fixes = preprocess_adoc_callouts(content, file_path)
    all_fixes.extend(fixes)

    content, fixes = preprocess_adoc_tables(content, file_path)
    all_fixes.extend(fixes)

    # Only write back if changes were made
    if content != original_content:
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            LOG.info(f"Fixed {file_path}: {len(all_fixes)} issue(s)")
        except Exception as e:
            LOG.error(f"Failed to write fixes to {file_path}: {e}")
            return []

    return all_fixes


def fix_adoc_files_in_directory(base_dir: Path) -> dict[Path, list[str]]:
    """Fix all .adoc files in a directory tree.

    AI: Method generated by Cursor

    Args:
        base_dir: Base directory to search for .adoc files

    Returns:
        Dictionary mapping file paths to lists of fix descriptions.
        Only includes files that had fixes applied.
    """
    fixes_by_file = {}

    for adoc_file in base_dir.rglob("*.adoc"):
        fixes = fix_adoc_file(adoc_file)
        if fixes:
            fixes_by_file[adoc_file] = fixes

    return fixes_by_file


def find_included_files(input_file: Path, base_dir: Path) -> set[Path]:
    """Recursively find all files included by an AsciiDoc file.

    AI: Method generated by Cursor

    Args:
        input_file: The main AsciiDoc file to analyze
        base_dir: The base directory for resolving relative includes

    Returns:
        Set of Path objects for all included files (recursively)
    """
    included_files = set()
    files_to_process = [input_file]
    processed_files = set()

    include_pattern = re.compile(r"^include::([^\[]+)\[")

    while files_to_process:
        current_file = files_to_process.pop()

        # Skip if already processed
        if current_file in processed_files:
            continue

        processed_files.add(current_file)

        # Read the file and find includes
        try:
            with open(current_file, "r", encoding="utf-8") as f:
                content = f.read()

            for line in content.split("\n"):
                match = include_pattern.match(line)
                if match:
                    include_path = match.group(1)

                    # Resolve the include path
                    # Try relative to base_dir first
                    resolved_path = base_dir / include_path
                    if not resolved_path.exists():
                        # Try relative to current file
                        resolved_path = current_file.parent / include_path

                    if resolved_path.exists():
                        included_files.add(resolved_path)
                        files_to_process.append(resolved_path)
        except Exception as e:
            LOG.warning(f"Failed to process includes in {current_file}: {e}")

    return included_files


def resolve_adoc_includes(content: str, base_dir: Path, current_file: Path) -> str:
    """Recursively resolve AsciiDoc include directives.

    AI: Method generated by Cursor

    Reads and inlines all include:: directives to create a single document
    that can be preprocessed as a whole.

    Args:
        content: The AsciiDoc content with include directives
        base_dir: The base directory for resolving includes
        current_file: The current file being processed (for relative paths)

    Returns:
        Content with all includes resolved inline
    """
    lines = content.split("\n")
    new_lines = []
    include_pattern = re.compile(r"^include::([^\[]+)\[(.*)\]")

    for line in lines:
        match = include_pattern.match(line)
        if match:
            include_path = match.group(1)

            # Resolve the include path
            # Try relative to base_dir first
            resolved_path = base_dir / include_path
            if not resolved_path.exists():
                # Try relative to current file
                resolved_path = current_file.parent / include_path

            if resolved_path.exists():
                try:
                    with open(resolved_path, "r", encoding="utf-8") as f:
                        included_content = f.read()

                    # Recursively resolve includes in the included file
                    included_content = resolve_adoc_includes(
                        included_content, base_dir, resolved_path
                    )

                    # Add a comment to track where this content came from
                    new_lines.append(f"// BEGIN INCLUDE: {include_path}")
                    new_lines.append(included_content)
                    new_lines.append(f"// END INCLUDE: {include_path}")
                except Exception as e:
                    LOG.warning(f"Failed to read include {include_path}: {e}")
                    new_lines.append(line)  # Keep original include directive
            else:
                LOG.warning(f"Include file not found: {include_path}")
                new_lines.append(line)  # Keep original include directive
        else:
            new_lines.append(line)

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

def preprocess_xml_list_titles(xml_content: str) -> str:
    """Preprocess XML to convert list titles to formalpara elements.

    AI: Method generated by Cursor

    Pandoc doesn't preserve <itemizedlist><title> or <orderedlist><title> elements
    when converting from DocBook. This function converts them to <formalpara><title>
    elements which pandoc does convert to Div.formalpara-title to preserve
    <itemizedlist><title> and <orderedlist><title> elements when converting from
    DocBook.

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

    def convert(self, input_path: Path, output_path: Path) -> dict[Path, list[str]]:
        """Convert release notes from AsciiDoc to Markdown.

        This method uses a multi-step conversion process:
        1. Fix all AsciiDoc source files in the base directory
        2. Convert AsciiDoc to DocBook5 XML using asciidoctor
        3. Convert DocBook5 XML to Markdown using pandoc with a custom filter

        We chose this process because it uses standard tools (even if they have
        bugs/limitations) and this process was recommended by our docs team.

        The source documentation is not 100% conformant with the AsciiDoc spec,
        this creates a problem with the process, and we chose to fix the source
        documents instead of creating temporary files and fix includes as well
        as it simplifies the code, speeds later runs, and allows for an easier
        diff to see what has changed.

        Args:
            input_path: Path to input .adoc file
            output_path: Path to output .txt (markdown) file

        Returns:
            Dictionary mapping file paths to lists of fix descriptions.
            Only includes files that had fixes applied.

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

        # Find base directory
        base_dir = find_adoc_base_dir(input_path)
        LOG.info(f"Detected base directory: {base_dir}")

        # Fix all .adoc files in the base directory
        LOG.info(f"Fixing .adoc files in {base_dir}...")
        fixes_by_file = fix_adoc_files_in_directory(base_dir)

        # Also fix all included files (even if outside base_dir)
        LOG.info("Finding and fixing included files...")
        included_files = find_included_files(input_path, base_dir)
        for included_file in included_files:
            # Skip files already fixed in base_dir
            if included_file not in fixes_by_file:
                fixes = fix_adoc_file(included_file)
                if fixes:
                    fixes_by_file[included_file] = fixes

        if fixes_by_file:
            LOG.info(f"Fixed {len(fixes_by_file)} file(s) with issues")
            for file_path, fixes in fixes_by_file.items():
                try:
                    rel_path = file_path.relative_to(base_dir)
                except ValueError:
                    # File is outside base_dir, show full path
                    rel_path = file_path
                LOG.info(f"  {rel_path}:")
                for fix in fixes:
                    LOG.info(f"    - {fix}")
        else:
            LOG.info("No fixes needed in source files")

        # Create temporary files for the conversion process
        adoc_temp = None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml") as xml_temp:
            try:
                xml_temp_path = Path(xml_temp.name)

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
            LOG.info(f"Detected base directory: {base_dir}")

            # Fix all included files (recursively)
            LOG.info("Finding and fixing included files...")
            included_files = find_included_files(input_path, base_dir)
            if included_files:
                LOG.info(f"Found {len(included_files)} included file(s), fixing...")
                for included_file in included_files:
                    fixes = fix_adoc_file(included_file)
                    if fixes:
                        LOG.info(f"  Fixed {included_file}: {len(fixes)} issue(s)")
                        for fix in fixes:
                            LOG.debug(f"    - {fix}")
            else:
                LOG.info("No included files found")

            # Read and preprocess the input file
            with open(input_path, "r", encoding="utf-8") as f:
                content = f.read()

            preprocessed_content, _ = preprocess_adoc_tables(content)

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
                        input_for_conversion = input_path

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

        except Exception as e:
            LOG.error("Failed during conversion: %s (%s)", input_path, e)
            raise

        return


if __name__ == "__main__":
    parser = get_argument_parser()
    args = parser.parse_args()

    failed_conversions = []
    successful_conversions = []
    all_fixes = {}  # Accumulate all fixes across all conversions

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
                fixes_by_file = docs_converter.convert(input_path, output_path) or {}
                successful_conversions.append(str(input_path))
                # Merge fixes into all_fixes
                for file_path, fixes in fixes_by_file.items():
                    if file_path not in all_fixes:
                        all_fixes[file_path] = fixes
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
                fixes_by_file = relnotes_converter.convert(input_path, output_path)
                successful_conversions.append(str(input_path))
                # Merge fixes into all_fixes
                for file_path, fixes in fixes_by_file.items():
                    if file_path not in all_fixes:
                        all_fixes[file_path] = fixes
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

    if all_fixes:
        LOG.info("\n" + "-" * 80)
        LOG.info("SOURCE FILE FIXES APPLIED:")
        LOG.info(f"  Total files fixed: {len(all_fixes)}")
        LOG.info("\nFiles with fixes:")
        for file_path in sorted(all_fixes.keys()):
            fixes = all_fixes[file_path]
            LOG.info(f"\n  {file_path}:")
            for fix in fixes:
                LOG.info(f"    - {fix}")

    LOG.info("\n" + "=" * 80)
