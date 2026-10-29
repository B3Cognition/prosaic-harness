# Harness 0.9.5

Adds model-free `kind: tool` workflow steps using Runtime 0.9.9 `direct_tool_v1`.
Direct tools require a separate host-owned grant and retain schema/validator,
receipt, call-count and effect boundaries. Invalid output is not automatically
replayed. See [direct-tool-step.md](direct-tool-step.md).

Adds explicit `initial_tool` selection for a host-admitted mandatory first native
tool. Existing bounded-recovery rules may repair a proven zero-effect refusal;
interrupted or uncertain work is not eligible for replay. See
[initial-tool-step.md](initial-tool-step.md).

Release qualification binds the exact Runtime 0.9.9 candidate and Core 0.4.1
candidate. PostgreSQL adapter 0.4.1 remains a compatibility witness, not a new
adapter publication. Existing workflow semantics and authority boundaries remain
unchanged unless the new capabilities are explicitly requested and admitted.
