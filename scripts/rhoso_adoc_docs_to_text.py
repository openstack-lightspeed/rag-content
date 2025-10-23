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
import fcntl
import time

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
    # Directories to skip (backup/old content that shouldn't be processed)
    skip_dirs = {"gerrit-backup", "backup", "old", ".backup", "archive"}

    for file in input_dir.rglob("master.adoc"):
        # Skip files in backup/old directories
        if any(part in skip_dirs for part in file.parts):
            LOG.info(f"Skipping {file} (in backup/excluded directory)")
            continue

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
    """Renumber callouts to be sequential within each code block.

    AI: Method generated by Cursor

    AsciiDoc callouts should be scoped to individual code blocks. Each block
    should have callouts numbered starting from <1>, regardless of what numbers
    were used in the source.

    Args:
        content: The raw AsciiDoc content as a string
        file_path: Path to the file being processed (for logging)

    Returns:
        Tuple of (fixed_content, list of fix descriptions)
    """
    lines = content.split("\n")
    renumber_map = {}  # Maps (block_index, original_number) -> new_number
    block_callouts = []  # List of (block_index, [original_numbers_in_order])
    block_index = 0
    in_block = False
    current_block_callouts = []

    # First pass: identify all callouts in blocks and build renumber map
    for i, line in enumerate(lines):
        if line.strip() == "----":
            if not in_block:
                in_block = True
                current_block_callouts = []
                block_index += 1
            else:
                in_block = False
                if current_block_callouts:
                    # Renumber callouts for this block starting from 1
                    for new_num, original_num in enumerate(
                        current_block_callouts, start=1
                    ):
                        renumber_map[(block_index, original_num)] = new_num
                    block_callouts.append((block_index, list(current_block_callouts)))
        elif in_block:
            # Find callouts in this line (in order of appearance)
            for match in re.finditer(r"<(\d+)>", line):
                original_num = int(match.group(1))
                if original_num not in current_block_callouts:
                    current_block_callouts.append(original_num)

    if not renumber_map:
        # No callouts to renumber
        return content, []

    # Second pass: apply renumbering to both block callouts and callout definitions
    new_lines = []
    in_block = False
    block_index = 0
    callout_definition_pattern = re.compile(r"^<(\d+)>\s+")
    # Track which block's definitions we're expecting
    definition_block_queue = list(
        block_callouts
    )  # Queue of (block_index, [original_nums])
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
                original_num = int(match.group(1))
                if (block_index, original_num) in renumber_map:
                    new_num = renumber_map[(block_index, original_num)]
                    new_line = (
                        new_line[: match.start()]
                        + f"<{new_num}>"
                        + new_line[match.end() :]
                    )
            new_lines.append(new_line)
        else:
            # Check if this is a callout definition line
            match = callout_definition_pattern.match(line)
            if match:
                original_num = int(match.group(1))

                # If we haven't set up the current definition block yet, or we've
                # processed all callouts for the current block, move to the next block
                if not current_definition_callouts and definition_block_queue:
                    current_definition_block, current_definition_callouts = (
                        definition_block_queue.pop(0)
                    )
                    definition_index = 0

                # Check if this callout matches the next expected callout for current block
                if (
                    current_definition_callouts
                    and definition_index < len(current_definition_callouts)
                    and original_num == current_definition_callouts[definition_index]
                ):
                    # Match! Renumber it
                    new_num = renumber_map[(current_definition_block, original_num)]
                    new_line = callout_definition_pattern.sub(f"<{new_num}> ", line)
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

    # Check if content actually changed
    new_content = "\n".join(new_lines)
    fixes = []
    if new_content != content:
        total_callouts = len(renumber_map)
        fixes.append(f"Renumbered {total_callouts} callout(s) with block-level scoping")

    return new_content, fixes


