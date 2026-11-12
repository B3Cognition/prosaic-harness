# Bounded sub-agents across Runtime, Harness and Lab

Draft for review, 2026-11-12. Baseline is Runtime 0.9.22, Harness 0.9.16,
Harness PostgreSQL 0.4.4 and Lab 0.9.15, with Core 0.5.0 and Runtime recorder
0.3.0. The [Cerebro backlog](../../cerebro-requests.md#next-follow-up--sub-agents)
asks for named delegates, scoped context/tools, child accounting, finite limits,
cancellation and durable result adoption.

## Ask Cerebro behavior

A parent agent answering a release-impact question can call the host-registered
`analyze_dependencies` alias. The specialist sees a bounded task, the dependency
context pack and its explicitly granted read tools. The parent receives a
validated finding. It can optionally call a second approved reviewer alias
with a bounded draft under the same outer allowance. Each specialist sees its
own pack and the explicit task argument. The parent owns the final answer,
guards, citations and any human review transition.

Expose each specialist as a normal tool alias. The alternative of transferring
conversation control would change history ownership and the final-answer
contract. Fixed workflow nodes remain useful for mandatory review where the
host must guarantee the order. Use delegation for bounded, optional decisions
made inside an agent node or a conversation turn. The manager pattern also
appears in the [OpenAI Agents SDK orchestration guide](https://openai.github.io/openai-agents-js/guides/multi-agent/).
Prosaic adds explicit host admission, bounded receipts and recovery semantics.

The proposed first increment uses synchronous serial calls at depth one,
OpenAI-compatible Chat Completions or Anthropic Messages, the same resolved
provider/model and endpoint identity for both roles, and local read-only child
tools. Delegation-enabled attempts pin that route at preparation and refuse
fallback to a different route before its dispatch.
Multiple sequential sibling calls are allowed within the configured allowance.
Owner transfer, recursive calls, concurrent siblings, background jobs, native
CLI children, child MCP, terminal tools, write tools and child workflow starts
are follow-ups. A parent can still use separately admitted local parallel
reads or MCP aliases.

## Authoring and authority

Host code registers immutable `SubAgentSpecV1` values. Each registration has an
alias, description, binding revision, approved child artifact digest, a named
child pack binding, a closed task and result schema, a finite child policy, and
an explicit inventory of reviewed local read tools. The first task envelope is
`{"task": string}` or `{"task": string, "draft": object}` with a host-declared
closed schema for the optional draft. Schemas use bounded local JSON with no
external references or coercion. The proposed limits are 8 registered aliases
per parent, 1–8 launches per invocation, 8 KiB canonical task bytes, 16 KiB
canonical result bytes, and 64 KiB total frozen child projections, and at most 64 source references
and 16 KiB canonical private provenance per child outcome. Byte limits
include framing and respect tighter existing Runtime and Harness limits.

Host approval, parent artifact tools, workflow-node tools or conversation
allowlist, and Runtime admission all intersect. A trusted authored node can
use the existing `tools: [analyze_dependencies]` syntax. No new workflow node
kind is needed. Native authored JSON uses the same tool list. Workflow proposals
and discovery exclude delegate aliases in v1, including the initial-tool schema.
Registration fails on alias collision, an unsupported path, a missing guard
registration, a child tool outside its explicit read-only inventory, or a
missing recorder, durable journal, namespace, or current authorization binding.
Runtime tests can use in-memory doubles for those contracts.

The invocation frame binds alias, artifact and effective endpoint/model identity,
child tool descriptors, pack/spec revision, schema and policy hashes, authorization
policy revision, scope, limits and the owned projection hash. Account identifiers
come from trusted host context. Model arguments can supply task and draft data
only. All registrations and snapshots are owned copies. Binding drift on restore
fails before dispatch even when the new policy would accept the old task.

Runtime callers provide a data-only `SubAgentFrameV1` to prepare or restore the
turn. Supply a separate `SubAgentAccessV1` at execution with the same policy
revision. It carries `authorize_launch(alias, arguments, context)`,
`authorize_result(alias, context, source_refs, purpose)` and a trusted owner
check. The execution context for retained views uses the persisted scope and
current trusted viewer. Callbacks grant only on literal approval. Host-registered
child guards and child evidence/tool policies are bound to the immutable spec.
Pure preparation validates shape, route and registration; Harness performs
host/store checks before reservation; Runtime checks the recorder, current
bindings and owner before the first provider request. Callbacks remain live
configuration and do not enter serialized records.

Harness resolves named child packs once from already-admitted Markdown, trusted
input and fresh accepted upstream records. Keep these bounded projections in the
private frozen parent attempt and pass each to Runtime with its binding. Build
them without contacting external sources. A dynamic business lookup is an
explicit granted child read tool. Recheck current authorization on any selected
source before child dispatch and before saved result exposure. Separate launch grants
(which can inspect task arguments) from result grants (which use the
trusted principal, alias, binding revision and persisted scope). Apply current
result grants to journal replay, retained history, evidence views and display.
A failed grant
returns a sanitized unavailable result without a child request. Parent chat
history, parent tool outputs and parent guard facts are absent from child input
unless the host explicitly includes an approved snapshot or the model passes a
bounded draft. A draft is untrusted data. Parent context selection and guard
facts follow their existing independent paths. The child gets a fresh scoped
Runtime turn and its own guard bindings, with no inherited parent readers,
tools, retained citations or workspace access.

## Execution, budgets and accounting

Generate a contextual, nonterminal, journaled, serial `CustomTool` for each
approved alias. Runtime marks and admits those tools only on supported API
turns, including prepared turns. Ordinary Runtime runs that want delegation
use the prepared-turn API. Refuse direct `run_tool`, `StructuredToolLoop`,
native/CLI, interpretation, acquisition and initial-tool paths before provider
dispatch or a journal claim. Treat a delegation call as a barrier within a
parent parallel-tool batch. The child cannot receive a generated delegate tool,
and Runtime also rejects nested delegate entry while child execution is active.

Activate one root `ExecutionBudget` before the parent provider loop and a
narrower child allowance during the child turn. Parent tool admission counts the
delegate alias once. Child model requests and child tools count once against
their local policy and the shared root. Guard repairs, provider retries and
fallbacks use those same counters. Bound launches separately from tool calls.
At child entry clamp the child allowance to the remaining root allowance and
leave at least one provider request for parent continuation. A parent may need
more for additional tools or repair, subject to the same root caps. This
reservation covers request count. If the child consumes remaining tokens or time,
or leaves unknown usage, terminate with the existing bounded failure and retain
observed evidence. The provider continuation then makes zero requests. Keep the
earliest absolute deadline. Cancellation and lease loss reach child checkpoints
and provider/tool boundaries. The parent joins all admitted work before
continuing. Cancellation is cooperative for host callbacks.

Require finite root and child provider, tool and reported-token caps. Counters
use actual dispatch attempts. Unknown usage stops further capped dispatch.
Reported-token limits stop on observation and can be exceeded by a single
provider response. Where the host requires pre-dispatch token admission, use
the existing qualified `TokenCounterRegistration` and completion-token bound
for the same resolved provider/model. Preserve its unknown/overrun behavior.

Harness reserves the aggregate root provider/tool limits through the existing
conversation attempt quotas. Persist a finite delegated-turn token reservation against a host-declared
session allowance. In workflows, charge delegated attempts by their persisted
reservation and other attempts by existing token accounting when computing the
remaining workflow token allowance. Never also charge a delegated attempt's
parent-only result against that allowance. Reserve before marking dispatch
under the parent lease. Settle the conversation
provider/tool reservations using verified aggregate counts for known completed
attempts and retain the reservation for unknown outcomes. Charge the full token
reservation once per dispatched attempt in v1. Report actual provider usage
separately from admission capacity. A proven undispatched attempt may start
under its original reservation. A dispatched interrupted attempt cannot retry under
the same parent execution. An explicit new host-authorized turn/run receives its
own bounded admission under current policy.

Derive child invocation identity from the parent invocation and Runtime-wide
tool ordinal in the existing namespace. The key stays independent of alias and
arguments so the signature can reject changed input at the same slot. Construct
child attribution with `ToolExecutionContext.child_context()`, preserving
tenant, actor, payer, application, request, run and frozen request metadata.
Each request is recorded once in its actual invocation. The parent execution
receipt records aggregate admission and actual bounded counters separately from
its own provider result. Accounting evidence has no retry or authorization role.

## Durable boundary and evidence

The existing journal claim fences the child slot. Its signature binds the alias,
binding seal, canonical arguments and frozen frame hash. The committed journal
outcome is the child receipt for v1. Keep the existing `ToolJournal` claim and
commit protocol. For the marked alias, the success-shaped journal envelope
carries a private `subAgentReceiptV1` object with the frame/slot identity,
validated inner `ToolResultV1` or proven `ToolFailure`, and provenance
references. Runtime strips the private envelope before parent result handling.
Use a separate bounded parent receipt proof for reuse checks after adoption.
Check the current grant and parent lease before dispatch and result exposure.
The child journal's claim token can seal immutable observed evidence if the
parent lease is lost concurrently. Only the parent store's transactional lease
fence can adopt a receipt or advance parent state. Child journal writes never
advance parent state.

Check shape, current grant and available launch allowance before claim. Recheck
after a new claim and before launch. A proven no-work denial at this point
commits a fixed failure and closes that slot, including after a later regrant.
Debit the launch count once at child entry, after pure child preparation and
the final preflight. A failed write or an outcome with uncertain work remains
fenced. Invalid child output with known completed effects may produce a fixed
sanitized failure. A lost response, failed commit, stale owner or uncertain paid work
fails closed. No exception prose, raw child transcript, headers, credentials,
or child accounting record crosses into the parent model or public events.

Recovery behavior is explicit. Same-slot replay is a journal boundary contract.
Harness v1 offers no dispatched-parent continuation that recreates that slot.
Standalone Runtime callers own the outer dispatch fence and must avoid rerunning
an interrupted parent turn to recover its child result.

| Durable observation | Allowed action |
| --- | --- |
| Prepared parent and no dispatch marker | Restore the exact frozen input and reservation, check current grants, then dispatch once. |
| Journal outcome committed and the same slot is reached | Validate the journal signature and stored outcome, recheck current permission after lookup, and deliver the projected result without child work. |
| Child claim exists without a known committed outcome | Leave it fenced and surface uncertainty. |
| Child outcome committed but the dispatched parent has no invocation receipt | Keep the parent interrupted. The child outcome is insufficient to reconstruct the parent model/tool transcript. |
| Parent invocation receipt committed before adoption | Adopt once using the existing receipt and lease protocol. Recovery performs zero model and tool calls. |

Parse the accepted child answer as one JSON object under the configured result
schema. The parent sees that bounded finding with its ordinary guards still
in force. The model-facing result contains `finding` and optional
`observations` populated by a host projection. The host may copy exact, approved selections
from the child's runtime-observed read results into the bounded parent result and declare those fields through
existing `EvidenceDraftV1` selectors. Start with local typed tool-result
observations. Require a child delivery record, exact captured value and source revision, and current child and parent grants. Mint
parent evidence through the parent's existing tool evidence pipeline. A parent
citation requires actual parent delivery and the current citation grant. Child
citation strings, claimed sources in model output and private context fields
provide no parent citation authority. Seal authorization references for every
protected frozen source and every protected child read that entered the child request, including uncited inputs
that could influence a finding. Each reviewed child read registration must
enumerate its full protected source footprint from the trusted outcome or
declare its output public. Unclassified observations fail closed. A failed
current grant hides the entire affected proposal and its citations. Harness
preserves accepted receipts, masks the delegated answer in retained views,
and blocks further continuation when a grant for a prior delegated receipt
in that enabled session or workflow is denied. This conservative rule covers
later answers and outputs that may depend on the revoked input. Receipt-only
adoption verifies the immutable bytes and uses the normal parent lease.
Public projection and later model reuse apply current grants.
Result and display policies bind to approved fields. Public progress uses
existing approved tool events and, where enabled, bounded status fields. Child text/reasoning deltas stay private.

## Compatibility and qualification

Make the new API optional and advertise `sub_agents_v1` in Runtime and enabled
Harness stores. Selection means a delegate alias is in the invocation's effective
tool set before the first model request. Selected invocations use Runtime
prepared-turn encoding v6/frozen input v5 and a private `subAgentsV1` frame.
A registered but unselected alias leaves Runtime's legacy encoding in use.
Reuse the typed tool evidence codec and seal the private delegation proof in
the parent receipt.

At creation, a workflow whose admitted nodes can select a delegate uses
workflow state v6/receipt v5. A conversation with an effective delegate
allowlist uses session v6/receipt v6. A non-delegating attempt inside either
record has an empty delegation proof and keeps its usual Runtime encoding.
Opted-in stores can hold old and new records concurrently. An existing run or
session keeps its frozen binding, and enabling delegation for it requires a
fresh admitted run or session. The new records carry
existing context/tool fields and an optional parallel policy with its exact
existing semantics. Include versioned binding and accounting reservation proofs
in existing sealed records. Advance the owner-provisioned workflow storage
marker from 4 to 5 and the conversation marker from 5 to 6 in both file and
PostgreSQL stores. Migrate markers explicitly after draining writers.
Reuse existing PostgreSQL JSON tables and grants. Old readers refuse enabled
records, and newer readers keep reading old records. Base readers/records,
tool descriptors, canonical inputs, hashes, outputs and non-delegating behavior
remain byte-compatible. No in-place rewrite of legacy data.

Use a separately qualified Harness PostgreSQL adapter build for the new marker.
The Runtime recorder and Core retain their released bytes. No new third-party
dependency. Lab must qualify source and installed wheel/sdist consumers, both
provider protocols, Linux AMD64/ARM64 and PostgreSQL 16/18. Compare independent
provider, tool, receipt and accounting counts. Use owned synthetic infrastructure
and both analyst and reviewer fixtures. Keep historical manifests and receipts
immutable and current public pins unchanged through implementation. See the
[implementation plan](../plans/2026-11-12-sub-agents.md).
