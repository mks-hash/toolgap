# Working in ToolGap

Read `docs/README.md`, `docs/WORK_TRACKER.md`, and relevant records in
`docs/decisions/` before continuing project work. Update the tracker when an
acceptance check completes, a blocker appears or scope changes. Store material
architecture choices in numbered decision records with evidence and alternatives.

`docs/WORK_TRACKER.md` is the only active task/roadmap record. User instructions
live in `docs/guides/`; dated checks/releases and superseded plans live in
`docs/archive/`. Archived TODOs are history, not current orders. Routine fixes
update existing tasks/decisions and link tests; do not create a report per fix.

The current objective is useful agent latency/quality under natural cache
pressure. Local contract work enables that study; passing fixtures and additional
SDK features alone do not complete the product objective.

Keep model formatting, tool execution and exact-prefix cache control separate.
Preserve actual saved token IDs and salt; do not repair a model response by
rewriting its cached prefix, dropping trailing output or inventing tool success.
Use pinned template/profile conformance and explicit unsupported outcomes.
Validate static continuation capability before tool/control effects, then actual
result serialization and token budget after tool completion.

Label CPU fixtures, native-tokenizer checks, live inference, useful tool-loop
correctness and performance evidence separately. Keep failed/cancelled callers.
Not run is not pass; unknown consumption/waste is not zero. Keep published
historical datasets/pins unchanged and link new evidence to its actual code/config.

Honor the user's current authorization. Local review does not authorize another
GPU session, image/runtime architecture change, public push, PR or release.
Existing authorization for an action remains valid within its stated scope;
do not invent additional approval gates. Paid runs need explicit applicable
session/time/cost constraints and automatic cleanup. Stop paid exploratory
debugging at the user's limit and continue locally.

Do not add personal host paths, credentials, private cloud metadata or
unsanitized logs to tracked files. Use relative paths and sanitized summaries;
identify privately retained raw evidence by hash and access status. Preserve
unrelated user files. The SDK and runtime research patches remain distinct from
the lifecycle bugfix and upstream feature PRs.
