"""Download pinned public tokenizer files only, then verify every checksum."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    allowed = {
        "config.json",
        "tokenizer_config.json",
        "tokenizer.json",
        "special_tokens_map.json",
        "merges.txt",
        "vocab.json",
    }
    files = profile["tokenizer_files"]
    if not files or not set(files) <= allowed:
        parser.error("Profile must declare tokenizer/config files only")
    if args.output.exists():
        parser.error("Use a new directory; existing tokenizer files are never replaced")
    args.output.mkdir(parents=True)
    for name, expected in files.items():
        url = f"https://huggingface.co/{profile['model']}/resolve/{profile['revision']}/{name}"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(30_000_001)
        if (
            len(data) != expected["bytes"]
            or hashlib.sha256(data).hexdigest() != expected["sha256"]
        ):
            raise ValueError(f"Pinned tokenizer checksum/size mismatch: {name}")
        (args.output / name).write_bytes(data)
        print(name, "verified", flush=True)
    (args.output / "provenance.json").write_text(
        json.dumps(
            dict(model=profile["model"], revision=profile["revision"], files=files),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
