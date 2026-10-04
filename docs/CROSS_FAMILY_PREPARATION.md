# Cross-family agent-resume harness: local preparation

Updated 2026-10-04. **Local foundation implemented; model/GPU research pending.**
This is development work after v0.3.0, not a new release or performance result.
The [research objective](RESEARCH_PLAN.md) remains useful multi-family agent
completion under finite cache capacity. Historical GPU datasets are unchanged.

## What runs now

`research/agent_resume/` contains a native-template adapter, a streaming generation
transport, a multi-round runner, three repository tasks, evidence graders, and
pinned candidate profiles. It borrows an explicitly configured server; it never
provisions a GPU, launches a server, downloads model weights or flushes a cache.

The useful tools search a bounded immutable Git snapshot, read numbered source
lines, and run one fixed, real CPU regression command. Model-provided shell
commands are never executed. The regression tool checks that live source/test
hashes equal the snapshot before running. Subprocess output is retained as an
artifact; varying test-duration text is excluded from the model-facing result.

Tasks ask for the physical-cleanup field, the overlap-estimate function, and the
result of the admission-hints regression suite with cited test-class evidence.
These three small tasks validate plumbing and grading; they are not yet the
long-context document/pressure workload or a task-quality benchmark. Incorrect
answers, invalid calls, tool errors, context limits and exhausted round budgets
remain in the output. Citations must have been returned by an actual tool.

| Candidate | Native tokenizer/template | Model-generated tool loop | New GPU validation |
|---|---|---|---|
| Qwen2.5-1.5B-Instruct | PASS, pinned historical tokenizer | Not run by this harness | None |
| Qwen2.5-7B-Instruct | PASS | Pending | None |
| Mistral-7B-Instruct-v0.3 | PASS | Pending | None |
| Llama-3.1-8B-Instruct | Pending access; public requests returned HTTP 401 | Pending | None |

For Llama, only format/parser fixtures passed. No native-template, model or
runtime compatibility claim follows. This preparation did not accept gated-model
terms or use private credentials. There are no model weights in this increment.

## Exact saved-token contract

The first prompt is rendered with the official local tokenizer. Every next input
starts with the **unchanged prior prompt IDs plus actual generated IDs**. A
canonical transcript derives only the new tool-result/end-of-turn suffix; it
never replaces the generated decision with re-encoded canonical JSON. The
adapter checks append stability and rejects unsupported earlier-history changes.
The reusable span excludes the final saved token and is aligned to 16-token pages.
Salt is recorded; the existing admission layer supplies unique operation IDs.

Mistral v0.3's inspected template includes system content only when its user turn
is the final message. Appending a tool history can therefore remove earlier
system instructions. This adapter folds system instructions into the initial
user turn **before initial generation**. A native-tokenizer negative check
confirms that the unnormalized changing history is rejected. Model-supplied
nine-character alphanumeric tool IDs are required; they are never fabricated.

Only one custom JSON tool call per assistant turn is supported. Llama built-in
Python expressions and parallel tool calls are unsupported and recorded as
failures. The template date is fixed at `04 Oct 2026` and recorded in provenance.

## Local results and their meaning

- Combined targeted SGLang/SDK/harness CPU suite: **149 passed**, **58 subtests**,
  zero failures/skips; 22 existing environment/deprecation warnings.
- New harness suite: **19 tests**. It covers preservation of noncanonical IDs,
  append rejection, tool IDs, provenance/settings guards, useful tools/graders,
  streaming, early continuation, owned cancellation and ambiguous cleanup.
- Three native tokenizers each ran three successful scripted two-tool-round
  trajectories and one deliberately invalid decision retained as a failure.
  Boundary checks cover missing/present end-of-turn markers. The fixed regression
  tool actually ran **9 CPU tests** for each model's fixture (as recorded
  in `local-validation.json`; corrected the earlier prose count of 14).
- Fresh-directory public Mistral tokenizer download verified all four pinned
  file sizes and SHA-256 checksums.
- Both historical evidence checkers passed: 45 v0.1 trials and 12 v0.2 GPU runs.

Scripted decisions are labeled `SCRIPTED_CPU_FIXTURE`. Their clocks are CPU
diagnostics, not LLM latency measurements, model task-success rates or speedups.
Native files establish tokenizer/template behavior, not generation correctness.
Python 3.12.14 and Transformers 5.17.0 were used. Sandbox restrictions stalled
asyncio executor wakeup/shutdown; the completed checks ran outside that sandbox.

Raw local results/logs are in ignored `work/cross-family/`. The compact checked-in
summary is [local-validation.json](../research/agent_resume/local-validation.json).
Per-run manifests include source SHA, tokenizer/config hashes and harness hashes.

