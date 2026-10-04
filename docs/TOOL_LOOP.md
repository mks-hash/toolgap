# ToolGap v0.2: a real tool loop

Status: experimental real model/tool/continuation demo validated in one L4 session.
See [the measured results and controls](TOOL_LOOP_VALIDATION.md).
No production-readiness claim is made. The v0.1
45-trial benchmark and its pinned release are unchanged.

ToolGap hides restore latency when reusable KV has fallen below resident L2/GPU.
A tool call alone does not make prefetch useful.

## Run on an existing compatible GPU

Install/apply the pinned runtime using `bash scripts/install.sh`. Use the exact
Qwen model revision and CUDA environment in [REPRODUCE.md](REPRODUCE.md). Install
the small client in that Python environment:

```bash
python -m pip install -e .
MODEL_PATH=/path/to/Qwen2.5-1.5B-Instruct \
SGLANG_CHECKOUT="$PWD/vendor/sglang" \
bash examples/tool_loop.sh
```

This command creates no cloud resources. It starts local servers sequentially,
performs 12 runs (three repetitions of four conditions), then stops them. Source
and tokenizer checks reject mismatches; users must also provide the model weights
from the pinned revision. The guard verifies tokenizer/config, not all weight files.
A busy port, invalid model tool call, missing L3 pages, or incorrect output fails
explicitly. There is no synthetic tool-call fallback.

The Qwen model selects `search_documents`; a subprocess scans a fixed 10,000-record
synthetic document archive and returns evidence and its document ID. The model
then consumes that actual tool result and must return the same ID. The archive
is a reproducible workload fixture, not an external production dataset. No sleep
or delay padding is used for tool work. Corpus size is fixed before GPU measurement.
The measured prompt currently contains 3511 pinned-tokenizer tokens; the exact
saved prefix length also includes the actual generated tool-call tokens and is
recorded per run. This is not the v0.1 4096-token workload.

## Matched cache conditions

A normal model request creates one reference file-L3 snapshot. Every condition
receives a copy of the same payloads, verified by SHA256 before measurement.
Fresh processes use the same model, prompt, salt, generation flags, corpus and
continuation. Identical model tool-call IDs, tool results and continuation output
IDs are mandatory across all conditions.

* **L3-only:** an explicit memory-cache flush preserves L3. Immediately before
  tool dispatch, a scheduler-thread probe must report GPU hit=0, host hit=0,
  and all saved-prefix storage pages available.
* **Resident:** no eviction is applied; the same probe must find the entire saved
  prefix in GPU/host cache. No measured L3 payload reads are permitted.

Each scenario compares ordinary request-time restore against proactive restore
while the tool subprocess performs retrieval. The controlled flush demonstrates
the prerequisite cache state; it does not claim tool calls themselves cause
KV eviction. The probe uses `match_prefix` and storage `exists`, never `get`.
Payload verification/copying can warm OS page cache in both treatments.

## Thin client and ownership contract

```python
from toolgap import PrefetchClient

async with PrefetchClient(url, headers=admin_headers) as client:
    state = await client.submit(operation_id, exact_token_ids,
                                cache_salt=salt, ttl_ms=10000)
    state = await client.status(operation_id)
    state = await client.cancel(operation_id)
```

`operation_id` must identify only this caller's operation. Reusing an ID with a
changed prefix/salt is rejected by the runtime. Token IDs must be the actual
saved sequence for this model/tokenizer and salt namespace. Decode/re-encode of
conversation history can change cache identity; the demo only encodes the newly
appended tool-response envelope. There is no invented session abstraction.

The example integration starts tool work and submit concurrently. Success
returns without waiting for submit or canceling an in-flight restore; the
continuation may join it through the existing runtime. The caller awaits the
submission task after generation and before closing the client. Admission or
HTTP transport rejection permits ordinary generation. Tool failure or external
cancellation attempts bounded cancellation of this operation and records whether
cleanup was confirmed. Transport failures may leave acceptance uncertain: the
server TTL is a backstop, not a promise that the client knows reclamation finished.
Permanently blocked backend I/O remains unsupported. Closing the transport alone
does not cancel a useful prefetch.

## Evidence

`tool-loop-trials.json` records t0 dispatch, t1 submit send, t2 L2 publication,
t3 tool completion, t4 continuation submission and t5 first token. It additionally
records scheduler acceptance, restore-operation start, backend I/O interval,
RPC overhead, TTFT, agent-step latency, hits, bytes, duplicate pages, evictions,
output IDs and post-flush host-slot/in-flight accounting. All timestamps use
Linux monotonic time on one machine. JSONL trace and server logs accompany each run.
CSV and four-group median summary are emitted on complete success.

`hidden_restore_path_ms = max(0, min(t2,t4)-t1)` includes queueing/control time;
`io_hidden_ms` measures only actual backend I/O before arrival. Neither is itself
a causal estimate of TTFT saved. Paired TTFT and full-step results provide that
comparison. Resident mode is an expected negative control, not a speedup target.
A short actual tool can expose residual restore latency; do not pad it to improve
results. New results must be reported even when overlap or benefit is small.

## Local checks

```bash
bash scripts/test_client.sh
# In the pinned SGLang CPU-test environment, also run:
python -m pytest tests/test_residency_probe.py
TOOLGAP_TOKENIZER_PATH="$MODEL_PATH" \
python -m unittest discover -s tests -p test_pinned_template.py -v
```

The residency test needs SGLang's mem_cache test directory and demo plugin on
PYTHONPATH (see the local validation report). It uses real file-backend/cache
fixtures. The client tests use a mock HTTP transport; they do not claim GPU
validation. Scope remains one worker/trajectory, full attention, file L3,
TP1/PP1. No new runtime patch, backend, distributed layer or agent framework.
