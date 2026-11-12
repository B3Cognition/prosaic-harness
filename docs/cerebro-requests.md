# Cerebro consumer requests

Updated 2026-11-12. The original requests and their delivery history remain below.

## Shipped context and tool capabilities

Context packs are published in Runtime 0.9.19, Harness 0.9.13,
Harness PostgreSQL 0.4.2 and Lab 0.9.12. Set an agent default or a
workflow-node override using Markdown evidence or accepted application records.
Guards retain their declared validation facts when the model receives a smaller
projection. See the [context-pack guide](context-packs.md).

Safe tool events and citations are published in Runtime 0.9.20, Harness 0.9.14,
Harness PostgreSQL 0.4.3 and Lab 0.9.13. The released family preserves Core 0.5.0
and Runtime PostgreSQL 0.3.0. See the
[shared contract design](superpowers/specs/2026-11-10-tool-result-event-evidence-design.md)
and [usage contract](tool-events-citations.md).

Parallel tool calls are published in Runtime 0.9.21, Harness 0.9.15,
Harness PostgreSQL 0.4.4 and Lab 0.9.14. See the
[parallel tool guide](parallel-tools.md).

MCP read tools are published in Runtime 0.9.22, Harness 0.9.16 and Lab 0.9.15.
Lab pins the verified public SDK wheels with Core 0.5.0, Runtime PostgreSQL 0.3.0
and Harness PostgreSQL 0.4.4. Select host-approved aliases in workflow agent nodes
and conversations. The optional Runtime extra provides Streamable HTTP,
authorization checks and journaled serial dispatch. Harness supports receipt
adoption while the endpoint is offline. See the
[Harness release notes](release-0.9.16.md) and
[Lab MCP guide](https://github.com/B3Cognition/prosaic-integration-lab/blob/v0.9.15/docs/mcp-client.md).

| Request | Existing foundation | Released behavior |
| --- | --- | --- |
| Tool arguments in step events | Runtime tool lifecycle events, call identity, typed outcomes and private conversation history | Released first increment: explicit host-approved argument/result display projections, bounded versioned events, separate permission to display, and no raw argument/result fields in general telemetry. Events describe observed execution and journal replay accurately. |
| Citation contract | Harness context packs retain citation IDs, source revisions/locators, representation hashes and actual deferred-read evidence | Released first increment: shared evidence references and final-answer citations that resolve only to authorized model-exposed content. Persist accepted citations with the answer and replay receipts without executing tools again. Provenance validation and semantic claim support remain separate checks. |
| Parallel tool calls | Explicit independent reads in fixed bounded windows; omitted policy remains sequential | Released: host-reviewed read registrations, per-node limits, serial barriers, ordered evidence and joined cancellation. Native and installed checks cover both wires. |
| MCP client | Local `CustomTool` registry with schema validation, explicit grants and bounded results | Released: optional SDK-backed adapter with scoped catalogs, bounded results and per-call authorization. MCP calls form serial barriers in parallel tool batches. |

## Bounded sub-agents

Runtime 0.9.23 and Harness 0.9.17 implement one level of serial delegation for
host-authored workflow nodes and conversations. The host registers each alias,
binds it to an independent context pack and reviewed read tools, and grants
current access. The coordinator owns the final answer and can cite approved
observations. PostgreSQL storage uses adapter 0.4.5 with explicit owner
migration. Lab 0.9.16 provides a copyable dependency analyst and reviewer.

See the [workflow authoring and recovery guide](sub-agents.md) and the
[Harness release notes](release-0.9.17.md).

## Earlier requests — recorded 2026-11-07

Cerebro requested the following, in priority order. The maintainer approved shipping a Harness blueprint using existing versioned validators and Runtime per-call headers first; Cerebro application changes remain out of scope; workflow enforcement tags follow in Harness0.9.12.

1. **Workflow rules with earlier step outputs. V1 in this release:** copyable Harness blueprint, trusted versioned validator, explicit first-review/revision dependencies, bounded feedback/retries, replay/freshness/version protection. Application policy owns insight IDs and the flagged-or-changed predicate. **V2 in Harness0.9.12:** enforcement tags/Guard admission in workflow agent steps, using Runtime0.9.16 public guarded turns and fresh declared accepted dependency facts. Retain the V1 API and blueprint; no copied execution engine. See [workflow rule contract](workflow-rules.md) and the separate [V2 blueprint](../examples/workflow-enforcement/README.md).
2. **Per-call OpenAI-compatible headers. In this release:** immutable host-supplied invocation headers, e.g. `x-tokenproxy-no-cache: 1`, forwarded on each provider request without modifying prompt/artifact identity. No model-controlled headers, raw-header persistence or global mutable options.
3. **Accounting request metadata. Runtime0.9.17/Lab0.9.10:** bounded immutable trusted `ExecutionContext.request_metadata` labels reach prepare before dispatch. No raw request/prompt/header projection or new authorization. Existing Harness0.9.12 retains original saved labels despite new caller labels/defaults; published recorder0.3.0 keeps its schema/bytes. Labeled contexts need >=0.9.17 readers; empty labels preserve old accounting hashes. See [contract](accounting.md#request-metadata-with-runtime-0917) and [Lab host](https://github.com/B3Cognition/prosaic-integration-lab/blob/v0.9.10/docs/accounting-request-metadata.md). Release pages carry final qualification/publication; partial SDK mixtures are not certified.
4. **Effort in results. Runtime0.9.18:** bounded `reasoning_effort_v1` observations retain actual HTTP/native controls and format through retries/fallback, separately from requested/profile defaults. Zero, unknown, omission and truncation are explicit; provider confirmation remains unobserved. HTTP correlation IDs join existing accounting calls without DDL. Published Harness0.9.12 preserves private result receipts and old absence. See the [Lab0.9.11 blueprint](https://github.com/B3Cognition/prosaic-integration-lab/blob/v0.9.11/docs/sent-reasoning-effort.md) and its complete-train/public-consumer proof. This documentation does not change Harness's declared Runtime floor or published bytes.
5. **Separate rule-repair allowance. Deferred:** explicit bounded initial and repair allowances, distinguish repair from transport retries. A hard total of1 cannot silently authorize2 calls. Keep token/tool/deadline/cost caps and unknown-effect recovery authoritative; show consumed allowances in evidence.
6. **Written identity guarantee. Deferred:** enumerate artifact digest, rules fingerprint, prepared input, workflow/binding and validator identity fields, absent/default omission and intentional changes. Golden old/new fixtures and a versioned migration/readmission policy; every release declares identity impact. Do not promise all hashes are unchanged when semantic bindings change.
7. **Version-specific release notes. Backfill completed; publisher enforcement deferred:** current releases have meaningful notes, and the documentation refresh backfills generic historical notes, including Runtime 0.9.14 and 0.9.15. See [release history](releases.md). Every future release must state behavior, compatibility, identity, migration and verification limits. Automating rejection of missing/generic notes remains future work; existing package bytes and receipts remain immutable.

Acceptance when revisiting: exercise both supported synthetic provider wires where applicable; source and isolated installed-wheel consumers; persisted resume/identity and accounting failure paths; no live inference without explicit authorization. Scope and release versions must be checked against current main before work begins.