## Reproduce CPU preparation

From this development checkout, install the SDK and a tokenizer runtime. No
CUDA/model runtime is needed for these commands:

```bash
python -m pip install -e . 'transformers==5.17.0'
python -m research.agent_resume.fetch \
  --profile research/agent_resume/profiles/mistral.json \
  --output work/mistral-tokenizer
python -m research.agent_resume.prepare \
  --family mistral --tokenizer work/mistral-tokenizer \
  --output work/mistral-cpu-check.json
bash scripts/test_client.sh
```

`fetch` downloads only tokenizer/config files at the pinned model SHA, verifies
every size/checksum and refuses an existing directory. It has no retry loop or
weight download. Use `qwen.json` / `qwen7.json` and `--family qwen` / `qwen7` for
the other prepared models. `prepare` loads local files with
`trust_remote_code=False`, checks profile hashes and uses an immutable source
snapshot at `fe6217292ce4f01c592a2d7274137d826a75e1a0`.

## Live diagnostic interface, after separately approved GPU setup

Each profile defines candidate server settings explicitly, independently of the
historical `Engine.start()` command. TP1/PP1/DP1, BF16, resident FULL, file storage,
8192 context/total-token limits, a 4 GiB host pool and one running request are
**initial compatibility candidates**, not validated fits or pressure profiles.
Raw BF16 KV estimates from config are 28 KiB/token for Qwen1.5B, 56 KiB/token for
Qwen7B and 128 KiB/token for Mistral7B. They exclude weights and runtime overhead.
No claim that a 7B model fits a particular GPU is made here.

Supply a deployment record from the real server setup, for example:

```json
{
  "model": "mistralai/Mistral-7B-Instruct-v0.3",
  "revision": "c170c708c41dac9275d15a8fff4eca08d52bab71",
  "model_path": "/absolute/path/to/pinned/model",
  "runtime_sha": "3e60ad803c6b01832b527f4a1dcbeb7a5449964b",
  "resolved_cache_mode": "FULL"
}
```

The runtime SHA/cache mode are operator declarations checked during deployment;
the runner does not attest loaded weight files. It compares model/revision
declarations, local tokenizer hashes and resolved server settings, failing on
mismatch. It does not replace deployment validation. Against an already running
and separately approved server:

```bash
python -m research.agent_resume.live \
  --profile research/agent_resume/profiles/mistral.json \
  --deployment work/mistral-deployment.json --tokenizer work/mistral-tokenizer \
  --server http://127.0.0.1:30000 --mode request_time \
  --output work/mistral-live-baseline
# A separate diagnostic uses --mode proactive and a new output directory.
```

The runner records full task latency, actual input/output IDs, per-tool timing,
continuation TTFT and **tool-dispatch-to-first-token**, grading, tool artifacts,
control send/receive events and cleanup. Submission runs concurrently with useful
tool work; continuation never waits for submit. `--reconcile-ms` optionally enables
the existing bounded reconciliation policy; omission preserves manual behavior.
Hints/policy ablations are not claimed by this diagnostic CLI.

Failure/cancellation attempts bounded cleanup of that trajectory's operation.
Successful exit preserves a useful in-flight restore. A timeout retains an
ambiguous owner's slot; it does not prove physical reclamation. The CLI stops
before further tasks if cleanup remains uncertain. Post-generation control
settlement is outside `full_task_ms` and has its own finalization timestamp.

## What must happen before a performance comparison

The diagnostic leaves cache state and physical I/O explicitly `UNMEASURED`.
It does not force an L3-only condition or calculate hidden restore from SDK
timestamps. A pair of diagnostic invocations is not a controlled benchmark.
Model-selected calls/outputs must first be validated on the actual GPU runtime.

An initial instrumentation audit found that the historical probe calls
`cache.match_prefix()`. In candidate runtime `3e60ad8`, Python TreeCore's
`_match_post_processor()` updates ancestor `last_access_time`; partial matching
may split nodes. The probe therefore cannot be treated as passive observation
during eviction research. Do not use it unchanged in the pressure experiment.
Its earlier controlled-flush datasets retain their original methodology.

The [passive observer and competing-arrival workload](PASSIVE_PRESSURE_PREPARATION.md)
are now implemented and CPU checked. They retain the same runtime/source identity
and keep GPU fit/performance unvalidated. Next perform a separately approved non-Qwen
compatibility pilot and persistent-worker pressure comparison without per-target
flush/restart. Measure opportunities, physical I/O, occupancy, evictions, waste,
all-caller latency and task quality. These steps complete the research objective;
this local foundation alone does not.
