# Shared tool result, event and evidence contract

Date: 2026-11-10. Status: proposed, independently reviewed; no implementation or
release is implied. Baseline: Runtime main `b2b2e39` / released 0.9.19, Harness main
`c43ebb9` / released 0.9.13, and Harness PostgreSQL 0.4.2.

## Intent and first increment

Ask Cerebro needs to show what tools actually did and give users citations they
can resolve to captured evidence. Prosaic should provide reusable execution and
provenance contracts while applications retain identity, authorization, display
policy and domain fact checking.

The user chose safe tool events and citations first. Parallel calls, MCP and
sub-agents are separate follow-ups. The API names, wire shapes and default bounds
below are design recommendations, not already approved or shipped APIs.

The first increment delivers:

1. An opt-in typed tool result with validated data and evidence declarations.
2. Bounded, host-approved argument/result projections in tool events.
3. An invocation evidence registry and a final-text citation contract.
4. Harness receipt/recovery and context-pack adapters, plus focused Lab coverage.

Success is a real Cerebro read such as `dependents(component="csb-frontend")`
producing an authorized UI summary `component: csb-frontend; count: 14` and an
answer citing the captured result. An event, a model-generated URL or a source
listed in an index cannot manufacture citation authority.

## Existing contracts to extend

Runtime already has immutable `CustomTool` definitions, closed input schemas,
argument/result byte bounds, explicit grants, contextual authorization,
`ToolFailure`, `ToolOutcome`, fenced effect journals and nested execution budgets.
The shared provider loop validates batches but executes calls sequentially.

There are two observation channels: `on_event` is a critical invocation callback;
the general observer is bounded, best-effort telemetry. Conversation capture
remaps provider call IDs and deliberately strips fields from provisional events.
Harness then adds step/attempt identity and applies its own event/receipt bounds.
Every one of these boundaries must explicitly support a new field; changing the
lowest-level emitter alone does not expose it safely to a consumer.

Context packs already supply `citationId`, source identity/revision/locator,
content hash, representation and actual read evidence. Reuse those contracts.
`ToolOutcome` remains the authority for execution status and effect uncertainty.
An application dictionary containing `status`, `sources` or `citationId` remains
ordinary untrusted data unless admitted through an opted-in trusted producer.

## Ownership and information boundaries

| Layer | Owns |
| --- | --- |
| Runtime | Result normalization, output validation, execution lifecycle, safe-event codec, evidence identity/delivery tracking, citation parser and final acceptance checks |
| Harness | Binding identities, context-pack adapters, durable receipts/adoption, retained-evidence authorization, step/session public views |
| Application | Tool handlers, source identity claims, caller/scope authentication, execution and display permissions, presentation links, semantic claim validators |
| Lab | Synthetic cross-provider, installed consumer and persisted-recovery examples |

Maintain three separately validated views:

- **Private result/provenance:** bounded captured data and source declarations,
  arguments already retained by existing receipts, execution outcomes and hashes.
- **Model result:** checked data and compact references for content submitted in
  model input. No automatic insertion of private provenance or guard facts.
- **Display event/view:** an explicitly approved projection for its current
  viewer. Execution permission, model exposure and UI display are distinct grants.

No evidence ID, digest, scope match, tool annotation or URL is an access token.
Private authoritative guard input remains separate from the selected model input.
This work does not narrow existing validation facts or make private facts citable.

## Registration and compatibility boundary

Propose independent optional `CustomTool` registrations:
`result_contract=ToolResultContractV1(...)` for typed data/evidence and
`event_policy=ToolEventPolicyV1(...)` for versioned display selectors. An existing
handler can keep its legacy return shape while opting into safe events. Event
result selectors consistently address the logical result data: the legacy return
value or v1 `data`, rather than either framing wrapper. Display execution also
requires an invocation-bound host display grant; registration alone cannot
authorize a viewer.

The output schema uses the same bounded, local JSON Schema subset as current
custom-tool input validation: no remote resolution or schema callbacks. It
validates `data`, not the provenance wrapper. Runtime validates/freeze-copies the
schema at registration and the returned data before admitting a result.

New nonempty declarations enter the tool descriptor and prepared/binding
identity. The tool version must change when handler or result semantics change.
Unconfigured tools retain the exact current descriptor and wire representation;
there is no implicit conversion based on dictionary keys. The configured contract
requires a typed `ToolResultV1` success or an existing typed `ToolFailure`.

