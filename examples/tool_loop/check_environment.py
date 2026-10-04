"""Offline exact-source/tokenizer guard; never provisions or downloads anything."""

import argparse
import hashlib
import json
from pathlib import Path


def check(source, model):
    manifest = json.loads(
        Path(__file__).with_name("compatibility-files.json").read_text()
    )
    for root, files in [
        (Path(source), manifest["source_files"]),
        (Path(model), manifest["model_tokenizer_files"]),
    ]:
        for name, expected in files.items():
            actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(
                    f"Refusing incompatible source/model tokenizer: {root / name}"
                )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sglang", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    print("COMPATIBILITY_FILES_OK", json.dumps(check(args.sglang, args.model)))
