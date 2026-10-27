"""Explicit operator step: download the tested public embedding model once.

Install requirements-memory.txt first. Apollo itself only loads local files.
"""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Dedicated local model directory')
    args = parser.parse_args()
    from huggingface_hub import snapshot_download
    path = snapshot_download(
        'sentence-transformers/all-MiniLM-L6-v2',
        revision='1110a243fdf4706b3f48f1d95db1a4f5529b4d41',
        local_dir=str(args.directory.resolve()),
        allow_patterns=['*.json', '*.txt', '*.safetensors'],
        ignore_patterns=['onnx/*', 'openvino/*'],
    )
    print('Provisioned model directory:', path)
    print('Set APOLLO_EMBEDDING_MODEL to this directory in the backend service environment and restart.')


if __name__ == '__main__':
    main()
