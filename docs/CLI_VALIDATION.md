# CLI increment: local validation

Validated on 2026-10-04, on development branch `feat/multi-session-admission`.
Package version: `0.3.0.dev0`. This increment is local and unreleased.

## Result

| Check | Result |
|---|---|
| Combined CPU regressions | 102 passed; 22 additional subtests passed; 0 failures/errors/skips |
| Combined suite duration | 10.85 seconds |
| Ruff lint and format | Passed for all seven checked Python files |
| Whitespace validation | `git diff --check` passed |
| Offline wheel build and installation | Passed; console and module entry points work |
| Installed CLI against localhost HTTP fixture | Passed: three control POSTs and four metadata GETs |
| Editable install: source/tokenizer doctor | Passed: eight source hashes and five tokenizer/config hashes |
| Existing recorded v0.1 evidence replay | Passed: 45 recorded trials |
| Existing recorded v0.2 evidence replay | Passed: 12 recorded runs and 52 recorded regressions |

The combined suite contains the previous 80 tests and 22 new CLI test cases.
Pytest also reports 22 passing subtests. Its JUnit output counts 124 entries;
this does **not** mean 124 independent regression tests. Existing deprecation
warnings remain (22 warnings); they did not fail the run.

Environment: Python 3.12.14, Torch 2.13.0+cu130, SGLang CPU engine with CUDA
devices hidden. No CUDA kernels, model forward, H2D or generation were run.
The pinned source checkout was `3e60ad803c6b01832b527f4a1dcbeb7a5449964b`.

## What was checked

CLI cases cover exact token/salt/ID/TTL transport; conflicting or invalid input;
generated operation ID retention; one RPC without retries; server rejection;
transport uncertainty; malformed/foreign responses; authentication and secret
redaction; interruption; and cancellation with physical cleanup still pending.
Completed cancellation is not presented as eviction of shared L2.

Doctor cases cover matching/missing/changed local files, unsupported server
scope, missing routes, malformed metadata, unreachable endpoints, backend-status
admin authorization, and optional local NVIDIA inventory. Missing evidence is
reported as UNKNOWN rather than silently passing.

The installed-wheel HTTP fixture used an ephemeral loopback port and the actual
console/module commands outside the source directory. It verified:

- `submit`, `status`, `cancel`: exactly three POSTs with the expected payloads
  and bearer header;
- remote doctor: exactly four GETs (`/openapi.json`, `/server_info`,
  `/hicache/storage-backend`, `/model_info`);
- no `/health`, `/health_generate`, generation or state-changing diagnostic
  request;
- no imports of Torch, Transformers or SGLang in the fresh CLI process.

`/health` is intentionally excluded: the pinned SGLang implementation can
generate on that endpoint when its generation flag is enabled.

The wheel includes the packaged compatibility manifest and console entry point:

```text
toolgap-0.3.0.dev0-py3-none-any.whl
SHA256: 6b985e583a426229949ea7167d93f2bcaacea12f5daf28ddfd7080da693e2b02
```

This hash identifies the local build, not a published distribution or a promise
that future rebuilds produce byte-identical wheel archives.

## Reproduce locally

For client/CLI tests, install the development package and activate a compatible
Python environment. The tokenizer-dependent check can use the existing pinned
local tokenizer directory; no download is required.

```bash
python -m pip install -e .
export TOOLGAP_TOKENIZER_PATH=/path/to/pinned/tokenizer
bash scripts/test_client.sh
```

For the combined runtime/client suite, from the parent project directory using
the existing CPU environment and patched checkout:

```bash
export PATH="$PWD/.venv-stage1_6/bin:$PATH"
export SGLANG_CACHE_DIR="$PWD/stage1_6/cache"
export TORCH_EXTENSIONS_DIR="$PWD/stage1_6/cache/torch_extensions"
export TORCHINDUCTOR_CACHE_DIR=/tmp/toolgap-v03-inductor
export TRITON_CACHE_DIR=/tmp/toolgap-v03-triton
export SGLANG_USE_CPU_ENGINE=1
export SGLANG_UNIFIED_RADIX_TREE_CORE_BACKEND=python
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export CUDA_VISIBLE_DEVICES=99
export TOOLGAP_TOKENIZER_PATH="$PWD/stage2b/v02_local/tokenizer"
export PYTHONPATH="$PWD/toolgap/src:$PWD/toolgap/examples/tool_loop:$PWD/toolgap/examples/tool_loop/plugin:$PWD/sglang-proactive/python:$PWD/sglang-proactive/test/registered/unit/mem_cache"
python -m pytest \
  sglang-proactive/test/registered/unit/mem_cache/test_prefetch_finite_io.py \
  sglang-proactive/test/registered/unit/mem_cache/test_proactive_prefetch.py \
  sglang-proactive/test/registered/unit/mem_cache/test_proactive_prefetch_api.py \
  toolgap/tests -q
```

Local command usage, input format and exit codes are documented in [CLI.md](CLI.md).
The project environment also has this development package installed editably;
its `toolgap` command can run the source/tokenizer doctor without a server.

Local build/test artifacts are under ignored `work/cli/`: `cpu-tests.log`,
`cpu-results.xml`, `wheel-build-final.log`, `wire-reports.json`,
`editable-doctor.json`, and `wheels/`. They are not new benchmark measurements.

## Limits and unchanged evidence

The HTTP fixture tests packaging and transport against a controlled server; it
does not prove live SGLang cache behavior. Doctor's PASS applies only to requested
file/inventory/metadata checks. It does not verify model weights, whole-tree Git
identity, remote/local model equivalence, successful restore or cache residency.

No GPU run, infrastructure mutation, runtime patch change or new performance
measurement was performed for this CLI increment. The previous
[two-caller GPU smoke](MULTI_SESSION_GPU_SMOKE.md) remains separate evidence.
Published v0.1/v0.2 benchmark data and the technical report remain unchanged.
