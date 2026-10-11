# Lean conversations in the Prosaic ecosystem

Date: 2026-10-11. Status: proposed design for maintainer review, not implemented.
Read-only Runtime, session/recovery and security-boundary reviews are complete;
their substantive findings are incorporated. No implementation or model run has
been performed for this proposal.

## Intent

Make Prosaic a lean way to build a natural-language assistant without adding
another orchestration framework or requiring every consumer to rebuild message
history and safe turn handling. Ordinary conversation must work without declaring
a graph. Existing Harness workflows remain available when a request needs
specialists, deterministic checks, selection or explicit confirmation.

The first proof must remember context, accept corrections, use approved tools,
and connect a follow-up to an exact workflow interaction. It must behave safely
through duplicate requests, competing messages and worker restart. The consumer
continues to own its interface, authenticated identity and business permissions.

## Repository and artifact decision

Extend the existing repositories and distributions. Do not create a new
repository, package family or canonical Markdown artifact kind for this MVP.

| Repository | Responsibility |
| --- | --- |
| Prosaic Core | Existing canonical `subagent`/`command` instructions and resources; no transcript or session execution |
| Prosaic Runtime | Provider-neutral message types and a bounded conversational turn API |
| Prosaic Harness | Optional graph-free conversation controller, session contract and recovery |
| Harness PostgreSQL adapter | Optional shared session persistence, with its own explicit schema |
| Integration Lab | Public-package adoption, HTTP embedding example and production-readiness evidence |

There will be new **execution records**: messages, session snapshots and turn
receipts. They are private data, not distributable agent prose. A consumer can
keep an existing agent Markdown file and bind it to a conversation through
trusted Python configuration. Neither a client nor an LLM supplies a directory.
An explicitly chosen file store has a private host root; memory and PostgreSQL
stores require no filesystem workspace.

Alternatives considered:

- A separate conversation repository would create another release/dependency
  boundary around responsibilities already owned by Runtime and Harness.
- A Lab-only implementation would prove a demo but leave consumers rebuilding
  the same generic mechanics. The Lab should consume the public implementation.
- Extending the existing packages preserves their ownership and optional-adapter
  pattern. This is the recommended approach.

A later independent package should require demonstrated dependency or release
pressure. A new Markdown kind should require an authoring contract that existing
agent instructions and trusted bindings cannot express.

## Prosaic patterns to preserve

| Existing pattern | Conversation application |
| --- | --- |
| Canonical prose plus private host bindings | Agent instructions are reusable; credentials, tools and policy stay host-owned |
| Pure admission before effects | Construct and validate bindings/history without models, callbacks, migrations or probes |
| Models supply data, never authority | Interpretations cannot grant tools, change owners or manufacture consent |
| One execution engine | Reuse Runtime's shared provider/tool loop, not a second chat engine |
| One writer of controlled state | The conversation controller owns session advancement; Harness owns workflow advancement |
| Opaque revisions and fenced leases | Competing turns cannot silently reorder or overwrite each other |
| Immutable receipt before checkpoint adoption | Recover a completed turn without repeating inference |
| Explicit uncertainty | Missing completion evidence never authorizes automatic retry |
| Optional persistence and explicit initialization | A memory example needs no database; shared deployments opt into an adapter |
| Public consumer verification | Lab tests installed artifacts instead of private APIs or sibling source patches |

Existing source anchors are the [RunStore protocol](../../../src/prosaic_harness/run_store.py),
[interaction projection](../../../src/prosaic_harness/interaction.py),
[recovery controller](../../../src/prosaic_harness/engine.py) and
[PostgreSQL rulings](../../decisions/2026-10-08-run-store-postgres-rulings.md).

## Runtime: role-aware turns

Add a public `ProsaicRuntime.turn()` alongside the existing `run()` API. Proposed
shape, not an executable example yet:

```python
turn = runtime.turn(
    approved_agent,
    message="Show me the second result",
    history=committed_history,
    policy=host_run_policy,
    on_event=handle_provisional_events,
    context=trusted_accounting_context,
    operation_context=trusted_invocation_scope,
    tool_journal=host_tool_journal,
)
```

