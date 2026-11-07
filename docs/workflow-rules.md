# Workflow enforcement contract — workflow_rules_v1

`Harness.capabilities` advertises `workflow_rules_v1`. Core parses inert tags,
Runtime executes Guards, and Harness owns graph admission, dependency freshness,
invocation receipts and acceptance. Domain predicates belong to trusted hosts.

Bind trusted Python Guards with `Workflow.load(path, guards=[...])` or
`WorkflowBindings(config=..., guards=[...], rule_project=absolute_root,
rule_project_identity='logical-v1')`. A native host also grants names through
`WorkflowPolicy(allowed_guards={...})`. A project is optional without path settings;
when present it requires an absolute root and bounded logical identity. Native
admission compiles public Runtime rule material without constructing Runtime,
calling Guards, inspecting a CLI or invoking models. Host registrations are owned
snapshots. Duplicate, malformed, unsupported or unregistered tags refuse.
Runtime required_guard floors cannot be removed or weakened by a workflow.

A rule-bearing agent requires both finite nonnegative request/tool invocation
caps. YAML supplies `limits.max_provider_requests_per_invocation` and
`max_tool_calls_per_invocation`; native hosts provide the corresponding
WorkflowPolicy fields. Proposals can lower explicit host caps, never create or
raise them. `max_calls` remains the workflow invocation limit. Runtime repair
shares those existing limits; this adds no independent repair allowance.

Before dispatch, Harness prepares `inputData.workflow` with fixed version1 and
step name plus the existing arguments projection. Request data stays nested;
artifacts and artifact_bindings include only declared accepted required/optional
outputs. Present stale optional inputs refuse just like required ones. Missing
optional outputs are omitted. Runtime gives each Guard a private JSON view.
The exact turn and required evidence capacity are admitted before pending/call
allocation. Existing schema and versioned Validator acceptance stays mandatory.

Only standard ProsaicRuntime guarded API turns are supported. Injected Runtime
config, guard versions/full declarations, compiled material and actual confined
paths must match admission. Acquisition, terminal tools, argument interpolation
and required file-read receipts refuse before effects. Runtime's public turn
callback has no read-receipt proof; the untagged read path stays supported.
Custom-tool completion events are paired with their already-readmitted sealed
registration version. All four guard phases remain Runtime-owned.

Receipt/checkpoint schema versions remain1/2. Result metadata adds the closed
`workflow_rules_v1` map: version1, facts_sha256, context_identity and the existing
IDs-only rule map. Adoption checks shapes, fact hash, pending/step identity,
sealed rules fingerprint and evaluated/outcome subsets. Successful answer rules
must be evaluated. Missing/invalid proof never advances. Bounded failure fallbacks
retain this proof and safely known usage. Rule failures block with stable
`rule_violation` and do not receive another Harness retry. Ordinary schema and
Validator retries keep their explicit existing max_attempts behavior.

**Identity:** used guard name/version/stages/settingsSchema/pathSettings/fixes/
echoValues, compiled rule bindings, logical project and fact profile
`workflow-guard-input-v1` enter guarded workflow identity. Explicit caps and
nonempty allowed_guards enter native host policy as appropriate. Bundles seal
the full host registry/project. Empty additions and unused registrations add no
workflow fields, so released untagged workflow/policy/bundle goldens stay exact.
Callbacks are trusted executable bindings, not serialized; hosts must content-
version their implementations. Runtime artifact digests/rules fingerprints retain
their existing definitions. Readmit changed used declarations; do not migrate a
pending run silently. A portable project may move only with the same logical
identity and newly verified confined effective paths.

Saved success/refusal receipts replay without effects. A lost receipt remains
uncertain and requires explicit interrupted retry consent; token caps can still
block unknown usage. Accounting attribution remains frozen and never grants
retry consent. See [copyable V2 example](../examples/workflow-enforcement/README.md).
