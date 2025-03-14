#!/usr/bin/env python3

"""Utility script to generate embeddings."""

import logging
import os

from lightspeed_rag_content import utils
from lightspeed_rag_content.metadata_processor import MetadataProcessor
from lightspeed_rag_content.document_processor import DocumentProcessor

logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# The OpenStack documentation base URL
OS_DOCS_ROOT_URL = "https://docs.openstack.org"


class OpenstackDocsMetadataProcessor(MetadataProcessor):
    def __init__(self, docs_path, base_url):
        super(OpenstackDocsMetadataProcessor, self).__init__()
        self._base_path = os.path.abspath(docs_path)
        if self._base_path.endswith("/"):
            self._base_path = self._base_path[:-1]
        self.base_url = base_url

    def url_function(self, file_path):
        return (
            self.base_url
            + file_path.removeprefix(self._base_path).removesuffix("txt")
            + "html"
        )


if __name__ == "__main__":
    parser = utils.get_common_arg_parser()
    args = parser.parse_args()
    print(f"Arguments used: {args}")

    output_dir = os.path.normpath("/" + args.output).lstrip("/")
    if output_dir == "":
        output_dir = "."

    # Instantiate Metadata Processor
    metadata_processor = OpenstackDocsMetadataProcessor(args.folder, OS_DOCS_ROOT_URL)

    # Instantiate Document Processor
    document_processor = DocumentProcessor(
        args.chunk,
        args.overlap,
        args.model_name,
        args.model_dir,
        args.workers,
        args.vector_store_type,
        args.index.replace("-", "_"),
    )

    # Process documents
    document_processor.process(
        args.folder,
        metadata=metadata_processor,
        required_exts=[
            ".txt",
        ],
    )

    # Save to the output directory
    document_processor.save(args.index, output_dir)