def preprocess_adoc_callout_placement(
    content: str, file_path: Path = None
) -> tuple[str, list[str]]:
    """Move callout definitions to immediately after their code blocks.

    AI: Method generated by Cursor

    Callout definitions should appear right after the code block they reference,
    not bundled at the end. This function reorganizes them properly and splits
    bundled definitions.

    Args:
        content: The raw AsciiDoc content as a string
        file_path: Path to the file being processed (for logging)

    Returns:
        Tuple of (fixed_content, list of fix descriptions)
    """
    lines = content.split("\n")
    fixes = []

    # First pass: identify blocks with callouts
    block_info = []  # List of (block_start, block_end, max_callout_num)
    in_block = False
    block_start = -1
    block_callouts = []

    for i, line in enumerate(lines):
        if line.strip() == "----":
            if not in_block:
                in_block = True
                block_start = i
                block_callouts = []
            else:
                in_block = False
                if block_callouts:
                    max_callout = max(block_callouts)
                    block_info.append((block_start, i, max_callout))
        elif in_block:
            # Find callouts in this line
            for match in re.finditer(r"<(\d+)>", line):
                block_callouts.append(int(match.group(1)))

    if not block_info:
        return content, []

    # Second pass: collect all callout definition lines (tracking individual definitions)
    callout_definition_pattern = re.compile(r"^<(\d+)>\s+")
    all_definitions = []  # List of (line_idx, callout_num, line_content)

    for i, line in enumerate(lines):
        match = callout_definition_pattern.match(line)
        if match:
            callout_num = int(match.group(1))
            all_definitions.append((i, callout_num, line))

    if not all_definitions:
        return content, []

    # Third pass: Match definitions to blocks in order
    # Each block gets the next N definitions (where N is the number of callouts in that block)
    lines_to_skip = set()
    insertions = {}  # Maps block_end_line to list of (lines, context_lines) to insert
    definition_idx = 0

    for block_start, block_end, max_callout in block_info:
        # This block needs definitions for callouts <1> through <max_callout>
        num_defs_needed = max_callout

        # Check if definitions are already right after this block
        defs_after_block = []
        check_idx = block_end + 1
        while check_idx < len(lines) and len(defs_after_block) < num_defs_needed:
            # Skip empty lines and ifeval/endif lines
            line = lines[check_idx]
            if callout_definition_pattern.match(line):
                def_num = int(callout_definition_pattern.match(line).group(1))
                defs_after_block.append(def_num)
            elif line.strip() and not line.strip().startswith(("ifeval::", "endif::")):
                # Hit a non-definition, non-wrapper line
                break
            check_idx += 1

        # Check if we have the right definitions already in place
        expected_defs = list(range(1, max_callout + 1))
        if defs_after_block == expected_defs:
            # Definitions are already in the right place
            definition_idx += num_defs_needed
            continue

        # Collect the N definition lines for this block
        block_def_lines = []

        if definition_idx < len(all_definitions):
            # Check if these definitions are wrapped in an ifeval block
            first_def_idx = all_definitions[definition_idx][0]

            # Look for ifeval wrapper before the first definition
            has_ifeval_wrapper = False
            ifeval_line = None
            for j in range(first_def_idx - 1, max(0, first_def_idx - 3), -1):
                if lines[j].strip().startswith("ifeval::"):
                    has_ifeval_wrapper = True
                    ifeval_line = lines[j]
                    break
                elif lines[j].strip():  # Hit a non-empty, non-ifeval line
                    break

            # Collect just the definition lines we need (not the entire context)
            for i in range(num_defs_needed):
                if definition_idx + i < len(all_definitions):
                    def_line_idx, def_num, def_line = all_definitions[
                        definition_idx + i
                    ]
                    block_def_lines.append(def_line)
                    lines_to_skip.add(def_line_idx)

            # If there was an ifeval wrapper, wrap these definitions
            if has_ifeval_wrapper and ifeval_line:
                block_def_lines = [ifeval_line] + block_def_lines + ["endif::[]"]
                # Mark the original ifeval/endif for removal if all definitions are being moved
                # (We'll handle this by marking individual definition lines only)

            # Schedule insertion after the block
            if block_end not in insertions:
                insertions[block_end] = []
            insertions[block_end].extend(block_def_lines)
            insertions[block_end].append("")  # Add blank line after definitions

            fixes.append(
                f"Moved {num_defs_needed} callout definition(s) to after block at line {block_end + 1}"
            )
            definition_idx += num_defs_needed

    # Also remove any ifeval/endif wrappers that only contained definitions we moved
    # Scan for ifevals that now have no content between them
    i = 0
    while i < len(lines):
        if i not in lines_to_skip and lines[i].strip().startswith("ifeval::"):
            # Check if the next non-skipped, non-empty line is an endif
            j = i + 1
            while j < len(lines):
                if j not in lines_to_skip:
                    if lines[j].strip().startswith("endif::"):
                        # Empty ifeval block, mark both for removal
                        lines_to_skip.add(i)
                        lines_to_skip.add(j)
                        break
                    elif lines[j].strip():
                        # Found content, keep the ifeval
                        break
                j += 1
        i += 1

    if not lines_to_skip and not insertions:
        return content, []

    # Build the new content
    new_lines = []
    for i, line in enumerate(lines):
        if i not in lines_to_skip:
            new_lines.append(line)
            # Insert definitions after this line if needed
            if i in insertions:
                new_lines.extend(insertions[i])

    return "\n".join(new_lines), fixes