An invocation's proposed `ToolContractBindingsV1` binds its enabled event policy,
citation policy, evidence authorization and optional retained-evidence imports.
Capabilities are independently named `tool_results_v1`, `safe_tool_events_v1` and
`citations_v1`. Admission checks the selected backend, registries and durable
reader/writer support before any provider/tool work. A fallback pool must not
select an incapable backend after admission.

## Tool results and effect journals

Proposed producer types:

```python
ToolResultV1(
    data={"component": "csb-frontend", "count": 14},
    evidence=(EvidenceDraftV1(
        source_key="cerebro.component-dependents",
        source_revision="graph-revision-42",
        locator="component:csb-frontend",
        selector="",  # JSON Pointer into data; empty means the whole value
        label="Dependents of csb-frontend",
    ),),
)
```

`EvidenceDraftV1` is accepted only from trusted registered handlers/adapters. It
contains a host-supplied source claim, not a Runtime certification of the external
database. `source_revision` may be null when the producer cannot establish one;
the captured value hash still identifies the observation. A locator is a bounded
private identifier/string, not an automatically fetched or publicly rendered URL.

Only closed JSON Pointers into `data` are supported for generic tool evidence in
v1. Runtime resolves each pointer against its owned result, computes the content
hash itself and rejects invalid selectors. It never accepts arbitrary detached
content or a producer-supplied hash in place of checking the captured value.

Preserve the existing journal outer shape `{"status":"ok","result":...}` and
`{"status":"error","error":...}`. For a configured v1 success, the journal's
`result` is a private tagged object `{version:1,data:...,sources:[drafts...]}`.
The registered tool contract disambiguates it from an ordinary legacy object.
This keeps the `ToolJournal` protocol and `ToolOutcome` v1 unchanged. Both new
execution and journal replay validate the tagged object against the pinned
contract. Invocation-specific evidence IDs are never stored as reusable journal
authority.

The model-facing success keeps the same outer shape and projects its inner value:

```json
{
  "status": "ok",
  "result": {
    "version": 1,
    "data": {"component": "csb-frontend", "count": 14},
    "evidence": [{"id": "ev_<64 lowercase hex characters>", "label": "Dependents of csb-frontend", "observation": "callResult"}]
  }
}
```

The example ID is a placeholder; real IDs are minted by Runtime. `observation`
is a closed value `callResult`, `journalReplay` or `retainedContext`, so reuse
is visible without pretending the source was queried again. None of these values
certifies external recency. Raw locators,
arguments, credentials and unrelated source metadata are absent from this view.
The private normalized outcome and final checked model projection are retained
separately in versioned evidence, using references to existing captured bodies
rather than duplicating unbounded content.

Normalize, validate and bound a journaled result **before committing it**. Preserve
the current commit-before-later-cancellation ordering. A malformed/oversized
journaled result or lost acknowledgment retains existing uncertain-effect
fencing; it cannot authorize retry. Nonjournaled invalid results preserve current
`ToolOutcome` uncertainty. Event formatting and citation repair cannot repeat an
already completed effect.

Raw and final model frames must each fit the existing tool result byte limit,
including their framing. Replay preserves the captured source revision and data,
rechecks current execution/exposure permissions, and mints delivery references
for the present invocation. It never turns cached data into a fresh observation.

## Evidence identity and actual model exposure

The Runtime-owned `EvidenceRecordV1` binds:

- Origin invocation, stable runtime call ID/index, tool name/version and argument
  digest, or a verified context-pack origin.
- Source key, nullable revision and private locator.
- Exact captured-body reference, selector/representation, content kind, byte
  length and SHA256 over the selected value.
- A delivery reference: provider request/input digest and the exact model view
  that included the value and its compact reference.

The generic ID is `ev_` plus SHA256 of the versioned canonical identity above,
excluding the later delivery reference. IDs are opaque. Delivery eligibility is
a separate record, not something proven by the ID alone.

Build a pending evidence view after output validation and post-tool guards. Mark
it eligible only when the corresponding bounded provider input is actually
dispatched with those bytes. An accepted final answer can use its eligible
registry; a constructed/dropped view, failed tool, discovery index, UI event or
undispatched result supplies no citation eligibility. This proves submission to
the invocation, not that a model read or understood the content.

