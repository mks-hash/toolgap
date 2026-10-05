# Documentation

| Purpose | Entry point |
|---|---|
| Product, results and quick start | [Repository README](../README.md) |
| Current objective, tasks and acceptance criteria | [WORK_TRACKER](WORK_TRACKER.md) |
| Installation and GPU reproduction | [Reproduce](guides/REPRODUCE.md) |
| Cache-control API and CLI | [API](guides/API.md), [CLI](guides/CLI.md) |
| Real tool-loop integration | [Tool loop](guides/TOOL_LOOP.md) |
| Multiple callers and local reconciliation | [Integration](guides/MULTI_SESSION.md), [demo](guides/MULTI_SESSION_DEMO.md), [reconciliation](guides/RECONCILIATION.md) |
| Agent study readiness and measurement commands | [Agent study](guides/AGENT_STUDY.md) |
| Architecture and policy decisions | [Decision index](decisions/README.md) |
| Historical checks, preparation and releases | [Archive](archive/README.md) |
| Published technical report, source and audit | [Report](report/README.md) |

`WORK_TRACKER.md` is the **only active task/roadmap record**. Archived plans
explain past preparation; their TODOs and proposed runs are not current orders.

Keep user instructions in `guides/`, material decisions in `decisions/`, and
dated validation/experiment/release records in `archive/`. Routine fixes update
the existing task/decision with tests and evidence; they do not need a new report.
Create a dated evidence record only for a substantive experiment, review or release.

Historical measurements retain their original pins and scope. CPU fixtures,
native-tokenizer conformance, actual generation, useful tool-loop success and
performance are different evidence. Keep failures; unknown is not zero.

Public-ready files use relative paths and sanitized evidence. Private raw logs
stay private; summaries state their access status. Documentation does not
authorize paid execution or publication.
