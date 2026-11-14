# Harness 0.9.19 — guarded-turn recovery

Trusted hosts can pass `rule_retries` (0–3, default 1) and
`correct_malformed_tool_calls` (default false) to `WorkflowBindings`,
`Workflow.load`, or `ConversationBindings`. Runtime handles retries and
correction inside the original turn, including its existing request, token and
time limits. In workflows the settings apply to role-aware turns, including
guarded steps, context packs and tool-contract steps.

Non-default values enter workflow, bundle and conversation identity. Resume
requires the same host settings. Omitted and explicit default values have the
same identity as previous releases. Harness checks that an injected
`ProsaicRuntime` agrees with the declared options. Custom adapters support the
default policy.

Recovery outcomes are stored only when observed. Workflow invocation metadata
uses `guarded_recovery_v1`; private conversation receipts use
`guardedRecoveryV1`. Each version 1 record contains `ruleRetriesUsed`,
`rulesDeclined`, `rulesRetried` and `toolRequestCorrections`. These fields
describe Runtime's recovery decisions. Use tool delivery evidence to establish
whether a read actually ran. Older receipts remain readable by this release.
Readers of new conversation receipts with recovery evidence need Harness
0.9.19 or later.

Runtime 0.9.25 is required. Core 0.5.0 remains the floor, and the catalogue
ontology lane also qualifies Core 0.5.1. The PostgreSQL store 0.4.5 and
Runtime recorder 0.3.0 keep their published versions and schemas. See
[Runtime issue #37](https://github.com/B3Cognition/prosaic-runtime/issues/37).
