# Prosaic Harness 0.6.2

Adds `WorkflowCatalog`, `WorkflowBindings`, `WorkflowPolicy` and
`WorkflowFactory` for validated in-memory workflows. Proposed graphs use logical
references; the host owns Runtime configuration, credentials, tool callbacks,
validators and policy. No client `base_dir` is required. Composition of approved
agents and introducing inline instructions have independent permissions.

Admission snapshots inputs and checks canonical artifacts, graph semantics,
schemas, routing, grants and bounds without invoking models or callbacks.
Execution verifies admission and bindings again. Native proposals cannot
introduce filesystem/CLI access or physical resource bindings. Human decisions,
durable failure receipts and reconstruction across workers retain checkpoint
version 2 and receipt version 1. Historical YAML workflows remain supported.

Pins Runtime 0.7.1 at `6ac8768de3dd69abdbbfbe6f15107a0504762691`, which
pins Core 0.3.2 at `af7d90e178f61d53ba71bcc61c41c3ef7f941b4c`.
The separately installed PostgreSQL store remains 0.1.1.

Local qualification passed 337 Harness tests, minimum Python 3.11/schema
dependencies, PostgreSQL 16/18 selected native/store/recovery checks (24 each)
and clean installed-wheel smoke on Python 3.11/3.12. Source archives include the
documented smoke script. The release requires all five final-commit CI jobs:
Linux Python 3.11/3.12/3.13 and the complete 85-case owned PostgreSQL 16/18
matrix, including crash/standby and clean-wheel gates with zero skips.
The published verification asset records exact native results, source commits
and checksums of downloaded distributions.

Install from the immutable GitHub tag or release assets. GitHub distributes the
Core and adapter wheels/source archives; no npm or PyPI publication is involved.
See [the API guide](workflow-factory.md) and [initial verification boundaries](workflow-factory-verification.md).
Host callbacks and schema CPU remain cooperative, token budgets can overshoot
within an invocation, and remote completion before receipt commit retains its
explicit retry-consent boundary. These releases do not certify a production
deployment or external provider.
