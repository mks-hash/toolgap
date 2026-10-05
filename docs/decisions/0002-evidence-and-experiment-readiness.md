# ADR-0002: separate conformance, live behavior, and performance readiness

Date: 2026-10-05. Status: **accepted**; local machine-readable enforcement implemented in TG-005/TG-006; live applicability remains unverified.

## Context

The repository already labeled scripted CPU checks as scripted and retained
failures. Nevertheless, their successful result was operationally treated as
sufficient model-integration readiness. The Mistral pilot exposed a contract
assumption that should have been reviewed locally. Its orchestrator finished
normally after a failed gate, so process exit and study success also differed.

## Decision

Use independent evidence dimensions rather than one `supported` or `passed`
flag. Every record names model revision, tokenizer/template hashes, runtime,
adapter/runner/workload configuration, validation type and actual checks.

| Dimension | Local proof | Proof requiring actual model/runtime work |
|---|---|---|
| Tool schema and adapter contract | Reference/recorded conformance fixtures and unsupported-input cases | Does not prove model chooses valid calls |
| Exact-prefix continuation | Native tokenizer, independently valid calls/results, multi-round token checks | Real generated IDs and tool-result continuation |
| Transport | Stream fixtures, finish/error/cancellation handling | Actual server generation |
| Resource fit | Config-derived estimate and local setup | Loaded model and resolved pools on target GPU |
| Useful agent loop | Runner/tool/grader plumbing fixtures | Model-selected calls, executed tools, continuation, correct final answer |
| Natural restore opportunities | Observer purity and trace schema tests | Useful workload pressure, observed state and request-time restore |
| Performance | Defined metrics, frozen comparison and reporting code | Quality-preserving paired whole-worker runs with all callers retained |

Statuses are `PASS`, `FAIL`, `NOT_RUN`, `UNKNOWN` or `UNSUPPORTED`, with reasons
and evidence references. No implicit promotion between dimensions. Not run is
not zero failures or zero opportunities. Unknown consumption/waste is not zero.
A procedure's clean shutdown/exit is recorded separately from workload success.

Before paid execution, locally review adapter/source references, unsupported
cases, result serialization, fit estimate, commands and all failure accounting.
Explicitly state that live behavior remains unverified. A first live pilot is
legitimate for learning model behavior after these checks; it cannot be replaced
by scripted output. The user authorizes the specific session and its budget.

Live compatibility must pass before pressure evaluation. Baseline quality,
instrumentation and cleanup must pass before a performance comparison. Missing
natural opportunities stops that comparison with an honest feasibility result.
Repeated GPU execution is not implicitly authorized by failure or a local fix.

### Time-dependent opportunities and causal claims

The existing proactive API ends immediately with `CACHED` when its requested
prefix is resident; the runner submits at dispatch and does not automatically
resubmit after later eviction. Therefore a prefix found in L3 at continuation
is not sufficient evidence that the dispatch policy could have hidden its read.
Baseline observation must distinguish eligibility at dispatch, eligibility
arising during the tool gap, and eligibility first seen at continuation. Record
page-aligned spans, storage availability, observed remaining tool window and
missing samples. Bounded sampling yields interval-censored transitions, not
exact eviction timestamps. Successful reads and consumed KV need their own
evidence; file presence alone proves neither.

Sampling must not use mutating cache matching, submit prefetch or synchronously
delay useful tools/continuations to create an overlap window. Measure its cost
and use the same instrumentation in both arms. A future delayed/progress trigger
is a separate treatment; no implementation is authorized by this decision.

Report three estimands separately: baseline opportunity prevalence, conditional
continuation benefit and unconditional whole-worker outcome. Do not condition
the aggregate comparison on treatment-induced cache state or discard failures.
Select the primary endpoint, acceptable competing-caller degradation and stop
rules before paid comparison. Randomize/counterbalance whole-worker blocks;
shared callers are not independent repeats. Report sample size and uncertainty,
without tail-latency or significance claims from a tiny feasibility pilot.

An absent opportunity is a result for the declared workload/resource point.
A later change in model size, cache capacity or concurrency is a separately
declared experiment, not grounds for silently forcing eviction or selecting
only favorable runs. Exact target-by-target improvement is not promised;
quality and competing-caller effects must both be reported.

## Data and ownership

Keep immutable run manifests/raw outcomes and exact token IDs; add a versioned
sanitized summary for repository navigation. Include negative outcomes, checksums,
experimental units and completion/stop reasons. Raw private evidence remains
private; summaries state its access status. Keep personal host paths and secrets
out of public-ready artifacts. A dirty checkout needs an explicit changed-file
manifest, or use a clean pinned checkout; HEAD alone does not identify its code.

The work tracker links a decision, implementation and evidence. Historical
benchmarks retain their original scope and pins. A new profile's smoke cannot
replace their performance data, and an old benchmark cannot validate a new
profile.

Keep a small versioned JSON/JSONL evidence package as the canonical source;
Parquet is an optional derived export, not a new prerequisite. Include pinned
tool dataset/grader, parser/template options, storage namespace, clock domains,
arrival trace and evidence-access status. Reusing libraries does not remove our
responsibility for exact-token identity and experimental semantics.

## Alternatives and consequences

A single green preflight flag is simpler but hides which claims it proves.
Running all behavior checks locally with fabricated model outputs is cheaper
but cannot establish actual tool selection. Exhaustive GPU model sweeps are not
needed before a bounded experimental release or a corrected compatibility pilot.

These distinctions add a small manifest/reporting obligation, not new deployment
infrastructure. TG-005/TG-006 implement the checks and status schema. The decision
does not imply any pending GPU pilot has passed.

## Local enforcement checkpoint

[Readiness](../../research/agent_resume/readiness.py) now binds profile,
harness/SDK sources, packages and raw artifacts. Native and useful-live results
are checked by the live/pressure consumers before inference/control effects.
The file namespace is claimed once for the full profile; the existing private
mailbox observes actual runtime checkout/source/packages, namespace and KV
layout. Weight identity stays declared; inspectable matching clean runtime is
required. [Tests](../../tests/test_readiness_sampling.py) include rejecting
scripted/stale evidence and mismatched/unknown namespace/runtime/layout.

[Sampling](../../research/agent_resume/sampling.py) requests observations in the
background with a frozen budget. It records observed time, not an invented
exact-dispatch state. Late/cross-clock/missing observations stay UNKNOWN;
eligibility after the tool finishes cannot establish tool overlap. The
whole-worker feasibility endpoint is frozen in the packet. Gate acceptance
means a baseline has observed candidates, not that the dispatch policy can
reach every later window or that performance is established. An unconditional
exploratory comparison may legitimately show that this trigger misses them.

Cold whole-worker start is enforced before pressure: empty device/host/file KV
and no in-flight work. Actual resolved capacities and layout must match the
baseline before treatment generation. The
[tracker](../WORK_TRACKER.md) records pending real-server validation of this
initialization, matched kernel/model warmup and live net-instrumentation
calibration. The
[guide](../guides/AGENT_STUDY.md) supersedes archived CLI commands. This checkpoint
does not change the 0/3 pilot result or authorize another GPU execution.
