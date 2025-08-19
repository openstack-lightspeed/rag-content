#!/usr/bin/env python3

"""Utility script to generate embeddings."""

import shutil
import tempfile
import logging
import os
import re
from pathlib import Path
import sys

from lightspeed_rag_content import utils
from lightspeed_rag_content import okp
from lightspeed_rag_content.metadata_processor import MetadataProcessor
from lightspeed_rag_content.document_processor import DocumentProcessor
from llama_index.readers.file.markdown.base import MarkdownReader

logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

OKP_CONTENT_TYPES = ["erratas", "docs", "pages"]


def clean_url(unclean_url):
    unclean_chars = "[()]"
    clean_url = re.sub(unclean_chars, "", unclean_url)
    return clean_url


class OpenstackDocsMetadataProcessor(MetadataProcessor):
    ROOT_URL = "https://docs.openstack.org"

    def __init__(self, docs_path, base_url=ROOT_URL):
        super(OpenstackDocsMetadataProcessor, self).__init__()
        self._base_path = os.path.abspath(docs_path)
        if self._base_path.endswith("/"):
            self._base_path = self._base_path[:-1]
        self.base_url = base_url

    def url_function(self, file_path):
        return clean_url(
            self.base_url
            + file_path.removeprefix(self._base_path).removesuffix("txt")
            + "html"
        )


class RedHatDocsMetadataProcessor(MetadataProcessor):
    ROOT_URL = "https://docs.redhat.com/en/documentation/red_hat_openstack_services_on_openshift/{}/html-single"

    def __init__(self, docs_path, version, base_url=ROOT_URL):
        super(RedHatDocsMetadataProcessor, self).__init__()
        self._base_path = os.path.abspath(docs_path)
        if self._base_path.endswith("/"):
            self._base_path = self._base_path[:-1]
        self.base_url = base_url
        self.version = version

    def url_function(self, file_path: str):
        # Document name mappings for cases where internal document names
        # differ from published URL paths in Red Hat documentation
        doc_mappings = {
            "installing_openstack_services_on_openshift": "deploying_red_hat_openstack_services_on_openshift"
        }
        if "release-notes" in file_path:
            return clean_url(
                self.base_url.format(self.version)
                + "/release_notes/index#chap-release-info_release-info-top-"
                + os.path.basename(file_path).rstrip(".txt")
            )
        else:
            doc_name = str(Path(file_path).parent.name)
            # Apply document name mapping if needed
            if doc_name in doc_mappings:
                doc_name = doc_mappings[doc_name]

            return clean_url(
                self.base_url.format(self.version) + "/" + doc_name + "/index.html"
            )


#
# Functions related to OpenStack OKP
#


def copy_openstack_errata(input_dir: Path, output_dir: Path) -> Path:
    """Returns a directory containing only OpenStack related errata files."""
    errata_dir = input_dir / "errata"
    if not errata_dir.exists():
        raise ValueError(
            f"The specified errata directory '{errata_dir}' does not exist."
        )

    print("Copying OpenStack related errata files...")
    os.makedirs(output_dir / "errata", exist_ok=True)
    for f in okp.yield_files_related_to_projects(errata_dir, projects=["openstack"]):
        # Copy the file to the output directory
        shutil.copy2(f, output_dir / "errata")
    print("OpenStack related errata files copied successfully.")


def _yield_openstack_pages_md_files(base_dir):
    """Yield OpenStack related Markdown files from the given directory."""
    for root, _, files in os.walk(base_dir):
        for file in files:
            if "openstack" in file.lower() and file.lower().endswith(".md"):
                yield os.path.join(root, file)


def copy_openstack_pages(input_dir: Path, output_dir: Path) -> Path:
    """Returns a directory containing only OpenStack related pages."""
    pages_dir = input_dir / "pages"
    if not pages_dir.exists():
        raise ValueError(f"The specified pages directory '{pages_dir}' does not exist.")

    print("Copying OpenStack related pages...")
    os.makedirs(output_dir / "pages", exist_ok=True)
    for f in _yield_openstack_pages_md_files(pages_dir):
        # Copy the file to the output directory
        shutil.copy2(f, output_dir / "pages")
    print("OpenStack related pages copied successfully.")


def _yield_openstack_documentation_md_files(base_dir):
    """Yield OpenStack related documentation Markdown files from the given directory."""
    for root, dirs, files in os.walk(base_dir):
        # Only search if the current folder's name is exactly "single-page"
        if os.path.basename(root) == "single-page":
            for file in files:
                if file.lower().endswith(".md"):
                    yield os.path.join(root, file)


