# Harness 0.9.12 — workflow enforcement over accepted earlier outputs

Workflow agent steps can bind enforcement tags to trusted Runtime Guards.
`Workflow.load(guards=...)` and native `WorkflowBindings(guards=...)` plus
`WorkflowPolicy.allowed_guards` admit explicit host permissions. Guards inspect
only the original request and declared fresh accepted dependency outputs through
`GuardContext.input_data['workflow']`. Required floors and all four hook phases
remain Runtime-owned. `Harness.capabilities` advertises `workflow_rules_v1`.

The source archive adds `examples/workflow-enforcement`: a content-versioned
flagged-or-changed final review Guard, YAML/native construction, bounded repair
and explicit human acceptance. Existing Validator V1 resources remain unchanged.
Runtime0.9.16 and Core0.5.0 are reused; no new Core/Runtime or adapter release.
The Runtime dependency floor advances to>=0.9.16,<0.10. Store0.4.1 remains an
unchanged qualification witness and is not republished.

Guarded steps require explicit finite request/tool caps. max_calls still counts
Harness invocations. Rule repair shares existing budgets; no separate allowance
is inferred. Exhausted/faulted/failed rules block with rule_violation without an
outer Harness retry. Acquisition, terminal tools, args interpolation and required
file-read receipts are unsupported on guarded steps and refuse before effects;
existing untagged paths retain their contracts. See [API contract](workflow-rules.md).

**Identity/readmission:** guarded workflows seal complete used Guard declarations,
compiled rule material, logical project and workflow-guard-input-v1 fact profile.
Bundles also seal full registered host material. Empty additions/unused guard
registrations preserve released untagged workflow/default policy/bundle identity.
Changed used declarations require readmission/new runs; existing schema versions
remain unchanged. Receipts add bounded fact/context hashes and IDs-only rule proof;
missing or mismatched proof cannot advance. Saved receipts replay without calls;
uncertain calls still require explicit consent and complete budget evidence.

Qualification must pass complete source/installed-wheel cases, both synthetic
provider wires, real PostgreSQL16/18, OS/Python and dependency floors. Release
promotion uses original qualified bytes from the exact merged source and verified
Core/Runtime lineage, followed by public-byte/fresh-consumer checks. Local source
runs without a disposable database skip five PG lifecycle cases; hosted required
PG lanes must pass rather than skip. No live-provider certification is claimed.
