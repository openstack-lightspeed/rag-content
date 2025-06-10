#!/usr/bin/env python3

"""Utility script to generate embeddings."""

import logging
import os
import re
from pathlib import Path
import sys

from lightspeed_rag_content import utils
from lightspeed_rag_content.metadata_processor import MetadataProcessor
from lightspeed_rag_content.document_processor import DocumentProcessor

logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


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

    def __init__(self, docs_path, base_url=ROOT_URL, version="18.0"):
        super(RedHatDocsMetadataProcessor, self).__init__()
        self._base_path = os.path.abspath(docs_path)
        if self._base_path.endswith("/"):
            self._base_path = self._base_path[:-1]
        self.base_url = base_url
        self.version = version

    def url_function(self, file_path: str):
        if "release-notes" in file_path:
            return clean_url(
                self.base_url.format(self.version)
                + "/release_notes/index#chap-release-info_release-info-top-"
                + os.path.basename(file_path).rstrip(".txt")
            )
        else:
            return clean_url(
                self.base_url.format(self.version)
                + "/"
                + str(Path(file_path).parent.name)
            )


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
    args = parser.parse_args()

    if not args.folder and not args.rhoso_folder:
        print(
            'Error: Either the "--folder" and/or "--rhoso-folder" options '
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
            metadata=RedHatDocsMetadataProcessor(args.rhoso_folder),
            required_exts=[
                ".txt",
            ],
            unreachable_action=args.unreachable_action,
        )

    # Save to the output directory
    document_processor.save(args.index, str(args.output))
