# ADR-0003: bounded repository discovery and source-backed tool evidence

Date: 2026-10-05. Status: accepted; local implementation and checks completed.
Live useful-task behavior remains unverified after this change.

## Context

The [Qwen7 pilot](../../research/agent_resume/qwen7-live-pilot-2026-10-05.json)
made eight real tool calls and preserved eight actual continuation prefixes,
but passed 0/3 tasks. Seven natural-language queries produced no literal line
matches. The regression suite passed, but its result supplied no source
locations; the final answer invented a test path. Local replay reproduced the
empty searches and confirmed that all required answer sources exist.

This is a repository-tool usability problem before cache-pressure measurement.
It does not establish that Qwen7 is incapable of completing these tasks, or
that prefetch lacks useful pressure opportunities. The unsupported mixed
prose/tool response is a separate declared adapter limitation and remains so.

## Decision

Keep the existing model/runner/cache-control boundaries. Change only the
research repository tools and their generic instructions:

- `search_repository(query)` returns at most 20 numbered lines. Literal
  matches rank first; other lines rank by inverse-frequency-weighted overlap
  of query words, with deterministic path/line ties. Split snake/camel case
  identifiers, remove a fixed generic stopword list, and declare the method.
  No embeddings, synonym expansion, task-specific aliases or answer lookup.
  Build the search index lazily inside the first timed search.
- `list_repository(prefix, offset)` returns at most 40 pinned file paths with
  line counts and hashes, plus a continuation offset. It reads the same Git
  snapshot as search/read; it does not expose arbitrary filesystem paths.
  File metadata is discovery, not evidence sufficient for grading.
- `run_regression(suite)` retains actual execution/exit/test-count evidence and
  returns bounded numbered test-class declarations from the test source it
  actually runs. Locations come from parsing the pinned file, not task answers
  or generated claims. A failed test run cannot produce a successful task merely
  because its source lines are available.
- Final citations still require actual returned source lines from search,
  read, or regression, the correct answer, and any required successful tool.
  Do not lower the grader's requirements, drop failed outcomes, change saved
  IDs, accept unsupported output, or increase the four-tool-round limit.

Tool contract v2 binds the schema, executor and runner/prompt source hashes into
the existing measurement contract. Old packets fail before live evidence/HTTP
or tool execution. New tokenized packets and native evidence are mandatory;
the old pilot archive and its 0/3 result remain intact.

## Alternatives

Changing the grader, supplying expected answers in the prompt, increasing tool
rounds, or repairing model-specific output would hide the failed workflow.
Replacing native generation with a prescribed call sequence would be a scripted
fixture rather than the useful live gate. A semantic-search service or a generic
agent framework adds unnecessary infrastructure for this bounded source corpus.

## Consequences and verification

Retrieval can return relevant lines even when the query is not an exact phrase;
it can also return irrelevant lexical matches. It does not promise semantic
understanding or successful agent decisions. The original-corpus replay checks
seven retained queries; separate inventory-domain fixtures check identifiers,
literal priority, deterministic bounds, pagination, and no synonym expansion.
Listing-only and fabricated citations remain rejected. A real CPU regression
run supplies the actual test-class evidence. A stale-packet fixture stops before
live operations; native-tokenizer checks verify two actual template suffixes.

The search index's construction and new result/prompt sizes can change tool
duration and token demand. They must be measured as the new workload in both
arms; no historical latency or GPU pressure claim is reused. Results and next
acceptance checks live in [WORK_TRACKER](../WORK_TRACKER.md). CPU/scripted checks
do not complete TG-008, observer calibration, or the pressure comparison, and
do not authorize another GPU session.
