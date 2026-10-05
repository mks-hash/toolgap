# Agent study: local readiness and evidence gates

The active plan is [WORK_TRACKER](../WORK_TRACKER.md). This guide describes
commands; it does not authorize a GPU session, launch a server or select a new
model. The current Mistral live pilot remains 0/3; pressure has not run.

Use a reviewed pinned profile and its cached tokenizer. Commands below run from
the repository root. Every output path must be new. Keep raw runs in ignored
`work/`; sanitize summaries before public inclusion.

## Prepare locally

```bash
export PYTHONPATH="$PWD/src:$PWD"
python -m research.agent_resume.pressure prepare \
  --profile "$PROFILE_FILE" --tokenizer "$TOKENIZER_DIR" \
  --output work/study/packet.json
python - <<'PY'
import json
from pathlib import Path
p = json.loads(Path('work/study/packet.json').read_text())['packet']['profile']
Path('work/study/profile.json').write_text(json.dumps(p, indent=2))
PY
python -m research.agent_resume.native_conformance \
  --profile work/study/profile.json --tokenizer "$TOKENIZER_DIR" \
  --output work/study/native.json
python -m research.agent_resume.check_pressure \
  --packet work/study/packet.json --tokenizer "$TOKENIZER_DIR" \
  --output work/study/scripted.json
```

The packet uses 4 maximum running server requests, 1 GB configured host pool,
12 fixed arrivals by default and at most 8 active clients. It includes exact
initial token IDs over pinned public source, not artificial filler or a tool
sleep. The scripted check runs real fixed repository tools with fabricated
model decisions. It cannot satisfy the useful-live gate.

Generate native evidence for the **packet profile**, not the original diagnostic
profile: changed resource settings change its fingerprint. Native reference
checks cover two canonical tool rounds and reference agreement; they do not
establish whether a model generates valid calls. The pinned Mistral no-ID native
call remains semantic-valid but unsupported for its HF continuation history.

## File storage and an existing approved server

Before starting the reviewed server, claim a new isolated directory:

```bash
python -m research.agent_resume.readiness \
  --profile work/study/profile.json --storage-parent "$L3_PARENT"
# Use the printed absolute directory as SGLANG_HICACHE_FILE_BACKEND_STORAGE_DIR.
```

Use a canonical absolute directory path. Do not reuse another profile's directory. Keep the generated identity file.
The namespace binds declared weights/revision, tokenizer, runtime, precision and
settings. Deployment JSON must include `storage_path`, `clock_domain` (Linux
boot ID plus time-namespace identity), model/revision/model_path, runtime_sha, resolved_cache_mode=`FULL`,
and the actual `pressure_match_observation` toggle. The private plugin mailbox
must be mounted on the same host and named by `TOOLGAP_PRESSURE_PROBE_DIR`.
Use the existing research plugin/trace setup from the archived
[preparation](../archive/plans/PASSIVE_PRESSURE_PREPARATION.md); its older CLI
recipes are superseded by this guide.

The preflight probes metadata only. It checks the actual imported clean runtime
checkout, file directory, page size, host layout and KV storage dtype before
`/generate` or prefetch. Server package versions and relevant runtime source
hashes are retained. This is **not weight attestation**; fixed weights and no
hot swap remain study requirements. A packaged runtime without an inspectable
matching Git checkout fails closed in this study harness.

Pressure enforces cold whole-worker initialization: empty device/host KV, no
in-flight work and an empty claimed file directory. Restart/reset the whole
worker and use a fresh claimed directory between the useful diagnostic and
measured blocks. Do not flush/evict a target inside a measured tool gap. A
treatment checks observed capacities/layout/dtype/threshold against its baseline.
Freeze equal kernel/model warmup outside the measured blocks and validate the
cold-start procedure on the real server before interpreting performance. Empty
KV alone does not prove equal JIT/filesystem warmth.

## Live gate, then baseline — only with applicable execution approval

```bash
python -m research.agent_resume.live \
  --profile work/study/profile.json --tokenizer "$TOKENIZER_DIR" \
  --native-evidence work/study/native.json --deployment "$DEPLOYMENT_JSON" \
  --server "$SERVER_URL" --probe-dir "$PROBE_DIR" \
  --mode request_time --output work/study/live
# Proceed only if readiness.json records study_success=true.
python -m research.agent_resume.pressure run \
  --packet work/study/packet.json --tokenizer "$TOKENIZER_DIR" \
  --native-evidence work/study/native.json --live-evidence work/study/live \
  --deployment "$DEPLOYMENT_JSON" --server "$SERVER_URL" \
  --probe-dir "$PROBE_DIR" --observation memory-and-stat \
  --mode request_time --output work/study/baseline
# Retain the dedicated raw server trace as baseline/server-trace.jsonl.
python -m research.agent_resume.trace_report \
  --block work/study/baseline --trace work/study/baseline/server-trace.jsonl \
  --output work/study/baseline/trace-report.json
```

`readiness.json` separates procedure completion from useful study success.
Failed tasks stay in the denominator. Pressure rejects missing/stale native or
live evidence before HTTP effects; it binds the exact profile, harness/SDK source
hashes, packages and raw artifacts. Live checks do not promote resource fit,
pressure or performance to PASS.

A proactive feasibility block additionally requires `--baseline` and the same
packet/instrumentation, bound raw trace, quality/cleanup success and observed
natural L3 candidates. Missing opportunities stop this path. The gate labels it
an **exploratory whole-worker comparison**, with dispatch reachability UNKNOWN;
it cannot establish statistical performance or matched initialization by itself.
Counterbalance block order and retain all callers. No automatic retry or delayed
prefetch/resubmission policy is introduced.

## What the samples mean

The frozen budget is 100 ms intervals, at most 8 samples per tool round, 50 ms
per sample. Tools and continuation requests never await samples. An initial
request, periodic requests and a continuation-boundary request run in the
background; cleanup reaps client tasks after the trajectory timing ends. A
cancelled request already read by the scheduler may leave a late private mailbox
reply; the nonce is never reused. Client task cleanup is not a claim about
operation-specific KV consumption or completion of all server file writes.

Each sample records requested/returned time, server read/observation times,
boot/time-namespace clock domain, page-aligned residency and optional direct file stat. File presence
is only a candidate: a nonresident available span meeting the observed cache/controller prefetch
threshold is reported (256 tokens in the default pinned runtime),
not successful reads, publication or consumption. Late, missing, invalid and
cross-clock samples remain UNKNOWN. A sample crossing continuation arrival is
excluded from pre-arrival opportunity summaries. Samples after tool completion
cannot establish overlap with useful tool work. Sparse negative samples do not
prove that no opportunity existed between them.

A background sample cannot establish cache state exactly at dispatch.
`dispatch_state=UNKNOWN` is intentional. Transitions have interval bounds and
observed remaining tool/continuation windows. The once-at-dispatch prefetch may
miss later eviction after a terminal CACHED response; do not condition the
whole-worker result on treatment-induced cache state.

Client observer wait is not active CPU cost or imposed tool delay. Probe cost
and full mailbox-service duration are recorded separately; service duration
excludes its trace write. Net contention/perturbation still needs matched live
observation-on/off calibration: use the same request-time packet on cold workers,
with `--observation off` and `--observation memory-and-stat`, counterbalance
order and retain quality failures. Set the matching server toggle in each
deployment. A small calibration is descriptive feasibility evidence. Operation-specific consumption and wasted bytes
remain null when unproved. Primary endpoint: successful tasks per block second,
subject to all-caller quality/cleanup and an explicit competing-caller degradation
limit. Caller-level samples are not independent worker repetitions.
