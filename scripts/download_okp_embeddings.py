#!/usr/bin/env python3
# Copyright 2026 Red Hat, Inc.
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
"""Download the OKP embeddings model from Hugging Face."""

import argparse
import sys

from huggingface_hub import snapshot_download

MODEL_ID = "ibm-granite/granite-embedding-30m-english"
DEFAULT_OUTPUT_DIR = "okp_embeddings_model"


def main():
    parser = argparse.ArgumentParser(
        description="Download the OKP embeddings model from Hugging Face."
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to save the model (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    print(f"Downloading model {MODEL_ID} to {args.output_dir}")
    try:
        snapshot_download(repo_id=MODEL_ID, local_dir=args.output_dir)
    except Exception as e:
        print(f"Failed to download model {MODEL_ID}: {e}", file=sys.stderr)
        sys.exit(1)
    print("Download complete.")


if __name__ == "__main__":
    main()