Delivery capture checks the finalized native provider payload after history
fitting, tool-result compaction and transport encoding. A summary cannot prove
delivery of its omitted original. Within one invocation, a later compaction does
not erase proof of an earlier actual submission; importing evidence into a new
invocation requires a newly authorized/submitted view.

If post-tool guards rewrite data, retain references only for selectors whose
selected value is unchanged. Withdraw affected references; do not silently claim
the rewritten content came from the original source. If the resulting answer
cannot satisfy citation policy, fail or use existing explicitly bounded repair.
Trusted derived-evidence transforms are a future extension, not implicit v1 behavior.

For context packs, Harness validates origins through existing exposure bindings
and actual read receipts, without refetching source data. Inline content is
eligible only in the selected/dispatched view. Discoverable index entries are not
eligible until read. A deferred partial read gets a reference to its exact returned
representation/hash; it cannot widen into a citation of the parent document.
Existing `ctx_...` identifiers remain unchanged. Their adapter can reuse an ID
only for that exact exposed representation; narrower reads receive distinct
`ev_...` delivery records with the original pack citation as private lineage.

Propose a required versioned `EvidenceAuthorizerV1` when citations/evidence are
enabled. It receives owned scope, source/representation identity and purpose
`modelUse`, `cite` or `retainedRead`, and must return literal true; exceptions
deny without public diagnostics. It receives metadata, not private source bodies.
Model use authorizes the evidence-bearing projection before dispatch; `cite`
authorizes referencing it in an accepted answer; `retainedRead` separately
authorizes source viewing. Execution authorization remains independent.

Harness maps model use and retained reads onto existing context-pack authorization
and adds an explicit `citation` context-use purpose for references. The pack
adapter and generic authorizer must both permit the requested use. Existing host
authorizers that do not recognize the new purpose deny it until explicitly
versioned/readmitted; there is no fallback from citation permission to execution
or model-use permission.

`modelUse` denial stops before the next provider dispatch with a fixed
`evidenceUseDenied` invocation failure; an already completed tool remains
completed in its private receipt. `cite` denial also stops answer acceptance with
that code and never enters model repair for authorization failures. A denied
retained import is not registered or submitted. `retainedRead` denial returns an
unavailable public citation view without fetching, rerunning or disclosing its
private locator. Authorizer exceptions follow the same denial paths. These are
new invocation/view failures, not new meanings for `ToolOutcome` v1.

Prior-turn evidence is imported only by an explicit host/Harness retained-evidence
binding that verifies its immutable receipt, current scope/authorization and
current model exposure. Seeing an old ID in conversation text is insufficient.
Foreign sessions/tenants and private validation-only sources are refused.

## Safe tool events

Keep existing event names and fields. Enabled calls add one closed versioned
`toolEventV1` field to `tool_started`/`tool_completed`; legacy calls are unchanged.
For opted-in calls the shared executor owns emission, so provider, direct-tool
and structured-JSON paths cannot emit duplicate lifecycle pairs.

```json
{
  "event": "tool_completed",
  "name": "dependents",
  "call_id": "bf7284dca687ead3e469a834ce131129de89e3e635e2a57e7de71687ce0e748f",
  "turn": 1,
  "tool_version": "dependents-v1",
  "status": "ok",
  "duration_ms": 37.0,
  "tool_outcome": {
    "version": 1,
    "code": "ok",
    "phase": "execution",
    "effect": "completed",
    "recovery": "none",
    "replayed": false
  },
  "toolEventV1": {
    "version": 1,
    "callIndex": 0,
    "phase": "completed",
    "provisional": true,
    "display": {"component": "csb-frontend", "count": 14}
  }
}
```

`ToolOutcome` remains a separate existing field. `phase` is one of `started`,
`completed`, `rejected`, `replayed`, `uncertain`. A completed event means observed
tool completion, not an accepted answer or committed workflow/session turn.
Harness's existing commit/adoption events remain the acceptance boundary.

Display rules:

1. A versioned host policy declares named argument/result JSON Pointer selectors,
   then explicitly authorizes their disclosure for this invocation/viewer and
   purpose `toolProgress`. Only literal authorization true permits projection.
   Projection is declarative in v1: no arbitrary formatter callback, generated
   prose or model-authored summary. Computed counts must be actual result fields
   returned by the handler. Invalid/missing selected scalars are omitted.