def preprocess_adoc_callout_spacing(
    content: str, file_path: Path = None
) -> tuple[str, list[str]]:
    """Ensure blank lines after callout definition sections.

    AI: Method generated by Cursor

    Callout definitions should always be followed by a blank line for proper
    AsciiDoc formatting and to avoid confusing the parser.

    Args:
        content: The raw AsciiDoc content as a string
        file_path: Path to the file being processed (for logging)

    Returns:
        Tuple of (fixed_content, list of fix descriptions)
    """
    lines = content.split("\n")
    fixes = []
    callout_definition_pattern = re.compile(r"^<(\d+)>\s+")

    # Find the end of each callout definition section and ensure blank line after
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        new_lines.append(line)

        # Check if this is a callout definition
        if callout_definition_pattern.match(line):
            # Found a callout definition, look for the end of this section
            j = i + 1
            last_def_line = i

            # Scan forward to find all consecutive callout definitions
            # (may be wrapped in ifeval/endif blocks)
            while j < len(lines):
                current_line = lines[j]

                if callout_definition_pattern.match(current_line):
                    # Another definition, update the last position
                    last_def_line = j
                    j += 1
                elif current_line.strip().startswith("endif::"):
                    # Could be the end of an ifeval wrapper
                    last_def_line = j
                    j += 1
                    # Check if next line is another definition or ifeval
                    if j < len(lines):
                        next_line = lines[j]
                        if callout_definition_pattern.match(
                            next_line
                        ) or next_line.strip().startswith("ifeval::"):
                            continue
                        else:
                            break
                    else:
                        break
                elif current_line.strip().startswith("ifeval::"):
                    # Continuation of wrapped definitions
                    j += 1
                elif current_line.strip() == "":
                    # Empty line, we're good
                    break
                else:
                    # Hit a non-definition, non-wrapper line
                    last_def_line = j - 1
                    break

            # Now append all lines from i+1 to last_def_line
            for k in range(i + 1, last_def_line + 1):
                new_lines.append(lines[k])

            # Check if there's already a blank line after the definitions
            next_idx = last_def_line + 1
            if next_idx < len(lines):
                if lines[next_idx].strip() != "":
                    # No blank line, add one
                    new_lines.append("")
                    fixes.append(
                        f"Line {last_def_line + 1}: Added blank line after callout definitions"
                    )

            i = last_def_line + 1
        else:
            i += 1

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
                has_subs_only = False
                subs_value = None
                check_idx = len(new_lines) - 1
                prev_line_idx = -1
                while check_idx >= 0:
                    prev_line = new_lines[check_idx].strip()
                    if prev_line:
                        if prev_line.startswith("[source") or prev_line.startswith(
                            "[listing"
                        ):
                            has_source_designation = True
                        elif prev_line.startswith("[subs="):
                            # Extract the subs value
                            match = re.match(r"\[subs=([^\]]+)\]", prev_line)
                            if match:
                                subs_value = match.group(1)
                                has_subs_only = True
                                prev_line_idx = check_idx
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
                        if has_subs_only and subs_value:
                            # Replace the existing [subs=...] line with [source,language,subs=...]
                            new_lines[prev_line_idx] = (
                                f"[source,{language},subs={subs_value}]"
                            )
                            fixes.append(
                                f"Line {i + 1}: Added source designation to [subs={subs_value}] for block with callouts"
                            )
                        else:
                            # Add new [source,language] line
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


class Cell:
    """Represents a single table cell with its properties.

    AI: Class generated by Cursor
    """

    def __init__(
        self,
        content: str,
        colspan: int = 1,
        rowspan: int = 1,
        format_spec: str = "",
        source_line: int = 0,
    ):
        self.content = content
        self.colspan = colspan
        self.rowspan = rowspan
        self.format_spec = format_spec
        self.source_line = source_line

    def __repr__(self):
        span_info = ""
        if self.colspan > 1 or self.rowspan > 1:
            span_info = f" ({self.colspan}x{self.rowspan})"
        return f"Cell({self.content[:20]}...{span_info})"


class SpanPlaceholder:
    """Placeholder for positions occupied by spanning cells.

    AI: Class generated by Cursor
    """

    def __init__(self, original_cell: Cell):
        self.original_cell = original_cell

    def __repr__(self):
        return f"Span({self.original_cell.content[:10]}...)"


