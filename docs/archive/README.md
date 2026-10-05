# Historical records

These records retain the scope, configuration and outcome of their original
checks. They are evidence and design history. Current work and acceptance
criteria live only in [WORK_TRACKER](../WORK_TRACKER.md).

| Directory | Contents |
|---|---|
| `evidence/` | Recorded checks, GPU smoke results, failed pilots and reviews |
| `plans/` | Superseded research/preparation snapshots and their command recipes |
| `releases/` | Release notes and announcement drafts |

## Evidence by milestone

- [Stage 2A correctness](evidence/STAGE_2A.md),
  [v0.1 synthetic benchmark](evidence/STAGE_2B.md),
  [v0.1 release review](evidence/REVIEW.md).
- [v0.2 real tool loop and resident control](evidence/TOOL_LOOP_VALIDATION.md),
  [fresh-main compatibility smoke](evidence/UPSTREAM_SMOKE.md).
- [v0.3 local integration checks](evidence/MULTI_SESSION_VALIDATION.md),
  [two-caller GPU smoke](evidence/MULTI_SESSION_GPU_SMOKE.md),
  [CLI](evidence/CLI_VALIDATION.md),
  [reconciliation](evidence/RECONCILIATION_VALIDATION.md),
  [admission policy](evidence/ADMISSION_POLICY_VALIDATION.md).
- [Failed Mistral live pilot](evidence/MISTRAL_PILOT_2026-10-05.md),
  [integration architecture review](evidence/ENGINEERING_REVIEW_2026-10-05.md).
- [Local integration/preparation checkpoint history](evidence/LOCAL_CHECKPOINTS_2026-10-05.md)
  preserves the dated sections formerly embedded in the active tracker.

Preparation history: [research design](plans/RESEARCH_PLAN.md),
[cross-family CPU harness](plans/CROSS_FAMILY_PREPARATION.md),
[passive observation and pressure workload](plans/PASSIVE_PRESSURE_PREPARATION.md).
Recipes in these snapshots remain subject to their pins and known failed gate;
they are not evidence that the current harness is ready for another paid run.

Release history: [v0.2](releases/RELEASE_v0.2.0.md),
[v0.3](releases/RELEASE_v0.3.0.md),
[v0.2 announcement draft](releases/ANNOUNCEMENT_v0.2.0.md).

Raw benchmark data remain in `results/`; the published
[technical report](../report/README.md) keeps its original source/PDF and hashes.
Historical repository paths in that manuscript refer to its release snapshot.