2. Argument projection occurs after schema validation and execution authorization.
   A true `started` event occurs immediately before callback dispatch, after any
   required journal claim. Rejection produces a completed/rejected event with
   fixed safe codes and no argument/result display; replay produces a replayed
   completion without falsely reporting a new handler execution.
3. Result projection uses the successful checked result, never exception text or
   an unclassified/uncertain outcome. It may retain an already-approved argument
   summary and actual counters. Models cannot supply event fields or summaries.
4. No policy/grant means no `display`. Bad/oversized projector output is omitted
   with `toolEventV1.displayUnavailable: true` and no `display`. This failure does
   not change effect status, trigger a retry or echo a projector exception.
5. The general best-effort observer retains its present payload-free allowlist.
   Only the scoped `on_event` path may carry the approved display. Existing
   critical callback failure behavior remains unchanged and cannot erase a known
   completed effect. Event delivery is synchronous in this increment.

Use stable Runtime call IDs in all v1 views, keeping provider IDs private. Reuse
conversation capture's hash of invocation identity, exchange and call index;
the direct path uses exchange zero. One shared identity helper supplies the
structured loop and other API paths. Saved receipt adoption preserves these IDs;
a new invocation receives different IDs even if a journal result is reused. Existing
conversation ID remapping, direct-tool call identities and structured-loop IDs
must be connected to the same per-call record. Harness adds its existing
step/attempt scope without changing call identity. Sequence numbers, if added by
an adapter, describe observed emission order; they do not make events durable
evidence. Retained event projections require fresh permission when viewed again.

## Citation contract and accepted answers

Propose `CitationPolicyV1(mode="optional" | "required")`; absence means legacy
behavior. Enabling it binds owned citation instructions into prepared model input
and its identity. Models reference supplied IDs using the exact text token
`[cite:<evidence-id>]`. This preserves prose output and requires no second model
call merely to format references. The v1 token syntax is reserved everywhere in
an opted-in final answer, including code/quoted text; malformed tokens are errors.

After all ordinary answer guards and text fixes, parse the final accepted
candidate, compute token positions from its UTF-8 bytes and validate:

- Every token refers to eligible evidence in the invocation's authorized registry.
- The selected source/representation was delivered and remains authorized for
  final-answer use; a stale/foreign/index-only/private reference is rejected.
- `required` means at least one valid citation in a nonempty answer. `optional`
  permits none, but validates every token that is present. Neither mode promises
  every claim has a citation or establishes semantic entailment.

Application semantic guards/evaluations separately check that claims are supported.
Citation/source metadata are provenance, not domain facts. Fact guards enabled
with the new result wrapper must be audited/versioned to evaluate its `data`
projection rather than treating source hashes or metadata numbers as fact support.
Existing model/authoritative guard bindings remain explicit; no guard receives
broader evidence access through this contract.

Citation validation is a pure local acceptance check. A violation becomes a fixed
`citationViolation` answer-check failure. Repair is available only through an
existing explicit allowance and remaining provider/tool/token/deadline caps. There
is no hidden formatting call, fresh allowance, extra tool dispatch or uncapped
repair loop. A changed candidate is checked again as a whole; offsets and hashes
are never reused after text changes.

Accepted `Result.stdout` remains the answer text including tokens. A typed
`CitationsV1` sidecar records its SHA256 and an ordered list of token UTF-8
`start`, exclusive `end` and `evidenceId`, plus a digest of the evidence registry.
It contains no raw source bodies or automatic source URLs. The corresponding
private evidence remains in the receipt. Harness exposes a separately authorized
resolved citation view for rendering; applications can render tokens as footnotes
or links without changing the accepted stored answer.

Citation-enabled final text is withheld until ordinary guards and citations
accept it, using the current withheld-text mechanism. Safe tool progress can
continue live. General telemetry receives no answer tokens, citation IDs, argument
values or source locators through the new fields.

Opening a citation is a distinct `retainedRead` authorization. The host resolver
verifies the retained receipt, exact representation/hash and current viewer grant;
it may return captured bytes or an application-generated link. It performs no
arbitrary URL fetch. Escaping/link policy belong to the application. Revocation
can deny viewing or later inference independently while preserving the private
receipt. A safe public answer projection may mark a reference unavailable without
rewriting the canonical accepted answer or provenance.

## Persistence, failure and resource bounds