The result contains a sanitized copy of the authoritative `Result` plus an
immutable, provider-neutral completed-turn record. Publish a documented metadata
allowlist for this new API; raw provider headers/continuations and private prompt
debug fields remain internal. Existing `run()` metadata stays compatible.
The new API does not mutate supplied history.
Its public types cover user/assistant text, ordered assistant tool requests and
their corresponding tool outcomes. Tool records have stable call IDs, registered
names and bounded finite JSON. Neutral call identity is scoped to the originating
invocation and exchange; provider IDs stay private and may repeat across turns.
Adapters consistently encode matching request/result references. Reject duplicate
IDs within an exchange, unknown fields, orphan results, invalid roles and incomplete
historical tool groups before dispatch; ordinary repeated native `call_0` values
in separate exchanges must remain usable.
Serialized new public contracts use camelCase; Python APIs use normal snake_case.

For the new `turn()` path, prevalidate each entire proposed tool batch before any
handler dispatch. Unknown/ungranted names or malformed, duplicate-key, nonfinite
or schema-invalid arguments fail that turn with `invalidToolRequest`; they do not
enter automatic model repair. Retain observed usage and known completed effects
in its receipt. This deliberate initial restriction avoids inventing a cross-provider
wire representation for rejected native requests. Valid tool requests may still
return bounded declared error outcomes and continue through the existing loop.
Legacy `run()` keeps its existing tool-error correction behavior. Tests must prove
that the new restriction occurs before effects, rather than discovering invalid
history only when a later successful completion is committed.

Supported initial transports are the current OpenAI-compatible and native
Anthropic text/tool paths. Both reuse the same bounded execution loop and encode
neutral history themselves. Provider-specific continuation dictionaries and raw
headers remain private. Images, hidden reasoning, provider-managed sessions and
native coding backends are outside the initial turn contract; unsupported
bindings fail explicitly before a request. Advertise `conversation_turn_v1` as an
explicit capability so Harness cannot silently fall back to string concatenation.

The new turn path defaults to no filesystem workspace. File/CLI capabilities
require explicit private host workspace/root bindings and existing permission
checks; missing bindings fail before dispatch rather than use the process's
current directory. Native tools remain trusted host callbacks with their own
domain authorization and transport bounds. This does not sandbox Python handlers.

Approved agent prose and bundled host resources form trusted instructions,
separate from user/assistant/tool history. A new conversational artifact containing
`{{args}}` is rejected: arbitrary user content must never be interpolated into
host instructions. Existing `run()` rendering, prompt roles, acquisition and
serialized results remain compatible. Conversational acquisition is deferred;
approved retrieval tools can supply data through the normal tool boundary.

Only trusted embedding code can restore a complete typed history. A public chat
endpoint accepts a new user message, not system/assistant/tool roles or a supplied
transcript. Persisted historical tool requests are context, never commands to
redispatch. Tool results and summaries never become privileged instructions.

Retain existing tool schema/permission checks, native execution evidence,
versioned registrations, cancellation, observation, accounting and invocation
budgets. Reuse existing tier routing; the MVP binds one approved agent/profile to
each session. Different approved bindings and workflow specialists can select
different tiers. Per-turn agent/profile switching is deferred rather than adding
another routing language. Optional workflow-reply interpretation has a separate
fixed host-approved instruction artifact and profile, sealed with the session;
it cannot borrow the conversational agent's tool grant.

## Harness: graph-free sessions

Introduce proposed public `Conversation`, `ConversationBindings`,
`ConversationPolicy`, `SessionSnapshot` and `SessionStore` contracts. `Conversation`
calls Runtime directly for an ordinary turn; it does not construct a one-node
workflow. Its session may reference an existing admitted workflow when needed.

