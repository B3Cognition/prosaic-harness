# Cerebro consumer requests

Updated 2026-11-10. The original requests and their delivery history remain below.

## Current tools work — 2026-11-10

The maintainer requested a shared tool result/event/evidence design. **Safe tool
events and citations are the first implementation increment.** Parallel tool
execution, an MCP client and sub-agents remain separate follow-ups. The
[shared contract design](superpowers/specs/2026-11-10-tool-result-event-evidence-design.md)
is proposed; these capabilities are not shipped by this backlog update.

| Request | Existing foundation | Status and acceptance direction |
| --- | --- | --- |
| Tool arguments in step events | Runtime tool lifecycle events, call identity, typed outcomes and private conversation history | First increment: explicit host-approved argument/result display projections, bounded versioned events, separate permission to display, and no raw argument/result fields in general telemetry. Events describe observed execution and journal replay accurately. |
| Citation contract | Harness context packs retain citation IDs, source revisions/locators, representation hashes and actual deferred-read evidence | First increment: shared evidence references and final-answer citations that resolve only to authorized model-exposed content. Persist accepted citations with the answer and replay receipts without executing tools again. Provenance validation and semantic claim support remain separate checks. |
| Parallel tool calls | Provider batches, shared budget admission and per-call execution records; dispatch is sequential today | Separate follow-up: host-approved independent reads, bounded concurrency, per-call immutable outcomes, deterministic history, cancellation and aggregate budget reservation. Sequential execution remains the default. |
| MCP client | Local `CustomTool` registry with schema validation, explicit grants and bounded results | Separate follow-up: optional SDK-backed adapter, explicit protocol/transport coverage, admitted schemas and stable tool aliases, catalog changes, authentication and per-call authorization. Remote annotations do not grant execution or parallelism. |
| Sub-agents | Nested execution budgets, child accounting context, specialist prompts and context packs | Separate follow-up: named host-registered delegates with narrowed context/tools, parent/child budget accounting, depth/call bounds, cancellation and durable result adoption. Do not introduce unrestricted recursive delegation in the first increment. |

The first increment belongs primarily in Runtime, with Harness adapters for
context-pack provenance, durable adoption and authorized views, and focused Lab
consumer scenarios. Preserve legacy tool wire values, guard bindings and saved
records when the new contracts are absent. Capability checks must reject
unsupported enabled combinations before dispatch. No release versions are
assigned until the implementation scope is approved.

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