class AsciiDocTableParser:
    """Parse AsciiDoc tables into a logical grid structure and reconstruct them correctly.

    AI: Class generated by Cursor
    """

    def __init__(self, expected_cols: int):
        self.expected_cols = expected_cols
        self.grid = []
        self.fixes_made = []

    def parse_and_fix_table(
        self, table_lines: list[str]
    ) -> tuple[list[str], list[str]]:
        """
        Parse table into logical grid and reconstruct with fixes.

        Returns:
            Tuple of (fixed_table_lines, list_of_fixes)
        """
        try:
            cells = self.extract_cells_from_lines(table_lines)
            if not cells:
                return table_lines, []

            self.build_grid(cells)
            self.validate_and_fix_grid()
            fixed_lines = self.reconstruct_table()

            return fixed_lines, self.fixes_made
        except Exception as e:
            LOG.debug(f"AST table parser failed: {e}")
            return table_lines, []

    def extract_cells_from_lines(self, table_lines: list[str]) -> list[Cell]:
        """Extract all cells from table lines, parsing span specifications."""
        cells = []

        for line_no, line in enumerate(table_lines):
            stripped = line.strip()
            if not stripped or stripped == "|===" or stripped == "|====":
                continue

            # Use regex to find all cell boundaries
            # A cell can start with:
            # 1. | followed by optional span spec (|N.M+| or |N+|) and content
            # 2. Embedded span spec like " N+|" or " N.M+|" after previous cell content

            # Split by all cell boundary patterns
            # Pattern: | OR (whitespace)(N+|) OR (whitespace)(N.M+|)
            cell_boundary_pattern = r"(\s*\d+(?:\.\d+)?\+\||(?<!\d)\|)"

            # Find all boundaries
            boundaries = []
            for match in re.finditer(cell_boundary_pattern, stripped):
                boundaries.append(match.start())

            # Add end of string as final boundary
            boundaries.append(len(stripped))

            # Extract cells between boundaries
            for idx in range(len(boundaries) - 1):
                start = boundaries[idx]
                end = boundaries[idx + 1]
                cell_text = stripped[start:end]

                # Parse the cell
                colspan = 1
                rowspan = 1
                format_spec = ""
                content = ""

                # Remove leading/trailing whitespace and get the core cell text
                cell_text = cell_text.strip()
                if not cell_text:
                    continue

                # Skip the leading |
                if cell_text.startswith("|"):
                    cell_text = cell_text[1:]

                # Check for colspan.rowspan+ pattern
                span_match = re.match(r"(\d+)\.(\d+)\+\|?", cell_text)
                if span_match:
                    colspan = int(span_match.group(1))
                    rowspan = int(span_match.group(2))
                    cell_text = cell_text[span_match.end() :]
                else:
                    # Check for colspan+ pattern
                    colspan_match = re.match(r"(\d+)\+\|?", cell_text)
                    if colspan_match:
                        colspan = int(colspan_match.group(1))
                        cell_text = cell_text[colspan_match.end() :]

                # Check for format specifier
                format_match = re.match(r"([a-z])\|", cell_text)
                if format_match:
                    format_spec = format_match.group(1)
                    cell_text = cell_text[format_match.end() :]

                # Remaining text is content
                content = cell_text.strip()

                # Skip empty cells that come from leading | (cell_text was just "|")
                if not content and colspan == 1 and rowspan == 1 and not format_spec:
                    continue

                cells.append(
                    Cell(
                        content=content,
                        colspan=colspan,
                        rowspan=rowspan,
                        format_spec=format_spec,
                        source_line=line_no,
                    )
                )

        return cells

    def build_grid(self, cells: list[Cell]):
        """Build 2D grid from cells, accounting for spans."""
        # Preallocate grid (estimate max rows)
        max_rows = len(cells) + 10
        self.grid = [[None] * self.expected_cols for _ in range(max_rows)]

        row, col = 0, 0

        for cell in cells:
            # Find next available position in grid
            while row < len(self.grid):
                while col < self.expected_cols and self.grid[row][col] is not None:
                    col += 1

                if col < self.expected_cols:
                    break

                # Move to next row
                row += 1
                col = 0

            if row >= len(self.grid):
                break

            # Place cell and mark spanned positions
            for r in range(row, min(row + cell.rowspan, len(self.grid))):
                for c in range(col, min(col + cell.colspan, self.expected_cols)):
                    if r == row and c == col:
                        self.grid[r][c] = cell
                    else:
                        self.grid[r][c] = SpanPlaceholder(cell)

            # Move to next column position
            col += cell.colspan
            if col >= self.expected_cols:
                row += 1
                col = 0

        # Trim empty rows from end
        while self.grid and all(cell is None for cell in self.grid[-1]):
            self.grid.pop()

    def validate_and_fix_grid(self):
        """Validate each row has correct number of columns and fix issues."""
        for row_idx, row in enumerate(self.grid):
            # Check for None values (gaps in the grid)
            for col_idx, cell in enumerate(row):
                if cell is None:
                    # Add empty cell
                    row[col_idx] = Cell(content="", colspan=1, rowspan=1)
                    self.fixes_made.append(
                        f"Row {row_idx + 1}: Added empty cell at column {col_idx + 1}"
                    )

    def reconstruct_table(self) -> list[str]:
        """Reconstruct valid AsciiDoc table lines from grid."""
        lines = ["|==="]

        for row_idx, row in enumerate(self.grid):
            line_parts = []

            for col_idx, cell in enumerate(row):
                if isinstance(cell, SpanPlaceholder):
                    # Skip positions occupied by spans
                    continue

                if cell is None:
                    # Shouldn't happen after validation, but handle it
                    line_parts.append("|")
                else:
                    # Build cell specification
                    cell_spec = "|"

                    # Add span specifications
                    if cell.colspan > 1 and cell.rowspan > 1:
                        cell_spec += f"{cell.colspan}.{cell.rowspan}+"
                    elif cell.colspan > 1:
                        cell_spec += f"{cell.colspan}+"
                    elif cell.rowspan > 1:
                        cell_spec += f"1.{cell.rowspan}+"

                    # Add second pipe after span spec (if there's content or format spec coming)
                    if cell.colspan > 1 or cell.rowspan > 1:
                        cell_spec += "|"

                    # Add format specifier (it goes between pipes)
                    if cell.format_spec:
                        cell_spec += f"{cell.format_spec}|"

                    # Add content (may be empty)
                    if cell.content:
                        cell_spec += cell.content
                    elif not cell.format_spec:
                        # Empty cell with no format spec, just add a space
                        cell_spec += " "

                    line_parts.append(cell_spec)

            # Build line from parts
            if line_parts:
                line = " ".join(line_parts)
                # Don't add trailing | - it creates extra empty cells
                # AsciiDoc tables don't require trailing |
                lines.append(line)

        lines.append("|===")
        return lines


