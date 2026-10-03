#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
target=${1:-"$root/vendor/sglang"}
if [[ -e "$target" ]]; then echo "Target exists; supply a new checkout path" >&2; exit 1; fi
mkdir -p "$(dirname "$target")"
git clone --filter=blob:none --no-checkout https://github.com/sgl-project/sglang.git "$target"
base=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sglang_base"])' "$root/compatibility.json")
git -C "$target" checkout --detach "$base"
python3 "$root/scripts/apply.py" "$target"
echo "Source ready: $target. See docs/REPRODUCE.md for the pinned CUDA environment."