Bindings snapshot the approved artifact, relevant Runtime configuration, requested
tool descriptors and semantic versions, execution/context policy and approved
workflow registrations, including any fixed interpretation artifact/profile and
its tool-free policy. Following `WorkflowBindings`, also seal `operation_namespace`
and the tool journal descriptor's logical `identity` and `contract_version`,
including their absence. A journal requires an explicit operation namespace.
Read static declarations using the existing journal descriptor contract; do not
call journal methods during admission. Derive identity from all those validated
inputs. Secrets, handler source/repr, journal DSNs and private storage paths are
not public identity material. Construction invokes no handlers, authorizers,
validators or provider probes.

Persist the original binding identity and logical version. Another worker must
reconstruct that exact binding to execute or recover a session. Missing versions
and semantic drift fail explicitly; never reinterpret an old turn with current
defaults. Host permission revocation still applies at execution, even when the
binding identity matches. Fingerprints detect inconsistency, not authentication.
Reject adding/removing a journal or changing its namespace, logical identity or
contract before dispatch, receipt adoption or interrupted retry. Check the actual
static descriptor against the sealed declaration at those boundaries, including
when reusing an existing bindings object. Rotating private credentials does not
change logical identity; the host must preserve the same
actual effect ledger behind that declared identity. A matching descriptor cannot
prove that an embedding application has honored this responsibility.

Sessions begin with a host-generated opaque ID and frozen trusted scope:
namespace/environment, application, tenant, actor and optional billing account.
The MVP is single-actor. The controller verifies scope equality on reads and
mutations, while the embedding service authenticates and authorizes the actual
caller before invoking it. A session ID or namespace alone grants no access.

Proposed controller operations are creation, read-only status/history, `send()`,
receipt recovery and explicit interrupted retry. A send carries user text,
owner-scoped message ID and the caller's observed session revision. It returns a
bounded public turn/status view, not private Runtime configuration or raw operator
state. Workflow attachment uses a host-approved registration and an owned run;
client text cannot register code, validators, endpoints or generated bindings.

## Ordered turns, idempotency and recovery

Keep one bounded sealed session snapshot: ordered admitted turns, request
identities, aggregate counters, one pending operation and any workflow reference.
Store immutable invocation receipts separately. Do not introduce an event-sourcing
framework, queue or background scheduler for this MVP.

Under a fenced session lease, atomically admit a message, assign its turn sequence,
freeze its input/context/binding identity and persist the pending invocation.
Check current authorization before replay or admission. An identical message ID
returns the original pending/completed result even if its original revision is now
stale. Reuse with different text, attachment/action or immutable input conflicts.
Two new messages against the same revision cannot both dispatch: one wins, the
other receives busy/revision conflict and must refresh intentionally.

Persist a dispatch marker before inference. Persist a complete bounded Runtime
receipt before committing the assistant turn. Then admit that receipt and advance
the session with CAS under the current lease. No database transaction or checked-out
connection spans inference, a tool callback or a workflow operation. Lease loss
stops further dispatch and prevents stale result adoption; it cannot undo an
already dispatched provider request or remote effect.

| Turn state | Meaning |
| --- | --- |
| `pending` | User input and context admitted; dispatch has not begun |
| `running` | Dispatch intent is durable; completion may be unknown |
| `completed` | Successful final result admitted and assistant history committed |
| `failed` | Known failure recorded; no successful assistant answer committed |
| `needsResolution` | Dispatch/effect may have happened without sufficient completion evidence |

Recovery adopts a matching saved receipt without another call. A dispatch marker
without a committed receipt becomes `needsResolution`; lease expiry does not
authorize replay. A receipt reporting `tool_effect_uncertain`, `tool_journal_failed`
or another ambiguous effect still leaves the turn `needsResolution`, not ordinary
`failed`. Recorded failure is not evidence that no effect occurred. Unknown tool
effects retain the existing journal's uncertainty contract. An explicit
host-authorized interrupted retry is a new invocation
attempt under the same turn, retaining original ownership, evidence and allowance
consumption. It cannot resolve an uncertain business effect by itself.

An authoritative `pending` record with no dispatch marker may execute its same
frozen invocation under a new valid lease. If dispatch-marker commit acknowledgement
was lost, reconcile authoritative store state first; local pending state alone
cannot justify dispatch. Receipt adoption and repeated recovery are idempotent,
including their accounting and allowance updates.