The effect journal records the validated outcome before later cancellation;
model exposure and final-answer acceptance are separate milestones. Persist the
private result declarations, final model-view bindings, accepted answer/citation
sidecar and their hashes in the same owned invocation/turn receipt. Harness saves
that receipt before adopting a result. A crash after receipt save adopts it under
current authorization without another provider call, tool callback or Runtime
guard execution. Current repeatable controller validation rules continue to apply.

Receipts before a dispatched continuation may prove a completed tool effect but
no delivered evidence. They retain existing interrupted/uncertain recovery rules;
missing delivery or citation evidence cannot be upgraded from progress events.
No event is made into a transaction log. Do not replay a completed effect to repair
missing citation metadata.

Use a new strict `TurnEvidence` version for the extension: existing v1/v2 codecs
remain unchanged. New Harness run/session/receipt versions carry an explicit
`toolContractV1` capability/binding marker and fail closed in incapable readers.
Numeric version allocation and exact serializer placement are implementation
details to settle against then-current main; the marker and refusal behavior are
contract requirements. Do not add unknown fields to old closed record schemas.
No database DDL is assumed: prove that existing JSON storage/capacity works before
choosing any migration. Schema ownership stays explicit if one is actually needed.

Proposed defaults are upper bounds; smaller existing limits always win:

| Bound | v1 default |
| --- | --- |
| Whole enriched event | 4 KiB UTF-8 encoded JSON |
| Display | 8 named scalar fields, 256 UTF-8 bytes/string, 1 KiB total |
| Generic evidence declarations | 64 per tool result, 256 active per invocation |
| Evidence sidecar | 64 KiB/invocation, excluding bodies already captured |
| Source key / revision / private locator / label | 256 / 128 / 1,024 / 128 UTF-8 bytes |
| JSON Pointer | 4 KiB; existing JSON depth/node limits also apply |
| Citation tokens / citation sidecar | 128 tokens, 32 KiB/answer |

Display fields accept finite scalar JSON values; control/ANSI/bidirectional
formatting characters are rejected. Source labels are data and always escaped by
renderers. Reject duplicate keys, nonfinite values, excessive traversal and cycles
using existing owned JSON codecs. Never truncate result/evidence silently into
something that appears complete. Omit optional display or refuse required evidence
with a closed code instead.

Opted-in durable runs require finite provider/tool attempt caps. Preflight reserves
the bounded receipt/event/evidence overhead within existing store, turn, history
and context-work budgets before dispatch. Both journal and model result framing
count toward result bounds; imported evidence and citation instructions count
toward prepared input limits/token admission. History fitting must not register
content omitted from actual submitted views. A late oversized callback result
does not undo the callback or remove existing uncertain-effect handling.

## First-increment coverage

| Execution surface | First increment |
| --- | --- |
| Shared OpenAI-compatible and Anthropic API tool loops, `run` and guarded `turn` | Results, safe events, exposure capture and final text citation checks |
| Harness workflow agent steps and graph-free conversations | Same Runtime contract, step/session bindings, persisted adoption and authorized citation views |
| `Runtime.run_tool` | Model-free result/evidence capture and safe events; no invented provider exposure or assistant-answer acceptance |
| `StructuredToolLoop` | Same result/event codecs; pure citation validation only with host-supplied exposure proof. Automatic `citations_v1` is unsupported in this external-driver surface |
| Builtin file tools | Existing output/events/read receipts; no automatic conversion into v1 custom-tool results or display policies |
| Native CLI execution | Existing behavior; no new capability inferred from opaque native logs. Enabled unsupported combinations refuse before dispatch |
| Host terminal completion tools | Existing behavior/events; combining terminal completion with automatic citation policy is refused in v1 to prevent bypassing final-answer checks |

Source/result declarations do not add parallel execution. Default ordering,
single-use structured-loop behavior, effect fencing, ordinary guard withholding
and accounting guarantees remain authoritative.

`StructuredToolLoop` yields a prompt to an external driver and receives a
`Result`; this is not proof of the prompt actually dispatched. It therefore
cannot advertise automatic `citations_v1` or mark returned references eligible.
Supplying automatic citation policy there is rejected before starting the loop.
Hosts may call the shared pure validator with an explicitly host-owned exposure
registry in both completion routes: `admit(proposal)` and
`tool_outcome(name, data)`. A host-attested registry is labeled as such; it cannot
be serialized as Runtime-observed delivery or minted from model JSON, a tool
payload, progress events or a bare `Result`. A future driver integration must
bind an actual dispatch receipt and exact input digest before it can claim
automatic delivery verification. This restriction also covers arbitrary JSON
proposal shapes; no implicit extraction or automatic completion bypass exists.

