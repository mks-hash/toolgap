#!/usr/bin/env bash
# Existing GPU host only. No provisioning, downloads, or cloud execution.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
: "${MODEL_PATH:?Set MODEL_PATH to the pinned Qwen model}"
sglang=${SGLANG_CHECKOUT:-"$root/vendor/sglang"}
python "$root/examples/tool_loop/check_environment.py" --sglang "$sglang" --model "$MODEL_PATH"
export PYTHONPATH="$root/src:$sglang/python:$sglang/test/registered/unit/mem_cache:${PYTHONPATH:-}"
export SGLANG_UNIFIED_RADIX_TREE_CORE_BACKEND=python CUBLAS_WORKSPACE_CONFIG=:4096:8
export TORCH_CUDA_ARCH_LIST=8.9 SGLANG_DEBUG_MEMORY_POOL=1
run=${TOOLGAP_RUN_DIR:-"$root/work/multi-session-$(date -u +%Y%m%dT%H%M%SZ)"}
exec python "$root/examples/multi_session/demo.py" --model-path "$MODEL_PATH" \
  --work-dir "$run/work" --results-dir "$run/results" "$@"
