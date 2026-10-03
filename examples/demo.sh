#!/usr/bin/env bash
# Synthetic tool wait, genuine file KV restore and model continuation. Requires CUDA.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
if [[ "${1:-}" == --replay ]]; then exec python3 "$root/scripts/check_evidence.py"; fi
: "${MODEL_PATH:?Set MODEL_PATH to the pinned downloaded Qwen model directory}"
sglang=${SGLANG_CHECKOUT:-"$root/vendor/sglang"}
export PYTHONPATH="$sglang/python:$sglang/test/registered/unit/mem_cache:${PYTHONPATH:-}"
export SGLANG_UNIFIED_RADIX_TREE_CORE_BACKEND=python CUBLAS_WORKSPACE_CONFIG=:4096:8
export SGLANG_DEBUG_MEMORY_POOL=1 TORCH_CUDA_ARCH_LIST=8.9
run=${TOOLGAP_RUN_DIR:-"$root/work/demo-$(date -u +%Y%m%dT%H%M%SZ)"}
exec python "$root/benchmark/run.py" --model-path "$MODEL_PATH" --work-dir "$run/work" --results-dir "$run/results" --repetitions 1 --gaps-ms 500