## Backward compatibility and identity

Disabled features preserve descriptor serialization, prepared input, policy hashes,
legacy output framing, old event shapes and old record encodings. New results,
display policy/version, citation policy and retained-evidence bindings explicitly
affect enabled run identities. Display selector policies and authorization
implementations have explicit versions; semantic changes require readmission
under a changed declared version.

Old receipts replay under old contracts. No automatic upgrading or rehashing of
historical records is allowed. New enabled records require capable readers and
explicit readmission when bindings change. Old tools returning dictionaries that
resemble v1 results remain ordinary data. Current `ToolOutcome`, `ToolFailure`,
`ToolJournal`, accounting and operation-key retry rules retain their meanings.

## Acceptance evidence for implementation

Use focused contract tests rather than writing tests that mirror helper code:

1. Safe events: allowlisted arguments and actual result counts; deny/invalid input,
   absent display grant, secrets in neighboring fields, malicious labels,
   malformed/oversized projector output, ID remapping and observer payload refusal.
2. Results/effects: output schema admission, typed-vs-dictionary distinction,
   bounds including framing, replay under a new invocation, completed effect then
   cancellation, unknown journal acknowledgment and no duplicate execution.
3. Citations: unknown/foreign IDs, exact selected value hashes, a deferred partial
   read, index-only/private evidence, post-tool correction, final-answer text fixes,
   UTF-8 offsets, required/optional policy, guard withholding and bounded repair.
4. Retention: authorized prior-turn imports, revocation before later inference and
   viewing, forged sidecars, crash after receipt save and adoption with zero new
   provider/tool calls. Distinguish completed tool proof from model delivery.
5. Compatibility: absent-field golden identity/wire/event/receipt fixtures,
   unchanged legacy journal outcomes, explicit unsupported backend refusal before
   spend, and existing private guard-input separation.
6. Exercise both API provider wires and the direct/structured paths; one installed
   Runtime/Harness consumer and one owned Lab scenario showing real tool events
   and resolvable citations. Add PostgreSQL persistence coverage for any changed
   durable codec/capacity, without duplicating unrelated native matrices for docs.

This document change needs local link/example/diff validation and independent
design review. It does not trigger implementation, dependency installation, live
inference, release builds or a release/CI train.

## Separate follow-ups

- **Parallel calls:** bounded host-approved independent reads, batch admission and
  reservation, per-call immutable outcomes, context propagation and deterministic
  history. Side effects/ordering and cancellation need their own design.
- **MCP client:** optional SDK-backed adapter using these tool/result/evidence
  contracts, explicit protocol/transports, schema admission, stable aliases,
  catalog drift, authentication and resource access. Metadata remains untrusted.
- **Sub-agents:** named delegates using existing child accounting/shared budgets,
  narrowed tools/context packs, depth/call caps, cancellation and durable adoption.
  No unrestricted recursion or new delegation scheduler in this increment.

## References

- [Cerebro backlog](../../cerebro-requests.md) and [context-pack contract](../../context-packs.md).
- Runtime [tools](https://github.com/B3Cognition/prosaic-runtime/blob/v0.9.19/src/prosaic_runtime/tools.py),
  [turn capture](https://github.com/B3Cognition/prosaic-runtime/blob/v0.9.19/src/prosaic_runtime/turn_capture.py),
  [tool outcomes](https://github.com/B3Cognition/prosaic-runtime/blob/v0.9.19/src/prosaic_runtime/tool_outcomes.py)
  and [structured transport](https://github.com/B3Cognition/prosaic-runtime/blob/v0.9.19/docs/structured-tools.md).
- Harness [actual read exposures](../../../src/prosaic_harness/context_packs/records.py)
  and [bounded recovery](../../bounded-tool-recovery.md).
- [MCP tool/result specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools):
  structured content, output schemas and untrusted tool annotations. This is prior
  art for the separate adapter, not an MCP dependency in this increment.
- [Anthropic parallel execution guidance](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use):
  provider batches leave execution scheduling to the client; relevant to the
  separate concurrency follow-up. Web references checked 2026-11-10.
