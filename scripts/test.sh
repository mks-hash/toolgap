#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
sglang=${SGLANG_CHECKOUT:-"$root/vendor/sglang"}
export PYTHONPATH="$sglang/python:$sglang/test/registered/unit/mem_cache:${PYTHONPATH:-}"
export SGLANG_UNIFIED_RADIX_TREE_CORE_BACKEND=python PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
exec python -m pytest "$sglang/test/registered/unit/mem_cache/test_proactive_prefetch.py" "$sglang/test/registered/unit/mem_cache/test_proactive_prefetch_api.py" -q "$@"