Retain every complete admitted user message in turn order, including a known
failed or canceled turn. Its history record carries the authoritative terminal
status and a bounded public failure code, not raw provider errors. A rejected
message was never admitted and is not history. Successful turns contribute their
complete assistant/tool groups; unsuccessful turns contribute only their admitted
user message and status, never
partial assistant output or tool exchanges. Encode unsuccessful status as bounded
unprivileged data alongside the user-role content, not as a system instruction or
fabricated assistant answer. Adapters must preserve this meaning when consecutive
user records occur.

This preserves corrections such as "I meant Prague" when answering that message
failed. Historical user text may inform context, but is not a fresh command,
confirmation or retry consent. Admission and confirmation always require the
current source message and current interaction checks. Pending/interrupted input
and partial effects remain available for recovery inspection. Block new turns
while an unresolved operation exists; read-only status and recovery inspection
remain available. Unknown usage is preserved, never zeroed.

All streamed text is provisional, including text preceding a tool request.
Runtime completion does not mean session commit. Emit a distinct committed-turn
event only after durable adoption. Reconnection with the same message ID reads
saved status/result without inference. Durable replay of every individual SSE
delta is outside the MVP.

## Bounds and memory

Bound retained history, model input and execution evidence separately. Require
finite host limits, captured in the sealed policy; clients and model text cannot
increase them. Recommended initial defaults are:

| Bound | Default | What counts |
| --- | --- | --- |
| Admitted user turns | 64 | Every distinct admitted message, including failed/canceled turns |
| Retained history | 4 MiB | Canonically encoded user records/statuses and complete successful assistant/tool groups |
| Whole sealed snapshot | 8 MiB | History, request identities, counters, attempt ledger, pending input and workflow reference |
| Individual user text | 16 KiB | UTF-8 text before admission |
| Final assistant text | 64 KiB | UTF-8 text before commit |
| Complete turn record | 128 KiB | Canonical encoding, including user text and assistant/tool exchanges |
| Model request/context | 192 KiB | Actual provider encoding of instructions, history, new input, current exchanges, tool schemas and request envelope |
| Runtime invocation attempts per user turn | 3 | Initial invocation and any explicitly authorized retries or additional model phases |
| Runtime invocation attempts per session | 128 | Ordinary turns, interpretation and every other conversation-owned Runtime call, even with zero provider/tool calls |
| Individual invocation receipt | 8 MiB | Complete canonical encoded receipt |
| Retained/reserved invocation receipt bytes | 64 MiB | All immutable receipts plus outstanding reservations across the session's lifetime |

These are independent ceilings: 64 turns is a maximum, not a promise that 64
worst-case turns fit. Text bounds measure UTF-8; encoded-record bounds include
serialization overhead. Intermediate blocks, events, parsing depth/node counts
and transport responses retain finite Runtime/tool/storage limits. Effective
request limits are the stricter conversation and Runtime transport limits.
Duplicate message replay, reconnect and receipt adoption add no turns or attempts.
A retry retains the original turn sequence but consumes a new attempt slot.
Allow exactly one immutable invocation receipt per allocated attempt, hence at
most 128 retained receipts; identical writes are idempotent and conflicting writes
fail. Workflow command evidence stays within the bounded snapshot and does not
create a second conversation invocation receipt.

Before dispatch, durably reserve an attempt slot, maximum encoded receipt bytes,
and history/snapshot space for the maximum terminal turn plus bounded failure and
recovery metadata. Reserve before each new attempt, not just the initial send.
Use bounded failure records so a failed answer can always retain its admitted
user text and status. Replace reserved receipt bytes with the actual committed
encoded size in a fenced CAS exactly once after authoritative matching evidence;
unknown writes or unfinished attempts retain their reservation. No automatic
receipt eviction or reuse of consumed attempt slots. Keep terminal history/snapshot
headroom through interpretation and any subsequent workflow-command phase until
the user turn reaches its final adopted state; an interpretation receipt alone
cannot release it. Receipt recovery/adoption, duplicate replay
and read-only inspection remain available when capacity is exhausted.

