#!/usr/bin/env python3

"""Utility script to generate embeddings."""

import os
import sys
import time

# Add the common_embedding.py to the Python path
scripts_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(scripts_dir)

from common_embeddings import (
    FileMetadataProcessor,
    get_common_arg_parser,
    filter_out_invalid_nodes,
    save_index,
    save_metadata,
    process_documents,
    get_settings,
    print_unreachable_docs_warning
)

# The OpenStack documentation base URL
OS_DOCS_ROOT_URL = "https://docs.openstack.org"

class OpenstackDocsMetadataProcessor(FileMetadataProcessor):

    def __init__(self, docs_path, base_url):
        super().__init__()
        self._base_path = os.path.abspath(docs_path)
        if self._base_path.endswith('/'):
            self._base_path = self._base_path[:-1]

        self.base_url = base_url

    def url_function(self, file_path):
        return (  # noqa: E731
            self.base_url
            + file_path.removeprefix(self._base_path).removesuffix("txt")
            + "html"
        )

if __name__ == "__main__":

    start_time = time.time()

    parser = get_common_arg_parser()
    args = parser.parse_args()
    print(f"Arguments used: {args}")

    # OLS-823: sanitize directory
    PERSIST_FOLDER = os.path.normpath("/" + args.output).lstrip("/")
    if PERSIST_FOLDER == "":
        PERSIST_FOLDER = "."

    os.environ["HF_HOME"] = args.model_dir
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    settings, embedding_dimension, storage_context = get_settings(
        args.chunk, args.overlap, args.model_dir)

    metadata_processor = OpenstackDocsMetadataProcessor(
        args.folder, OS_DOCS_ROOT_URL)

    # Load documents
    documents = process_documents(
        args.folder, metadata_func=metadata_processor.file_metadata_func,
        required_exts=['.txt',], num_workers=args.workers)
    unreachables = metadata_processor.n_unreachable_urls()
    # Create chunks/nodes
    nodes = settings.text_splitter.get_nodes_from_documents(documents)

    # Filter out invalid nodes
    good_nodes = filter_out_invalid_nodes(nodes)

    # Create & save Index
    save_index(good_nodes, storage_context, args.index, PERSIST_FOLDER)

    # Save metadata
    save_metadata(start_time, args, embedding_dimension, documents,
                  PERSIST_FOLDER)
    if unreachables > 0:
        print_unreachable_docs_warning(unreachables)