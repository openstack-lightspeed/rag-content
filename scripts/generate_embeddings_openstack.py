#!/usr/bin/env python3

"""Utility script to generate embeddings."""

import argparse
import logging
import os
from pathlib import Path

from lightspeed_rag_content.metadata_processor import MetadataProcessor
from lightspeed_rag_content.document_processor import DocumentProcessor

logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


class OpenstackDocsMetadataProcessor(MetadataProcessor):
    ROOT_URL = "https://docs.openstack.org"

    def __init__(self, docs_path, base_url=ROOT_URL):
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
        return (
            self.base_url.format(self.version) + "/" + str(Path(file_path).parent.name)
        )


def get_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate vector DB embeddings!")

    # TODO(lpiwowar): We should be able to support building of a single vector database
    #                 for both upstream and downstream documentation
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-rf",
        "--rhoso-folder",
        type=Path,
        required=False,
        help="Directory containing the plain text RHOSO documentation",
    )
    group.add_argument(
        "-of",
        "--openstack-folder",
        type=Path,
        required=False,
        help="Directory containing the plain text OpenStack documentation",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        type=Path,
        help="Vector DB output folder",
    )
    parser.add_argument(
        "-i",
        "--index",
        required=True,
        type=str,
        help="Index name that should be attached to the data stored in the vector DB",
    )
    parser.add_argument(
        "-w",
        "--workers",
        required=True,
        default=-1,
        type=int,
        help=(
            "Number of workers to parallelize the data loading. Set to a "
            "negative value by default, turning parallelism off"
        ),
    )
    parser.add_argument(
        "-md",
        "--model-dir",
        required=True,
        type=Path,
        default="embeddings_model",
        help="Directory containing the embedding model",
    )
    parser.add_argument(
        "-mn",
        "--model-name",
        required=True,
        type=str,
        help="HF repo id of the embedding model",
    )
    parser.add_argument(
        "-c",
        "--chunk",
        required=False,
        type=int,
        default=380,
        help="Chunk size for embedding",
    )
    parser.add_argument(
        "-l",
        "--overlap",
        required=False,
        type=int,
        default=0,
        help="Chunk overlap for embedding",
    )
    parser.add_argument(
        "-em",
        "--exclude-metadata",
        nargs="+",
        required=False,
        type=str,
        default=None,
        help="Metadata to be excluded during embedding",
    )
    # TODO(lpiwowar): Add support for different vector stores
    parser.add_argument(
        "--vector-store-type",
        default="faiss",
        choices=["faiss"],
        help="vector store type to be used.",
    )

    return parser


if __name__ == "__main__":
    parser = get_argument_parser()
    args = parser.parse_args()

    output_dir = os.path.normpath("/" + str(args.output)).lstrip("/")
    if output_dir == "":
        output_dir = "."

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

    if args.openstack_folder:
        metadata_parser = OpenstackDocsMetadataProcessor(args.openstack_folder)
        folder = str(args.openstack_folder)
    else:
        metadata_parser = RedHatDocsMetadataProcessor(args.rhoso_folder)
        folder = str(args.rhoso_folder)

    # Process documents
    document_processor.process(
        folder,
        metadata=metadata_parser,
        required_exts=[
            ".txt",
        ],
    )

    # Save to the output directory
    document_processor.save(args.index, str(output_dir))