If a result exceeds its turn contract, retain a bounded terminal failure receipt
and known effect/usage evidence; do not admit partial assistant history. Storage
availability may still change after admission, so a failed/unknown receipt write
preserves the dispatch marker and requires reconciliation rather than assuming
rollback. Enforce limits before admission, before every provider dispatch and
again before result adoption. Exhaustion returns a typed `sessionLimit` or
`contextLimit`, identifies the exhausted limit and preserves the existing history
and evidence. It never silently deletes older turns to accept a new one.

The MVP context mode is explicitly `fullHistory`: all admitted user records with
their statuses, all complete successful assistant/tool groups, and the new user
message. Trusted instructions remain in their separate privileged role. Freeze
this projection and its identity at admission; replay/retry uses that original
context rather than rebuilding it from later session state. Construct and bound
the initial provider payload before admission/inference. If it cannot fit, return
`contextLimit` without admitting or dispatching the new message.

For `turn()` in this mode, explicitly disable request-time tool-result compaction
in the shared execution loop for both historical and newly produced tool results,
regardless of endpoint `tool_result_compaction` defaults or feature settings.
This is a per-invocation mode; do not mutate shared endpoint configuration.
Legacy `run()` keeps its current compaction behavior. Recheck the fully encoded
payload before every subsequent provider request. If a growing tool exchange no
longer fits, stop with `contextLimit`, retain admitted user text, known effects
and usage in the failure receipt, and exclude that partial assistant/tool exchange
from future history. Never silently summarize, truncate a pending selection or
discard one side of a tool exchange. Byte bounds do not establish exact model
token-window capacity; provider context rejection remains an explicit failure,
without automatic hidden shortening/retry.

Automatic summarization, vector memory and long-term semantic retrieval are
deferred. A future context selector must report its retained source range and
identity, preserve the full transcript separately, and treat summaries as data.
Model-generated summaries would add paid inference, uncertainty and lossy memory;
they require a separate explicit effect contract.
An opt-in recent-history window is also deferred. Filling context therefore stops
new work explicitly; the host may offer a new session, but cannot claim that it
inherits the old session's remembered context or consent.

Each invocation has finite provider-request/tool-call/deadline limits. The session
also bounds cumulative provider and tool allowances. Reserve an invocation's
maximum request/tool allowance before dispatch; release unused reservation only
after trustworthy final evidence. Unknown attempts retain their reservations.
Reported-token caps, when configured, retain existing retrospective/unknown-usage
behavior; they are not a hard monetary guarantee. Retries and restarts do not
reset budgets. Use existing accounting and operation scope identifiers rather
than changing the recorder's serialized contract or billing eligibility.
Session allowances cover every Runtime invocation made by the conversation,
including reply interpretation. Attached workflow execution retains its own
existing run allowances. A combined tenant/deployment allowance is the host's
responsibility; the session cap must not be presented as including workflow calls.

Reserve JSON work capacity as well as UTF-8 bytes before dispatch. The outer
session/receipt allowance is depth64 and65,536 nodes; the default effective
Runtime allowance is depth56 and28,672 nodes, leaving room for record framing,
coexisting completed history/evidence and bounded host views. Host views use a
separately derived7,168-node allowance. These effective limits are sealed.
Materialized interpretation/command evidence consumes its reservation; it does
not discard the remaining terminal headroom. Exhaustion still permits adoption
of an already allocated receipt and exact replay.
Version1 stores impose hard8MiB snapshot/receipt and65,536-node ceilings.
Smaller receipt limits derive a smaller Runtime evidence allowance after reserving
the complete turn, duplicated canonically encoded final answer and8KiB correlation
framing. The encoded answer bound is `min(6*maxAssistantBytes+2,maxTurnBytes)`,
including JSON control-character escaping and the complete-turn ceiling. Reject
policies that cannot represent those bounds during pure binding admission.
Public interaction views reserve final-answer/envelope space inside the whole
public reply allowance, rather than using that allowance independently per field.
Before admitting each message, also bound its full failed/interrupted user record
against the turn allowance. Failed source framing cannot be deferred until after
inference. Atomic snapshot replacement permits a complete validated snapshot
from an already pinned file descriptor; immutable receipts retain pathname-inode
checks and replacement is never accepted as ordinary mutable state.
Interpretation admission also bounds the user plus a fixed64-byte host-rendered
clarification/outcome record; an interpreter binding requires an assistant text
allowance of at least64 bytes. Short invalid model JSON cannot consume the space
needed for a safe host clarification after the receipt is saved.

