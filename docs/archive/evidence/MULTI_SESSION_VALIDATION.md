# Multi-caller admission: local CPU validation

Date: October 4, 2026. Development branch: `feat/multi-session-admission`.
This is not a released v0.3 benchmark or GPU validation.

## Result

**70 passed / 1 skipped / 0 failed / 0 errors** (71 collected cases, 11.43 s).
There are **19 new cases**: 17 admission/transport tests and two real cache tests.
The skip is `TestPinnedTemplate.test_appended_tool_envelope_matches_qwen_chat_template`:
no offline pinned tokenizer path was supplied. No model was downloaded to remove
that skip. The other existing client/tool, finite-I/O, proactive manager, API,
and residency-probe regressions passed.

Local Python environment: Python 3.12, PyTorch 2.13.0+cu130, httpx 0.28.1;
CPU engine, Python TreeCore, GPU visibility disabled, no model forward/H2D.
The real fixture checkout was SGLang
`3e60ad803c6b01832b527f4a1dcbeb7a5449964b`, matching the published runtime patch.
Native hash compilation uses the CPU compiler; the CUDA build of PyTorch does
not mean these tests ran on GPU.

The supplied test runner was also exercised against that checkout. Existing
writable cache paths and the virtual environment's `ninja` executable were used.
Initial collection attempts needed those cache/PATH settings; no production
source workaround or dependency replacement was applied.

## Evidence established

- Two concurrent caller labels: only the first sends a restore submit. The
  second receives immediate local fallback and can proceed with independent tool
  work. No local queue or cross-tool serialization is introduced.
- On real file-backed I/O, cancelling A retains allocated host slots and blocks
  replacement admission until the terminal drain. After drain, accounting returns
  to baseline and B performs a successful subsequent restore.
- An unrelated continuation is not joined to A's restore. Identical token IDs
  under another salt miss A's published namespace, without host/device reuse.
- A's late cancel cannot issue a control call against B. Generated operation IDs
  differ between attempts and cannot be reassigned through the public property.
- A timeout followed by late success remains UNKNOWN until reconciled. Unknown
  cancel/status, missing cleanup confirmation, foreign replies, cancelled HTTP,
  and unexpected transport errors cannot release the slot speculatively.
- Serialized per-lease control prevents stale RUNNING status from overwriting a
  confirmed cancellation. EXPIRED plus pending cleanup retains admission.
- Finalized published-span accounting is once-only. Used tokens are explicitly
  caller-reported, unused published KV is separate from unknown consumption, and
  oversized input iteration/history retention are bounded.

The two real-cache checks use actual file storage, host tensors/allocator,
controller I/O workers and terminal queues; HTTP uses a MockTransport bridge to
that manager. They do not validate live network transport or simultaneous model
inference. Abandoned published KV is evictable shared L2, not operation-owned
memory; its bytes are not a measurement of all cancelled backend traffic.

## Reproduction

For a compatible activated Python environment and pinned patched checkout:

```bash
bash scripts/test_client.sh
SGLANG_CHECKOUT=/absolute/path/to/pinned/sglang bash scripts/test_admission_cache.sh
```

The combined 71-case run additionally included all ToolGap tests and these
existing SGLang files:

```text
test/registered/unit/mem_cache/test_prefetch_finite_io.py
test/registered/unit/mem_cache/test_proactive_prefetch.py
test/registered/unit/mem_cache/test_proactive_prefetch_api.py
```

For that combined pytest invocation set `PYTHONPATH` to ToolGap `src`,
`examples/tool_loop`, `examples/tool_loop/plugin`, and the checkout's `python`
and `test/registered/unit/mem_cache` directories. Use the CPU/cache environment
from `scripts/test_admission_cache.sh`, with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
The local combined log/XML are in `work/v03/cpu-tests.log` and
`work/v03/cpu-results.xml` (ignored workspace outputs).

Ruff lint/format, shell syntax checks, Python compilation, and both existing
recorded-evidence replay scripts passed. Neither runtime patch or compatibility
manifest was modified. Existing GPU datasets, report/PDF, citation and upstream
PRs remain the evidence for v0.1/v0.2, not this development increment.

## Next gate

Run two real agent trajectories with matched cache-state controls on one worker,
measuring admission/fallback, restored-span consumption, tool-step/TTFT,
duplicate reads, cleanup and interference with ordinary inference. Only after
that should load expand to 5–20 callers or runtime admission be expanded beyond
one active restore. No GPU provisioning/execution or publication was performed
for this local increment.
