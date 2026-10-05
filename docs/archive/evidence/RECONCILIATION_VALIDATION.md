# Bounded reconciliation: local validation

Date: 2026-10-04. Development branch: `feat/bounded-reconciliation`, based on
ToolGap v0.3.0 (`78a2946642bd1596cd51a7c48c607fadfca26c80`).
Pinned patched SGLang: `3e60ad803c6b01832b527f4a1dcbeb7a5449964b`.
Python 3.12.14, existing compatible CPU test environment.

## Results

| Check | Result |
|---|---|
| Combined lifecycle, proactive runtime/API and all ToolGap CPU tests | **118 passed**, 37 subtests passed, zero failures/skips |
| Standalone `scripts/test_client.sh` (no SGLang dependency) | **75 passed**, zero failures/skips |
| New bounded-reconciliation transport tests | **14 passed** |
| New real file-backend/host-allocator cancelled-read test | **PASS** |
| New existing-workflow integration test with real admission client | **PASS** |
| Ruff lint and formatting, changed Python files | **PASS** |
| Shell syntax and `git diff --check` | **PASS** |
| v0.1/v0.2 recorded-evidence replay | **PASS**, no dataset changes |

The combined suite emitted 22 existing dependency/configuration warnings
(including the disabled asyncio pytest plugin's configuration option). These
are not failures, skips or GPU validation. Local logs are retained in the ignored
`work/reconciliation/combined-cpu.log` and `client-suite.log`.

## Verified behavior

- A later caller is admitted after a matching terminal status confirms cleanup,
  while the previous owner's simulated continuation is still unfinished. An
  earlier busy caller is neither queued nor automatically retried.
- Default admission remains manual. Immediate terminal/rejected submits do not
  start background requests. Validated positive options bound status attempts.
- UNKNOWN, foreign/malformed responses and terminal-but-pending cleanup retain
  ownership. Exhausting the budget stops observation without releasing the slot;
  subsequent busy callers do not restart it. Manual reconciliation still works.
- In-flight status timeout/shutdown reaps the async transport and preserves
  uncertainty. A timeout while waiting for an existing control lock sends no
  status RPC. A replacement's slow submit cannot restart its exhausted budget.
- Explicit cancel is serialized with polling. Historical leases send no new
  control messages and cannot clear the replacement's active slot.
- Closing before the poller's first tick, during status, or before a submit reply
  leaves no poller running and does not cancel/reclaim remote work. Closed
  admission rejects new submits; retained leases still permit manual cleanup.
- Background observation never finalizes usage or evicts published cache.
  Unknown consumption remains distinct from explicit abandonment.
- The real SGLang fixture blocks a file read while its host slots remain
  allocated. Cancellation plus background status retains local admission until
  that read returns and terminal drain releases its destinations. Conservation
  checks pass, the worker survives, and the next operation publishes 12 tokens.
- The existing `trajectory()` workflow starts continuation while the background
  status response remains blocked; no workflow modification is needed.

## Reproduction

Client-only checks:

```bash
python -m pip install -e .
bash scripts/test_client.sh
```

For the combined suite, use the compatible pinned SGLang environment described
in the existing CPU-validation documents. Supply the locally available pinned
tokenizer via `TOOLGAP_TOKENIZER_PATH` to exercise its optional identity fixture:

```bash
export SGLANG_USE_CPU_ENGINE=1 SGLANG_UNIFIED_RADIX_TREE_CORE_BACKEND=python
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 CUDA_VISIBLE_DEVICES=99
export SGLANG_CACHE_DIR=/path/to/existing/cpu-cache
export TORCH_EXTENSIONS_DIR="$SGLANG_CACHE_DIR/torch_extensions"
export TOOLGAP_TOKENIZER_PATH=/path/to/pinned/tokenizer
export PYTHONPATH="$PWD/src:$PWD/examples/tool_loop:$PWD/examples/tool_loop/plugin:$SGLANG_CHECKOUT/python:$SGLANG_CHECKOUT/test/registered/unit/mem_cache"
python -m pytest \
  "$SGLANG_CHECKOUT/test/registered/unit/mem_cache/test_prefetch_finite_io.py" \
  "$SGLANG_CHECKOUT/test/registered/unit/mem_cache/test_proactive_prefetch.py" \
  "$SGLANG_CHECKOUT/test/registered/unit/mem_cache/test_proactive_prefetch_api.py" \
  tests -q
```

## Evidence limits

No GPU was provisioned or executed for this increment. The SGLang checkout and
runtime patches remain unchanged. Earlier GPU measurements belong to their
original versions and do not measure this poller. These tests demonstrate local
ownership/lifecycle behavior, not a throughput, aggregate agent-latency, or
fairness improvement. A later-arrival workload would be needed to measure
performance and the added status-RPC overhead.