Private Runtime tool evidence may retain `callIndex`, `signature`,
`operationNamespace` and `operationKey`, alongside its neutral call ID and safe
completion/uncertainty status. These logical references locate the original
journal record after a lost acknowledgment. They are private recovery evidence,
never part of a public conversation reply; a hash alone cannot locate or prove
completion of the actual ledger record.

## Workflow interactions and natural-language replies

Keep conversation history separate from Harness run state. Attach at most one
owned workflow to a session in the MVP, using its retained admitted definition
and private host binding. Expose current status and `PendingInteraction` through
the existing public projection. Workflow steps retain their own validators,
grants, budgets and deadlines; the conversation cannot extend an expired run.

Bind a displayed selection/confirmation to a curated immutable view containing
the run, step, workflow revision, ordered offered entities/choices and response
schema. Store that interaction reference in the conversation turn that displays
it. A reply such as "the second result" must target that exact reference; a new
search or reordering cannot silently change its meaning.

Reply interpretation uses the fixed admitted interpreter binding with
`allowed_tools=frozenset()`, `max_tool_calls=0`, `initial_tool=None`, no acquisition
and no filesystem/CLI capabilities. Interpreter admission also rejects an
artifact requesting tools. This sealed policy is mandatory even when
the ordinary conversational turn or workflow has tools. Send no tool definitions
to the provider. Reject any returned tool request with `invalidToolRequest`
before dispatching a handler, tool authorizer, operation-key resolver or journal
claim. Never fall back to the session's ordinary policy or pass its effect journal
to interpretation. Provider-request/deadline/output limits and session accounting
still apply. These are enforceable execution limits; prose asking the interpreter
to avoid tools is insufficient.

A model may propose a structured interpretation bound to the actual source
message and interaction reference. Admit a bounded closed response schema, then
validate allowed entity membership, freshness and current host authorization
before applying it. The interpreter artifact and schema version are included in
binding identity. Ambiguous interpretations ask for clarification. Model
confidence is not consent. A direct structured human response may bypass model
interpretation but must pass the same admission and confirmation checks.
For consequential approval, require an explicit host-declared confirmation rule
or direct structured human response. Quoted instructions, earlier approvals,
assistant/tool statements and model-generated text cannot authorize a decision.
Model output can never select interrupted retry consent.
For the MVP, every natural-language workflow command requires the registered
versioned host confirmation rule to return literal `True`. Generic graph
structure cannot classify which choice may lead to a consequential effect.
A registration without that rule supports attachment and reads, but its model
proposal only produces a clarification; direct authorized Harness responses
retain their existing public admission path.

Use sequential typed pending phases: `modelInvocation` for interpretation, then
`workflowCommand` for applying its admitted response. Save/adopt the interpretation
receipt once, and persist the frozen workflow command before calling
`Harness.resume()` with its original expected revision. Recovery of an uncertain
workflow command must not rerun interpretation. Public status distinguishes model
completion from workflow-command completion; final wording cannot claim approval
or task success before its actual workflow outcome is durably recorded.
The MVP does **not** promise an atomic transaction
across the conversation and workflow stores. Current Harness human-decision
history has no stable external action ID. If a crash occurs after resume may have
committed but before the conversation records its result, mark the bridge command
`needsResolution` and read actual run state; never repeat at a refreshed revision
or infer command identity from matching choice/response text.