def merge_split_table_rows(
    table_lines: list[str], expected_cols: int, table_start_idx: int, fixes: list[str]
) -> list[str]:
    """Merge rows that are incorrectly split across multiple lines.

    AI: Method generated by Cursor

    In multi-column tables, if consecutive lines each have only 1 cell,
    they likely represent a single row that was incorrectly split.

    Args:
        table_lines: Table lines to process
        expected_cols: Expected number of columns in the table
        table_start_idx: Starting line index for fix reporting
        fixes: List to append fix descriptions to

    Returns:
        Table lines with split rows merged
    """

    def count_cells_simple(line: str) -> int:
        """Quick cell count for merge detection."""
        if not line.strip() or "|" not in line:
            return 0
        # Count | characters and subtract 1 for leading |
        return line.count("|") - (1 if line.strip().startswith("|") else 0)

    merged_lines = [table_lines[0]]  # Keep opening |===
    i = 1

    while i < len(table_lines) - 1:
        line = table_lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            merged_lines.append(line)
            i += 1
            continue

        # Count cells in this line
        cells_in_line = count_cells_simple(line)

        # If this line has only 1 cell and we expect multiple columns,
        # check if the IMMEDIATELY FOLLOWING line also has 1 cell (they form a 2-cell row)
        # But don't merge more than 2 consecutive single-cell lines to avoid over-merging
        if cells_in_line == 1 and expected_cols == 2 and stripped.startswith("|"):
            # Check if next non-empty line also has exactly 1 cell
            j = i + 1
            while j < len(table_lines) - 1 and not table_lines[j].strip():
                j += 1

            if j < len(table_lines) - 1:
                next_line = table_lines[j]
                next_stripped = next_line.strip()
                next_cells = count_cells_simple(next_line)

                # Merge only if next line also has exactly 1 cell and starts with |
                if next_cells == 1 and next_stripped.startswith("|"):
                    # Merge these two lines
                    merged_line = line.rstrip() + " " + next_line.strip()
                    merged_lines.append(merged_line)
                    fixes.append(
                        f"Line {table_start_idx + i + 1}: Merged 2 split lines into single table row"
                    )

                    # Skip the merged line and any empty lines we passed
                    i = j + 1
                    continue

        # Default: keep line as is
        merged_lines.append(line)
        i += 1

    merged_lines.append(table_lines[-1])  # Keep closing |===

    return merged_lines


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

                # Remove standalone "|" or empty lines that appear right before the closing |===
                # These create incomplete rows. But preserve standalone "|" after the opening |===
                # as those are valid row delimiters in AsciiDoc.
                while len(table_lines) > 2:  # Need at least opening |===, closing |===
                    # Check lines before the closing |===
                    prev_line = table_lines[-2].strip()
                    # Only remove if it's a standalone "|" or empty line right before table close
                    # AND it's not the first line after table open (which would be index 1)
                    if (prev_line == "|" or prev_line == "") and len(table_lines) > 3:
                        # Remove this problematic line
                        removed_line = table_lines.pop(-2)
                        if removed_line.strip():  # Only log if it was non-empty
                            fixes.append(
                                f"Line {table_start_idx + len(table_lines)}: Removed incomplete table row: '{removed_line.strip()}'"
                            )
                    else:
                        break

                # Fix cells that start a new row after a blank line but don't have a leading |
                # This can confuse the table parser. However, we need to be careful to only
                # add | to the first line of a row, not to continuation lines within a cell.
                # A line is a row start if:
                # 1. Previous line is blank
                # 2. The line before the blank ended with | (indicating end of a cell/row)
                # 3. The current line doesn't start with |
                for j in range(
                    2, len(table_lines) - 1
                ):  # Skip opening |=== and first line
                    if (
                        table_lines[j - 1].strip() == ""  # Previous line is blank
                        and table_lines[j].strip()  # Current line has content
                        and not table_lines[j].strip().startswith("|")
                    ):  # Doesn't start with |
                        # Check if the line before the blank ended with | (end of previous row)
                        if j >= 2 and table_lines[j - 2].rstrip().endswith("|"):
                            # This is likely a new row starting
                            table_lines[j] = "|" + table_lines[j]
                            fixes.append(
                                f"Line {table_start_idx + j + 1}: Added leading '|' to row start"
                            )

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

    # Join lines and ensure file ends with newline if it contained tables
    result = "\n".join(new_lines)

    # Ensure the content ends with a newline
    if result and not result.endswith("\n"):
        result += "\n"

    return result, fixes


