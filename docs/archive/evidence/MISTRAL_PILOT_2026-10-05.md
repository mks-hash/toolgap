# Mistral pilot: failed live tool gate, pressure not evaluated

Date: 2026-10-05 (Europe/Moscow). One approved L4 session. This document is a
sanitized outcome summary; raw host/cloud logs remain private and were not
copied into this repository. See the
[machine-readable summary](../../../research/agent_resume/compatibility-pilot-2026-10-05.json).

| Check | Actual result |
|---|---|
| BF16 Mistral model on L4 | Loaded successfully |
| Initial actual model generations | Three completed |
| Guest container CPU fixtures | 168 passed; 58 subtests passed; 40 warnings |
| Useful live tasks | 0/3 passed |
| Executed tools / continuations / proactive operations | 0 / 0 / 0 |
| 12-agent baseline / proactive blocks | Not run |
| Natural L3-only opportunities / prefetch benefit under contention | Not evaluated |
| VM and boot disk | Deleted, post-delete queries empty |

Two responses began with call-like JSON and then added prose or further alleged
calls/results. Parsing rejected the extra data. The other response described
hypothetical tools and was incorrect. The model's asserted PASS did not represent
test execution. Current parsing also requires a model-generated ID; that
assumption needs local correction, but changing it alone would not repair these
recorded whole responses. Details and code findings:
[engineering review](ENGINEERING_REVIEW_2026-10-05.md).

The pilot used short diagnostic prompts (315/310/324 input tokens), not the
approximately 4k-token competing workload. GPU fit/initial generation is a
partial compatibility result, not a validated useful tool loop or HiCache
L3→L2→H2D comparison on Mistral. Prior Qwen benchmarks keep their original scope.

## Provenance

- Harness: `1a5e34c8374d641becf9dc63975a7b62382cfa0a`.
- Runtime: `3e60ad803c6b01832b527f4a1dcbeb7a5449964b`.
- Model: `mistralai/Mistral-7B-Instruct-v0.3` at
  `c170c708c41dac9275d15a8fff4eca08d52bab71`.
- Existing image digest:
  `sha256:4ae0bb2222247e51d146ff0cb9807240d5abbfe7d1b5d7eb1c9db0b072da07ec`.
- L4, 8 vCPU / 32 GiB, Ubuntu 24.04; NVIDIA driver 580.178.04,
  PyTorch 2.13.0+cu130 / CUDA 13.0, Transformers 5.17.0.
- TP1 / PP1, BF16, Triton, deterministic sampling, FULL resident host cache,
  file-backed L3 on persistent disk. GPU KV: 8192 tokens; host KV: 7632 tokens,
  1.00 decimal GB. Pressure candidate maximum running requests: four.
  This configuration differs from the initial four-GB compatibility candidate;
  its fit result must not be assigned to other profiles.

Creation-to-stop duration: 17 min 45.224 s. Compute planning estimate: $0.26 at
the previously recorded rate, approximately $0.30 at the conservative allowance.
These are not an invoice or a freshly verified price and exclude separately
retained storage. Native auto-delete was configured for 90 minutes; actual
cleanup happened earlier. There was no second execution or image/runtime change.

The original private result archive SHA256 is
`0c4328feee7a4fb36b8ba093993bff5f29fdfb5063ff5c1b158da67c671300da`;
the original pilot JSONL SHA256 is
`dc117e252a03c241e7d6992658552083f421c5b3e1f0fdd7a636a9d501661874`.
The summary retains per-response token-ID hashes and parser dispositions, but
does not contain the raw ID sequences. Full public offline replay is therefore
not provided by this summary alone.

Procedure completion was successful (`exit_code=0`), while the live task gate
failed with `LIVE_MODEL_TASK_OR_TOOL_CONTRACT_FAILED`. Intentional server
shutdown produced SIGTERM/SIGQUIT log entries; no spontaneous CUDA fit/crash
blocker was observed. No latency benefit or absence-of-opportunities conclusion
is supported by this run.