def copy_openstack_documentation(
    input_dir: Path, output_dir: Path, version: str
) -> Path:
    """Returns a directory containing only OpenStack related documentation files."""
    docs_dir = (
        input_dir / f"documentation/red_hat_openstack_services_on_openshift/{version}"
    )
    if not docs_dir.exists():
        raise ValueError(
            f"The specified documentation directory '{docs_dir}' does not exist."
        )

    print("Copying OpenStack documentation files...")
    os.makedirs(output_dir / "docs", exist_ok=True)
    for f in _yield_openstack_documentation_md_files(docs_dir):
        # Copy the file to the output directory
        shutil.copy2(f, output_dir / "docs")
    print("OpenStack documentation files copied successfully.")


#
# End functions related to OKP
#

if __name__ == "__main__":
    parser = utils.get_common_arg_parser()
    parser.add_argument(
        "-rf",
        "--rhoso-folder",
        type=Path,
        required=False,
        help="Directory containing the plain text RHOSO documentation",
    )
    parser.add_argument(
        "-ua",
        "--unreachable-action",
        choices=["warn", "drop", "fail"],
        default="warn",
        required=False,
        help="What to do when encountering a doc whose URL can't be reached",
    )
    parser.add_argument(
        "-osv",
        "--openstack-version",
        type=str,
        required=False,
        default="18.0",
        help="Version of the OpenStack documentation to process",
    )
    parser.add_argument(
        "-of",
        "--okp-folder",
        type=Path,
        required=False,
        help="Directory containing the OKP files",
    )
    parser.add_argument(
        "-oc",
        "--okp-content",
        nargs="+",
        choices=OKP_CONTENT_TYPES + ["all"],
        default=["all"],
        required=False,
        help="Choose one or more OKP content types, or 'all' for all of them",
    )

    args = parser.parse_args()

    if not any([args.folder, args.rhoso_folder, args.okp_folder]):
        print(
            'Error: Either the "--folder" and/or "--rhoso-folder" and/or "--okp-folder" options '
            "must be provided",
            file=sys.stderr,
        )
        sys.exit(1)

    # Instantiate Document Processor
    document_processor = DocumentProcessor(
        args.chunk,
        args.overlap,
        args.model_name,
        str(args.model_dir),
        args.workers,
        args.vector_store_type,
        args.index.replace("-", "_"),
        manual_chunking=args.manual_chunking,
    )

    # Process the OpenStack documents, if provided
    if args.folder:
        document_processor.process(
            str(args.folder),
            metadata=OpenstackDocsMetadataProcessor(args.folder),
            required_exts=[
                ".txt",
            ],
            unreachable_action=args.unreachable_action,
        )

    # Process the RHOSO documents, if provided
    if args.rhoso_folder:
        document_processor.process(
            str(args.rhoso_folder),
            metadata=RedHatDocsMetadataProcessor(
                args.rhoso_folder, args.openstack_version
            ),
            required_exts=[
                ".txt",
            ],
            unreachable_action=args.unreachable_action,
        )

    # Process the OKP files, if provided
    okp_out_dir = None
    if args.okp_folder:
        if not args.okp_folder.exists():
            raise ValueError(
                f"The specified OKP folder '{args.okp_folder}' does not exist."
            )

        print(f"Processing OKP files from: {args.okp_folder}")

        if "all" in args.okp_content:
            args.okp_content = OKP_CONTENT_TYPES

        # Create a temporary directory for OKP files
        okp_out_dir = Path(tempfile.mkdtemp(prefix="okp_openstack_"))

        for content_type in args.okp_content:
            if content_type == "erratas":
                copy_openstack_errata(args.okp_folder, okp_out_dir)
            elif content_type == "docs":
                copy_openstack_documentation(
                    args.okp_folder, okp_out_dir, version=args.openstack_version
                )
            elif content_type == "pages":
                copy_openstack_pages(args.okp_folder, okp_out_dir)

        print(
            f"Processing OpenStack related {', '.join(args.okp_content)} files in {okp_out_dir}"
        )
        document_processor.process(
            str(okp_out_dir),
            metadata=okp.OKPMetadataProcessor(),
            required_exts=[
                ".md",
            ],
            file_extractor={".md": MarkdownReader()},
            unreachable_action=args.unreachable_action,
        )

    # Save to the output directory
    document_processor.save(args.index, str(args.output))

    # Clean up the OKP output directory if it exists
    if okp_out_dir and okp_out_dir.exists():
        print(f"Cleaning up temporary OKP output directory: {okp_out_dir}")
        shutil.rmtree(okp_out_dir)