This conservative recovery is the selected MVP contract. A narrow idempotent
human-action receipt in Harness is a possible later hardening if seamless handoff
recovery is required. It must be designed as a supported public contract, rather
than hidden Lab metadata or a fabricated invocation receipt. Until then, the
public status must make the unresolved handoff visible, and qualification must
prove that recovery cannot produce a second approval/effect.

## Persistence, privacy and compatibility

`SessionStore` follows the existing storage pattern: explicit readiness,
session-scoped exclusive lease, owned snapshot load/create/CAS-save, immutable
receipt read/write and close. Return plain bounded public types, not driver
objects. Memory, file and PostgreSQL implementations share contract tests.
Memory storage is explicitly non-durable and single-process; it is never an
automatic fallback for failed durable storage.

Add `PostgresSessionStore` inside the existing Harness PostgreSQL distribution.
Use a separate `prosaic_harness_conversations` schema with version/contract 1,
explicit initialization/readiness and least-privilege grants. Preserve current
RunStore schema version 1, checkpoint format, initialization and grants. A
deployment using only old RunStore must work without initializing conversations
or receiving any conversation-table privileges. Reuse primary/WAL durability,
bounded transport, database-time leases and fencing patterns without weakening
their guarantees.

File stores use private host-owned roots, safe path validation and atomic durable
replacement. Session state/receipts are private evidence; default telemetry
contains opaque correlation and bounded status, not message bodies or tool data.
Owner-filter transcript export explicitly. The host owns retention/encryption
policy. Do not add automatic deletion or expiry in the first release; document
private storage growth bounds and operator lifecycle responsibility. A future
purge must preserve necessary idempotency tombstones and unresolved/linked
evidence, so deletion cannot make an old message dispatch again.
The reference host also enforces finite owner/deployment retained-session quotas,
including completed, failed and unresolved sessions, and bounded simultaneous work
using its existing service admission mechanisms. At capacity it rejects new
sessions explicitly. Creation rate limits and concurrency limits alone do not
bound total retained storage when sessions have no automatic expiry. The proposed
defaults cap controller-owned logical records at 8 MiB snapshot plus 64 MiB
receipts/reservations per session. Physical database/file overhead, WAL, backups,
accounting, external tool journals and linked workflow stores have separate host
capacity and lifecycle policies; the logical cap is not a disk-space guarantee.

Existing Core formats, `Runtime.run()`, workflow constructors, RunStore, saved
workflow runs and CLI commands retain their behavior. New conversation APIs are
opt-in, with their own versioned records and capability admission. Do not create
a chat CLI, server dependency or new adapter distribution merely for the demo.

## Milestones and evidence

### 1. Runtime conversation turns

Implement typed neutral messages and `turn()` using the existing shared engine.
Verify native tool exchanges, role separation, unsupported bindings, strict
history validation, Unicode byte limits, cancellation, streaming/final-result
distinction, accounting and budget behavior. Exercise OpenAI-compatible and native
Anthropic with credential-free synthetic transports. Prove unchanged `run()`
behavior and installed-wheel public imports/examples.
Include repeated native tool IDs across turns and invalid tool batches, contrasting
the new fail-closed behavior with legacy correction and proving no early handler
effect in a partly invalid batch.
Test full-history input that triggers the existing compactor: at least nine tool
outcomes and an older successful JSON result exceeding 96,000 characters, outside
the latest four results. Explicitly enlarge tool, turn-record and request limits
for this fixture.
Assert that historical and current tool content reaches the provider unchanged,
compaction remains disabled even when endpoint features enable it, and `run()`
still compacts under the same feature settings. Test overflow before the first
request and after a completed tool call: no extra provider dispatch, no hidden
shortening, and known effects/usage retained. Exercise unsuccessful user records
and consecutive user-role content on both transports.

### 2. Harness sessions and optional persistence

