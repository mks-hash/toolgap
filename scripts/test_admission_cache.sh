#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
sglang=${SGLANG_CHECKOUT:-"$root/vendor/sglang"}
export SGLANG_USE_CPU_ENGINE=1 SGLANG_UNIFIED_RADIX_TREE_CORE_BACKEND=python
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 CUDA_VISIBLE_DEVICES=99
export SGLANG_CACHE_DIR=${SGLANG_CACHE_DIR:-"$root/work/cpu-cache"}
export TORCH_EXTENSIONS_DIR=${TORCH_EXTENSIONS_DIR:-"$SGLANG_CACHE_DIR/torch_extensions"}
export TORCHINDUCTOR_CACHE_DIR=${TORCHINDUCTOR_CACHE_DIR:-"$SGLANG_CACHE_DIR/inductor"}
export TRITON_CACHE_DIR=${TRITON_CACHE_DIR:-"$SGLANG_CACHE_DIR/triton"}
export PYTHONPATH="$root/src:$sglang/python:$sglang/test/registered/unit/mem_cache:${PYTHONPATH:-}"
exec python -m pytest "$root/tests/test_admission_real_cache.py" -q "$@"
