# ADR-0005: bounded tool evidence and separate diagnostic observation

Date: 2026-10-06. Status: accepted; implementation in progress.

## Context

The packet-bound Qwen7 pilot at `b6b42e4` preserved 10/10 actual continuation
prefixes but passed 0/3 useful repository tasks. Two real result suffixes needed
8236 and 8058 input tokens against 7936 available; a third answer cited invalid
evidence. The guard rejected them correctly. Scripted preflight used privileged
answer/line knowledge and did not cover cumulative natural searches and reads.
A blanket useful-task gate also prevented any diagnostic cache observation.
See [retained pilot](../../research/agent_resume/qwen7-packet-pilot-2026-10-05.json).

## Decision

- Keep the runtime/SDK and exact saved input/generated IDs unchanged. Account
  for the actual native-template suffix and output reservation at the tool
  boundary. Return bounded complete evidence units (paragraphs/table rows/source lines), explicit partial status and
  a resume cursor; never slice a cached prefix or fabricate tool success. If no
  evidence can fit, classify `INSUFFICIENT_EVIDENCE` and retain the trajectory.
- Use the same fixed result-page cap and stopping policy in both treatments.
  Record raw versus delivered result identity, cursor and actual token counts.
  A changed tool response changes subsequent model input; old later responses
  cannot attest useful live behavior under that counterfactual.
- Make faithful replay of recorded real failures a CPU regression corpus.
  Expected failure is a valid replay outcome. Distinguish it from counterfactual
  budgeted-output tests and from scripted/model-generated evidence.
- Document search is the primary pressure workload; repository audit remains a
  stress workload with unchanged historical results and strict original grading.
  Reuse the v0.2 lexical executor. Its default corpus is synthetic: new real-document
  evidence must identify pinned sources instead of inheriting a claim of realism.
- Permit technically valid diagnostic baseline observations independently of
  task success, retaining every declared caller and its quality/censoring status.
  A diagnostic run cannot authorize proactive evidence comparison or a headline.
  Evidence comparison retains the existing strict quality, provenance, resource,
  instrumentation, cleanup and opportunity checks until another policy is
  explicitly predeclared and reviewed. Invalid prefixes or unsafe cleanup stop.
- One locally prepared campaign may run compatibility, concurrent baseline,
  opportunity observation and a conditional matched comparison in one VM session.
  Separate the questions and their evidence. Model/server reset requirements
  must remain symmetric; a single model load is an optimization, not a validity
  condition. No model registry or general pagination framework is required.

This supersedes ADR-0004's blanket useful-live requirement **only for explicit
request-time diagnostic observation**. Evidence mode keeps that requirement.
It does not authorize GPU execution, weaken historical graders or promote
recorded/scripted outputs to useful-live evidence.

## Alternatives and limitations

Raising context/round limits, silent history trimming, providing expected
answers to a live model, or weakening citations would hide the failures.
Requiring all possible malformed outputs or a new model's own recorded corpus
before its first inference creates unnecessary barriers. CPU checks cannot
prove new model decisions, natural cache residency or performance.

Zero observed opportunities describes the declared sampled workload/resource
point; it does not locate a different bottleneck or establish global absence.
Shared callers are not independent repetitions. Observer sensitivity screening
is not statistical equivalence. Publication is not consumption; unknown waste
remains unknown.

## Verification

Local acceptance: exact native suffix accounting; pre-effect minimum-response
fit; bounded evidence/cursor correctness; no fabricated success; independent
quality and diagnostics; faithful replay of retained outputs including expected
budget/citation failures. Use pinned official tokenizers for native checks.
Keep raw cloud data private. Record checks in the existing tracker and sanitized
research evidence; no GPU or runtime change is part of this implementation.