Implement pure admitted bindings, ordered controller state, memory/file stores
and PostgreSQL sessions. Contract-test idempotency, CAS, competing messages,
fencing, receipt-before-adoption, delayed/lost commits, interrupted retry consent,
unknown budget reservations and owner isolation. Verify cross-worker recovery
against owned PostgreSQL 16/18 on Linux AMD64/ARM64. Verify old RunStore with its
original roles/schema and conversation readiness failures without fallback.
Cover lost dispatch-marker acknowledgements, safely undispatched pending recovery,
saved uncertainty receipts, terminal capacity reservation and repeated recovery
without duplicate counters or allowance release.
Reject a changed operation namespace, journal identity/contract or journal
presence on reconstruction, adoption and retry before any model/tool dispatch;
construction must not invoke journal methods. Reject changed interpreter bindings
or a policy attempting to grant tools. Prove that an admitted correction survives
a known failed answer and is supplied to the next successful query with its
failure status, without partial assistant/tool history or inferred consent.
Test each history/snapshot/text/attempt/cumulative-receipt boundary, including
Unicode/serialization overhead, zero-call attempts, retries, unknown write
reservations, exact duplicate receipt writes and rejection without eviction.
At capacity, duplicate replay and saved receipt adoption must still succeed.

### 3. Lab adoption and workflow bridge

Add an authenticated reference chat endpoint using installed public packages.
Its request accepts user text, a message ID, expected session revision and an
optional opaque interaction reference; the host chooses owner and bindings.
Keep transport/result views curated and bounded. Demonstrate a synthetic journey:
remember a preference, correct it, search approved entities, select the second
offered result, pause for confirmation, and finish an existing admitted task.

Test duplicate/concurrent messages, reconnect, worker restart, saved receipt
adoption, uncertain inference/effect/handoff, stale/reordered selections, ambiguous
confirmation, quoted/fabricated approval, grant revocation, context overflow and
cross-user access. Add real model conformance for the locally available Qwen and
hosted tiers only through explicit opt-in and a shared bounded allowance; label
actual provider/model results separately from synthetic correctness evidence.
Verify interpretation/handoff phases independently and enforce creation/concurrency
capacity without counting workflow invocations as conversation-budget usage.
Add a quoted-approval regression with a consequential tool registered for the
ordinary session: the interpreter must receive no tools, and a fabricated native
tool request must invoke zero handlers, authorizers, operation-key resolvers and
journal claims. A quoted or historical approval cannot resume the workflow.
Test a failed correction followed by a successful query, retained-session quotas
including terminal sessions, and explicit history/context/receipt capacity errors.

Publish consumer installation, minimal memory usage, durable store initialization,
host bindings, streaming commit semantics, workflow replies and uncertainty
recovery. Verify fresh wheel/sdist consumers and the existing Lab matrix. Missing
required infrastructure fails selected lanes rather than skips. Preserve receipts,
source commits, original artifact hashes and exact-owned-fixture cleanup evidence.

Release only after qualification: Runtime capability and compatible recorder
dependency range first, then compatible Harness/adapter versions, then Lab's
released dependency manifest and adoption
guide. Core needs no feature release unless a concrete defect is discovered.
Choose exact version bumps during the implementation/release plan, not from this
unimplemented proposal.

## MVP limits and review decisions

The proposal deliberately includes text conversations, approved native tools,
bounded full history, single-actor sessions and one optional approved workflow.
It omits shared editing, background tasks, automatic summaries, retrieval indexes,
multimodal content, dynamic profile changes and a graphical workflow editor.
Runtime remains stateless across calls; optional Harness sessions supply memory.

The follow-up design review seals the operation namespace and journal contract,
makes interpretation tool-free, disables inherited compaction for full-history
turns, and retains admitted corrections after failure. Qualification cases above
cover each rule. History is bounded independently from model context, and attempts
and cumulative receipt storage are bounded as well. These are design requirements;
their regression tests have not been implemented or run yet.

The material decisions for maintainer review are extending the existing
repositories/artifact kinds, bounded full history with a fixed session binding,
the new turn API's fail-closed invalid-tool behavior, and visible `needsResolution`
for a lost workflow-handoff acknowledgement. These keep the implementation
focused and preserve established recovery rules. If seamless workflow handoff is
required initially, expand the public human-action receipt contract before
implementation; do not weaken revision checks to approximate it.
