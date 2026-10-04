#!/usr/bin/env bash
set -euo pipefail
mkdir -p /results
run="/results/$(date -u +%Y%m%dT%H%M%SZ)-$$"
export SGLANG_CACHE_DIR=/tmp/sglang-cache TORCH_EXTENSIONS_DIR=/tmp/torch-extensions
case "${1:-demo}" in
  tests) exec bash /opt/toolgap/scripts/test.sh;;
  demo) export TOOLGAP_RUN_DIR="$run"; exec bash /opt/toolgap/examples/demo.sh;;
  tool-loop) export TOOLGAP_RUN_DIR="$run"; exec bash /opt/toolgap/examples/tool_loop.sh;;
  benchmark) exec python /opt/toolgap/benchmark/run.py --model-path /opt/model --work-dir "$run/work" --results-dir "$run/results" --repetitions 3;;
  *) echo 'Expected tests, tool-loop, demo or benchmark' >&2; exit 2;;
esac
