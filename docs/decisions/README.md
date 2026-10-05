# Architectural decisions

| ID | Date | Status | Decision |
|---|---|---|---|
| [ADR-0001](0001-agent-integration-contract.md) | 2026-10-05 | Accepted; local contract implemented | Separate model formatting, agent execution, and exact-prefix cache control |
| [ADR-0002](0002-evidence-and-experiment-readiness.md) | 2026-10-05 | Accepted; local gates implemented | Separate local conformance, live behavior, and performance evidence |

Existing decisions about local admission and cleanup remain in
[admission policy](admission-policy.md) and
[RECONCILIATION.md](../guides/RECONCILIATION.md). This index does not retroactively claim
that formal ADRs existed when those features were implemented.

For a material choice, add a numbered record with context, evidence, alternatives,
decision, consequences, and verification. Supersede an old decision explicitly
rather than silently rewriting its rationale. Record unknowns and the task that
will resolve them. A proposal is not an implementation or an experiment approval.