class FileLock:
    """Context manager for file locking to prevent concurrent modifications.

    AI: Class generated by Cursor

    Uses fcntl-based advisory locks on Linux systems. Creates a .lock file
    next to the target file for locking purposes.
    """

    def __init__(
        self, file_path: Path, timeout: int = 300, check_interval: float = 0.1
    ):
        """Initialize the file lock.

        Args:
            file_path: Path to the file to lock
            timeout: Maximum time in seconds to wait for lock (default: 300s = 5 min)
            check_interval: Time in seconds between lock acquisition attempts (default: 0.1s)
        """
        self.file_path = file_path
        self.lock_path = file_path.parent / f".{file_path.name}.lock"
        self.timeout = timeout
        self.check_interval = check_interval
        self.lock_file = None

    def __enter__(self):
        """Acquire the file lock."""
        start_time = time.time()
        while True:
            try:
                # Open lock file (create if it doesn't exist)
                self.lock_file = open(self.lock_path, "w")
                # Try to acquire exclusive lock (non-blocking)
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Successfully acquired lock
                LOG.debug(f"Acquired lock for {self.file_path}")
                return self
            except (IOError, OSError):
                # Lock is held by another process
                if time.time() - start_time > self.timeout:
                    if self.lock_file:
                        self.lock_file.close()
                    raise TimeoutError(
                        f"Could not acquire lock for {self.file_path} after {self.timeout}s"
                    )
                # Wait and retry
                time.sleep(self.check_interval)

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release the file lock."""
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
                LOG.debug(f"Released lock for {self.file_path}")
                # Try to remove the lock file (best effort)
                try:
                    self.lock_path.unlink()
                except Exception:
                    pass
            except Exception as e:
                LOG.warning(f"Error releasing lock for {self.file_path}: {e}")


def fix_adoc_file(file_path: Path) -> list[str]:
    """Apply all AsciiDoc fixes to a source file and report changes.

    AI: Method generated by Cursor

    This function reads an .adoc file, applies all preprocessing fixes,
    writes the changes back to the file if any fixes were made, and
    returns a list of descriptions of what was fixed.

    Uses file locking to prevent concurrent modifications when multiple
    workers are processing files in parallel.

    Args:
        file_path: Path to the .adoc file to fix

    Returns:
        List of fix descriptions (empty if no fixes were needed)
    """
    # Acquire exclusive lock before processing the file
    with FileLock(file_path):
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

        content, fixes = preprocess_adoc_callout_placement(content, file_path)
        all_fixes.extend(fixes)

        content, fixes = preprocess_adoc_callouts(content, file_path)
        all_fixes.extend(fixes)

        content, fixes = preprocess_adoc_callout_spacing(content, file_path)
        all_fixes.extend(fixes)

        content, fixes = preprocess_adoc_tables(content, file_path)
        all_fixes.extend(fixes)

        # Only write back if changes were made
        if content != original_content:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
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


def preprocess_xml_escape_angle_brackets(xml_content: str) -> str:
    """Escape unescaped angle brackets in XML content that aren't valid XML tags.

    AI: Method generated by Cursor

    This fixes cases where asciidoctor generates XML with literal angle brackets
    in text content (e.g., from pass:[] macros with backticks containing <key=value>).

    Args:
        xml_content: The DocBook XML content as a string

    Returns:
        XML content with angle brackets properly escaped
    """
    fixes_applied = 0

    # Pattern to match placeholder-style angle brackets like <key=value> or <instance>
    # These appear in code examples and should be escaped
    # We specifically look for patterns that:
    # 1. Have = without proper attribute syntax (no space before =, or no quotes)
    # 2. Are simple words that look like placeholders

    def escape_invalid_tags(match):
        nonlocal fixes_applied
        tag_content = match.group(1)

        # Check if this looks like a placeholder rather than a real XML tag
        # Indicators of placeholders:
        # - Contains = with no space before it and no proper attribute syntax
        # - Pattern: word=word (like key=value)
        if re.match(r"^[a-zA-Z_][\w-]*=[^\s>]+$", tag_content):
            # This looks like <key=value> style placeholder
            fixes_applied += 1
            return f"&lt;{tag_content}&gt;"

        return match.group(0)

    # Find angle bracket pairs and check if they're placeholders
    # This pattern finds <...> but excludes:
    # - XML declarations <?...?>
    # - Closing tags </...>
    # - Self-closing tags <.../>
    # - Processing instructions
    result = re.sub(
        r"<([a-zA-Z_][\w-]*(?:=[\w-]+)?(?:\[[\w=\s\[\]<>-]*\])?)>",
        escape_invalid_tags,
        xml_content,
    )

    if fixes_applied > 0:
        LOG.info(f"Escaped {fixes_applied} invalid XML angle bracket(s)")

    return result


def preprocess_xml_undefined_entities(xml_content: str) -> str:
    """Replace undefined XML entities with their proper representations.

    AI: Method generated by Cursor

    AsciiDoc may generate entities like &verbar; which are not standard XML entities.
    This function replaces them with their numeric entity equivalents or the actual character.

    Args:
        xml_content: The DocBook XML content as a string

    Returns:
        XML content with undefined entities replaced
    """
    # Map of undefined entities to their replacements
    # Using numeric entities or actual characters that are XML-safe
    entity_replacements = {
        "&verbar;": "&#124;",  # Vertical bar |
        "&vert;": "&#124;",  # Alternative vertical bar
        "&lsqb;": "&#91;",  # Left square bracket [
        "&rsqb;": "&#93;",  # Right square bracket ]
        "&lcub;": "&#123;",  # Left curly brace {
        "&rcub;": "&#125;",  # Right curly brace }
        "&sol;": "&#47;",  # Solidus /
        "&bsol;": "&#92;",  # Reverse solidus \
        "&comma;": "&#44;",  # Comma ,
        "&period;": "&#46;",  # Period .
        "&colon;": "&#58;",  # Colon :
        "&semi;": "&#59;",  # Semicolon ;
        "&equals;": "&#61;",  # Equals sign =
        "&plus;": "&#43;",  # Plus sign +
        "&ast;": "&#42;",  # Asterisk *
        "&num;": "&#35;",  # Number sign #
        "&percnt;": "&#37;",  # Percent sign %
        "&dollar;": "&#36;",  # Dollar sign $
        "&commat;": "&#64;",  # Commercial at @
        "&excl;": "&#33;",  # Exclamation mark !
        "&quest;": "&#63;",  # Question mark ?
        "&grave;": "&#96;",  # Grave accent `
        "&Hat;": "&#94;",  # Circumflex accent ^
        "&tilde;": "&#126;",  # Tilde ~
    }

    # Replace each undefined entity
    for entity, replacement in entity_replacements.items():
        if entity in xml_content:
            xml_content = xml_content.replace(entity, replacement)
            LOG.debug(f"Replaced {entity} with {replacement}")

    # Fix incomplete HTML/XML entities that are missing the closing semicolon
    # This handles cases where &lt, &gt, &amp, &quot, &apos appear without semicolons
    # But we need to be careful not to break valid text
    # Pattern: Find &lt, &gt, &amp, &quot, &apos followed by non-alphanumeric (but not semicolon)

    # Fix common incomplete entities: &lt &gt &amp &quot &apos
    # Only fix if followed by a space, <, >, or end of attribute/tag
    def fix_incomplete_entity(match):
        entity = match.group(1)
        following = match.group(2)
        # Add the semicolon
        return f"&{entity};{following}"

    # Match &(lt|gt|amp|quot|apos) followed by something that's not a semicolon or letter
    # This ensures we don't break &ltfoo; into &lt;foo;
    pattern = r'&(lt|gt|amp|quot|apos)(?!;|[a-zA-Z])(\s|<|>|"|\||$)'
    xml_content = re.sub(pattern, fix_incomplete_entity, xml_content)

    return xml_content


def convert_html_tables_to_markdown(markdown_content: str) -> str:
    """Convert HTML tables in markdown to pipe tables.

    AI: Method generated by Cursor

    Pandoc sometimes outputs HTML tables for very large or complex tables.
    This function converts those HTML tables to markdown pipe tables.

    Args:
        markdown_content: Markdown content that may contain HTML tables

    Returns:
        Markdown content with HTML tables converted to pipe tables
    """
    from html.parser import HTMLParser

    class TableParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_table = False
            self.in_thead = False
            self.in_tbody = False
            self.in_row = False
            self.in_cell = False
            self.current_cell = []
            self.current_row = []
            self.headers = []
            self.rows = []
            self.table_start = -1
            self.table_end = -1

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self.in_table = True
                self.headers = []
                self.rows = []
            elif tag == "thead":
                self.in_thead = True
            elif tag == "tbody":
                self.in_tbody = True
            elif tag == "tr":
                self.in_row = True
                self.current_row = []
            elif tag in ("th", "td"):
                self.in_cell = True
                self.current_cell = []

        def handle_endtag(self, tag):
            if tag == "table":
                self.in_table = False
            elif tag == "thead":
                self.in_thead = False
            elif tag == "tbody":
                self.in_tbody = False
            elif tag == "tr":
                self.in_row = False
                if self.in_thead:
                    self.headers.append(self.current_row[:])
                elif self.in_tbody:
                    self.rows.append(self.current_row[:])
                self.current_row = []
            elif tag in ("th", "td"):
                self.in_cell = False
                cell_text = " ".join(self.current_cell).strip()
                self.current_row.append(cell_text)
                self.current_cell = []

        def handle_data(self, data):
            if self.in_cell:
                self.current_cell.append(data.strip())

    # Find all HTML tables
    table_pattern = re.compile(r"<table>.*?</table>", re.DOTALL | re.IGNORECASE)

    def replace_table(match):
        html_table = match.group(0)
        parser = TableParser()
        try:
            parser.feed(html_table)

            if not parser.headers and not parser.rows:
                return html_table  # Could not parse, keep original

            # Build markdown table
            md_lines = []

            # Headers
            if parser.headers:
                for header_row in parser.headers:
                    md_lines.append("| " + " | ".join(header_row) + " |")
                    # Separator row
                    md_lines.append("|" + "|".join(["---" for _ in header_row]) + "|")

            # Body rows
            for row in parser.rows:
                md_lines.append("| " + " | ".join(row) + " |")

            return "\n".join(md_lines)
        except Exception as e:
            LOG.warning(f"Failed to convert HTML table to markdown: {e}")
            return html_table  # Keep original on error

    result = table_pattern.sub(replace_table, markdown_content)
    return result


def preprocess_xml_table_cells(xml_content: str) -> str:
    """Flatten table cell content to inline elements for pipe table compatibility.

    AI: Method generated by Cursor

    Pandoc can only convert tables to pipe tables if cells contain inline content,
    not block-level elements like <simpara>. This function flattens table cells
    by unwrapping ONLY the direct simpara/para child of entry elements, while
    preserving any nested simpara/para tags inside lists or other structures.

    Args:
        xml_content: The DocBook XML content as a string

    Returns:
        Preprocessed XML with flattened table cells
    """
    try:
        # Parse the XML
        root = ET.fromstring(xml_content)

        # Define the DocBook namespace
        ns = {"db": "http://docbook.org/ns/docbook"}

        # Find all entry elements
        for entry in root.findall(f".//{{{ns['db']}}}entry"):
            # Check if the entry has exactly one child and it's a simpara or para
            children = list(entry)
            if len(children) == 1 and children[0].tag in (
                f"{{{ns['db']}}}simpara",
                f"{{{ns['db']}}}para",
            ):
                para_elem = children[0]

                # Move the para element's text to the entry
                if para_elem.text:
                    entry.text = (entry.text or "") + para_elem.text

                # Move all children of para to entry
                for child in list(para_elem):
                    entry.append(child)

                # Move the para element's tail (text after the element) to the last child or entry
                if para_elem.tail:
                    if len(entry) > 1:  # If there are children now
                        last_child = list(entry)[-1]
                        last_child.tail = (last_child.tail or "") + para_elem.tail
                    else:
                        entry.text = (entry.text or "") + para_elem.tail

                # Remove the para element
                entry.remove(para_elem)

        # Convert back to string
        return ET.tostring(root, encoding="unicode")
    except Exception as e:
        LOG.warning(f"Failed to preprocess XML table cells: {e}")
        # Return original content if preprocessing fails
        return xml_content


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
    PANDOC_LUA_CODEBLOCK_FIX_PATH = (
        Path(__file__).parent / "filters/fix-codeblock-tables.lua"
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

                # Step 1.5: Preprocess XML to fix issues
                with open(xml_temp_path, "r", encoding="utf-8") as f:
                    xml_content = f.read()

                # Replace undefined XML entities
                preprocessed_xml = preprocess_xml_undefined_entities(xml_content)

                # Flatten table cells to inline content for pipe table compatibility
                preprocessed_xml = preprocess_xml_table_cells(preprocessed_xml)

                with open(xml_temp_path, "w", encoding="utf-8") as f:
                    f.write(preprocessed_xml)

                # Step 2: Convert DocBook5 XML to Markdown using pandoc with filters
                pandoc_cmd = [
                    "pandoc",
                    "-f",
                    "docbook",
                    "--wrap=preserve",
                    "-t",
                    "markdown-simple_tables-multiline_tables-grid_tables+pipe_tables",
                    f"--filter={self.PANDOC_FILTER_PATH}",
                    f"--lua-filter={self.PANDOC_LUA_FILTER_PATH}",
                    f"--lua-filter={self.PANDOC_LUA_CODEBLOCK_FIX_PATH}",
                    str(xml_temp_path.absolute()),
                    "-o",
                    str(output_path.absolute()),
                ]
                subprocess.run(pandoc_cmd, check=True, capture_output=True)

                # Step 3: Convert any HTML tables to markdown pipe tables
                with open(output_path, "r", encoding="utf-8") as f:
                    markdown_content = f.read()

                markdown_content = convert_html_tables_to_markdown(markdown_content)

                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(markdown_content)

                # Step 4: Compact pipe tables by removing extra spaces before pipes
                # NOTE: Disabled for now - the sed pattern affects code blocks too
                # The Lua filter ensures code blocks have correct indentation
                # TODO: Create a smarter sed pattern or do this in the Lua filter
                # compact_cmd = [
                #     'sed', '-i', '-E',
                #     's/ +\\|/ |/g',
                #     str(output_path.absolute())
                # ]
                # subprocess.run(compact_cmd, check=True)

                LOG.info("Successfully converted: %s -> %s", input_path, output_path)

                return fixes_by_file

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
        (Path(__file__).parent / "filters/pandoc-docs-filter.py").absolute()
    ).absolute()
    PANDOC_LUA_FILTER_PATH = (
        (Path(__file__).parent / "filters/tightlists.lua").absolute()
    ).absolute()
    PANDOC_LUA_CODEBLOCK_FIX_PATH = (
        Path(__file__).parent / "filters/fix-codeblock-tables.lua"
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

                    # Step 1.5: Preprocess XML to fix issues
                    with open(xml_temp_path, "r", encoding="utf-8") as f:
                        xml_content = f.read()

                    # First escape any invalid angle brackets (like <key=value>)
                    preprocessed_xml = preprocess_xml_escape_angle_brackets(xml_content)

                    # Replace undefined XML entities before parsing
                    preprocessed_xml = preprocess_xml_undefined_entities(
                        preprocessed_xml
                    )

                    # Flatten table cells to inline content for pipe table compatibility
                    preprocessed_xml = preprocess_xml_table_cells(preprocessed_xml)

                    # Then convert list titles to formalpara
                    preprocessed_xml = preprocess_xml_list_titles(preprocessed_xml)

                    with open(xml_temp_path, "w", encoding="utf-8") as f:
                        f.write(preprocessed_xml)

                    # Step 2: Convert DocBook5 XML to Markdown using pandoc with filters
                    pandoc_cmd = [
                        "pandoc",
                        "-f",
                        "docbook",
                        "--wrap=preserve",
                        "-t",
                        "markdown-simple_tables-multiline_tables-grid_tables+pipe_tables",
                        f"--filter={self.PANDOC_FILTER_PATH}",
                        f"--lua-filter={self.PANDOC_LUA_FILTER_PATH}",
                        f"--lua-filter={self.PANDOC_LUA_CODEBLOCK_FIX_PATH}",
                        str(xml_temp_path.absolute()),
                        "-o",
                        str(output_path.absolute()),
                    ]
                    subprocess.run(
                        pandoc_cmd, check=True, capture_output=True, text=True
                    )

                    # Step 3: Convert any HTML tables to markdown pipe tables
                    with open(output_path, "r", encoding="utf-8") as f:
                        markdown_content = f.read()

                    markdown_content = convert_html_tables_to_markdown(markdown_content)

                    with open(output_path, "w", encoding="utf-8") as f:
                        f.write(markdown_content)

                    # Step 4: Compact pipe tables by removing extra spaces before pipes
                    # NOTE: Disabled for now - the sed pattern affects code blocks too
                    # TODO: Create a smarter sed pattern or do this in the Lua filter
                    # compact_cmd = [
                    #     'sed', '-i', '-E',
                    #     's/ +\\|/ |/g',
                    #     str(output_path.absolute())
                    # ]
                    # subprocess.run(compact_cmd, check=True)

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
                LOG.error("Failed to convert %s: %s", input_path, str(e))
                LOG.error("Continuing with next document...")

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
                LOG.error("Failed to convert %s: %s", input_path, str(e))
                LOG.error("Continuing with next document...")

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
