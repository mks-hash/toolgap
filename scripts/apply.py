#!/usr/bin/env python3
"""Apply only to the exact clean upstream SHA. No fuzzy version support."""
import argparse, hashlib, json, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def run(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    args = parser.parse_args(); repo = args.checkout.resolve()
    manifest = json.loads((ROOT / "compatibility.json").read_text())
    if run(repo, "rev-parse", "HEAD") != manifest["sglang_base"]:
        raise SystemExit("Refusing checkout: HEAD does not match pinned SGLang base")
    if run(repo, "status", "--porcelain", "--untracked-files=all"):
        raise SystemExit("Refusing dirty checkout; use a fresh clone")
    patches = sorted((ROOT / "patches").glob("*.patch"))
    applied = []
    try:
        for patch in patches:
            run(repo, "apply", "--check", str(patch))
            run(repo, "apply", str(patch)); applied.append(patch)
        run(repo, "diff", "--check")
    except BaseException:
        for patch in reversed(applied):
            run(repo, "apply", "--reverse", str(patch))
        raise
    print("PATCHES_APPLIED: PASS")
if __name__ == "__main__": main()
