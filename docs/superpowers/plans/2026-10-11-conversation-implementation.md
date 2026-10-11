# Conversation Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver optional graph-free durable conversations and safe replies to existing owned Harness workflow interactions.

**Architecture:** A sealed host binding and a bounded version-1 session reducer surround public Runtime preparation/turn APIs. Memory, file and PostgreSQL stores share owner-filtered CAS/lease/immutable-receipt semantics. A separate tool-free interpretation phase precedes a frozen workflow command, preserving visible uncertainty across the two stores.

**Tech Stack:** Python 3.11+, public Prosaic Runtime, existing jsonschema/referencing, pytest/build; optional existing psycopg adapter. No new framework or distribution.

**Spec:** [Approved conversation design](../specs/2026-10-11-conversation-design.md).

## Global Constraints

- Ordinary conversation must work without declaring a graph; do not create a one-node workflow.
- Existing Core formats, Runtime.run(), workflow constructors, RunStore, saved workflow runs and CLI commands retain their behavior.
- Serialized new public contracts use camelCase; Python APIs use normal snake_case.
- Single-actor frozen scope; current application authentication/authorization remains the embedding host's responsibility before every operation, including replay/read.
- Pure binding admission invokes no models, callbacks, migrations, journal methods, validators or probes. Fingerprints do not replace admission.
- Seal operation namespace and journal identity/contract/presence; check actual static declarations at dispatch, adoption and retry.
- Only complete successful assistant/tool groups enter history; all complete admitted user messages, including failed/canceled corrections, remain with explicit status.
- `fullHistory` is the sole initial context mode. No implicit truncation, compaction, summaries, windowing or vector memory.
- Defaults: 64 admitted user turns; 4 MiB history; 8 MiB snapshot; 16 KiB user text; 64 KiB final assistant text; 128 KiB complete turn; 192 KiB model request; 3 Runtime attempts per turn; 128 per session; 8 MiB per receipt; 64 MiB lifetime retained/reserved receipts.
- New PostgreSQL schema is `prosaic_harness_conversations`, version/storage contract 1; current RunStore schema version 1, tables, grants and on-disk formats stay compatible.
- No automatic retry after uncertain dispatch/effect/handoff, automatic deletion, queue or scheduler. No connection/transaction spans model, tool or workflow execution.
- Use apply_patch; observe failing tests before implementation; preserve unrelated files, local Stripe design and historical qualification receipts.

## Review Focus

- Host creation acknowledgement can be lost: a persisted preallocated session ID must replay exact creation without orphaning/quota bypass (Tasks 2 and 4).
- A reused bindings object can have a mutated live journal declaration: recheck the original seal at every execution/recovery boundary (Tasks 1 and 5).
- ASCII/UTF-8 serializers can disagree on Unicode capacity: one canonical new-session encoder must drive admission, storage and reservations (Tasks 2, 3 and 7).
- Exhaustion must not prevent adoption of an already allocated receipt or exact duplicate replay (Tasks 2 and 5).
- Interpretation completion must not release terminal headroom or imply that workflow resume committed (Task 6).

## Linked deliverables and dependency order

1. [Runtime turn plan](../../../../prosaic-runtime/docs/superpowers/plans/2026-10-11-conversation-turns.md) produces the independently usable stateless turn API.
2. This plan produces memory/file/optional shared conversations and workflow replies.
3. [Lab adoption plan](../../../../prosaic-integration-lab/docs/superpowers/plans/2026-10-11-conversation-adoption.md) consumes installed artifacts and qualifies the complete train.

At execution start, read the worktree skill, inspect attached worktrees/status in all three repositories and create/reuse isolated `codex/conversation-*` branches using the current local committed state. Carry these plans and design commits into the implementation checkout; do not silently start from remote main without them. No implementation worktree or product dependency installation is part of this planning stage.

### Public interface contract

Create `conversation_bindings.py` with:

```python
@dataclass(frozen=True)
class ConversationScope:
    namespace: str
    environment: str
    application: str
    tenant: str
    actor: str
    billing_account: str | None = None

@dataclass(frozen=True)
class RunAuthorizer:
    identity: str
    version: str
    authorize: Callable[[ConversationScope, str], bool]

@dataclass(frozen=True)
class ConfirmationRule:
    identity: str
    version: str
    admit: Callable[[str, dict, dict], bool]
```

Validate bounded references and static callable declarations; accept only literal `True` from authorizers/confirmation rules. Their declared identity/version/presence is sealed; source/repr is excluded. Admission never invokes them. These are trusted host authorization rules, not model-supplied policy.

`ConversationPolicy` contains the defaults above under explicit snake_case fields: `max_turns`, `max_history_bytes`, `max_state_bytes`, `max_user_bytes`, `max_assistant_bytes`, `max_turn_bytes`, `max_input_bytes`, `max_attempts_per_turn`, `max_attempts`, `max_receipt_bytes`, `max_total_receipt_bytes`. Also seal `max_json_depth=64`, `max_json_nodes=65536`, `max_public_bytes=262144`, cumulative `max_provider_requests=256`, `max_tool_calls=256` and `context_mode='fullHistory'`. All are finite; no boolean-as-integer acceptance. Runtime policies independently cap each invocation.

```python
class WorkflowRegistration:
    def __init__(self, workflow: Workflow, *, store: RunStore,
                 authorizer: RunAuthorizer, runtime=None, validators=None,
                 accounting=None, context=None, review_outputs: tuple[str, ...] = (),
                 confirmation_rule: ConfirmationRule | None = None): ...

class ConversationBindings:
    def __init__(self, agent: ProsaicArtifact, *, version: str, config: RuntimeConfig,
                 policy: ConversationPolicy, run_policy: RunPolicy,
                 turn_limits: TurnLimits | None = None,
                 custom_tools=None, operation_namespace=None, tool_journal=None,
                 workspace=None, workspace_identity: str | None = None,
                 interpreter: ProsaicArtifact | None = None,
                 interpretation_policy: RunPolicy | None = None,
                 interpretation_schema: dict | None = None,
                 workflows: Mapping[str, WorkflowRegistration] | None = None): ...
```

Expose the bounded host logical `.version` and derived `.identity`; logical binding version is separate from storage/record version 1. Snapshot all effective Runtime TurnLimits, including metadata/event/evidence/depth/node limits. Derive shared byte limits from ConversationPolicy and reject a conflicting explicit TurnLimits; never recover with new Runtime defaults. A configured private workspace requires a stable logical workspace_identity; seal its identity/capability meaning, exclude physical paths/credentials and require the host to preserve the same resource behind it across reconstruction.

The registry seals approved original workflow admission/config/tool/validator/operation material, not a fixed run ID. Runs may be created after a session. At attach, linked read and resume, recheck that material, authorize the actual run, and use standard Harness with the stored run ID. Preserve the run's original accounting context/budgets; do not replace them with conversation attribution. If saved accounting ownership exists, compare relevant trusted scope; otherwise the versioned host authorizer supplies application ownership evidence. Store/Runtime/credential references remain private. No opaque workflow wrappers or parallel engine.

Interpreter defaults are one provider request, zero tool calls, max_tool_rounds 1, timeout 30 seconds and the same finite input bounds. Its artifact requests no tools; no acquisition/workspace/CLI/effect journal. Seal its profile, artifact, policy and closed response schema. `interpretation_schema` admits only `{sourceMessageId, interactionRef, choice, response, ambiguous}` with required source/reference/ambiguous fields, bounded choice/response and no unknown fields; validate its proposed response again against the actual interaction schema/membership before applying it.

Create public `ConversationReply` as an owned immutable encoded view with `.document` returning a fresh camelCase dict: `version`, `sessionId`, `revision`, `turnSequence`, `messageId`, `status`, optional `answer`, safe `failureCode`, `pendingInteraction`, and `recoveryStatus`. It exposes no scope, Runtime configuration, prepared input, private receipts, raw errors or operator snapshot. Status-only responses omit absent turn fields.

```python
class Conversation:
    def __init__(self, bindings: ConversationBindings, *, store: SessionStore,
                 scope: ConversationScope, context=None, accounting=None, observer=None): ...
    def create(self, *, session_id: str | None = None) -> SessionSnapshot: ...
    def status(self, session_id: str) -> ConversationReply: ...
    def history(self, session_id: str) -> tuple[ConversationMessage, ...]: ...
    def send(self, session_id: str, *, message_id: str, message: str, expected_revision: str,
             interaction_ref: str | None = None, on_event=None, cancelled=None) -> ConversationReply: ...
    def recover(self, session_id: str) -> ConversationReply: ...
    def retry_interrupted(self, session_id: str, *, expected_revision: str,
                          acknowledge_effect_risk: bool, on_event=None, cancelled=None) -> ConversationReply: ...
    def attach_workflow(self, session_id: str, *, registration: str, run_id: str,
                        expected_revision: str) -> ConversationReply: ...
```

`session_id` is a trusted optional preallocated UUID hex, never a client authority claim. Exact create replay verifies immutable scope/binding/version and creates no additional session. `SessionSnapshot(session_id, state, revision)` is host/operator data, not an HTTP response. The first conversational send accepts text only. Direct structured human responses continue through existing Harness.resume() with its own current revision/auth checks; adding a parallel structured conversation-send convenience is deferred.

Optional accounting injection follows existing Harness and public Runtime.turn(accounting=...). When enabled, require a complete trusted ExecutionContext and validate application/tenant/actor/billing against frozen scope; do not inherit a different owner/payer. Freeze its resolved attribution and parent invocation at creation, with session-correlated request_id/run_id. Each ordinary/interpreter attempt receives its own child invocation_id and stable phase/turn step_id; adoption verifies the original attribution and IDs. Reconstruction cannot replace frozen accounting context with current defaults. Recorder schema stays unchanged; linked workflow accounting remains separately frozen in its original run.

### Task 1: Pure binding, scope and capability admission

**Files:** Create `conversation_bindings.py`, `tests/test_conversation_bindings.py`; modify `__init__.py`.

**Interfaces:** Produce the scope/policy/registry/binding contracts above and an internal admitted binding containing original immutable identity/version and private execution references.

- [ ] Write RED tests using static journal declarations whose methods raise if called:

```python
def test_journal_namespace_is_identity_material(binding_factory):
    left = binding_factory(operation_namespace="ledger-a")
    right = binding_factory(operation_namespace="ledger-b")
    assert left.identity != right.identity
    assert left.tool_journal.calls == []
    assert right.tool_journal.calls == []
```

Create `tests/support/conversations.py` fixtures `binding_factory`, `scope`, `runtime_fixture` using real public artifacts/config/tools and static journals. `binding_factory` exposes the admitted identity and test-owned journal object; it accepts normal binding constructor overrides, not forged seals.
- [ ] Give fixture bindings explicit version `chat-v1`; verify version and all effective TurnLimits are immutable identity material, require a logical identity for explicit workspace and reject changed declarations. Document that the host must preserve the actual resource behind a matching declaration, just as it must preserve the actual effect ledger.
- [ ] Run `.venv/bin/python -m pytest tests/test_conversation_bindings.py -q`; observe missing API failures.
- [ ] Reuse factory snapshot/descriptor/schema helpers for pure admission; include journal presence, logical namespace/identity/contract, interpreter and authorizer descriptors. Require journal namespace, supported Runtime capability and finite budgets before store mutation. Recheck static journal descriptors on reused objects, not only fresh reconstruction.
- [ ] Test changed config/artifact/tool version/validator/workflow/authorizer/interpreter, malformed scope, unsupported capabilities, mutable aliases, callback/probe counts and forged matching fingerprints. Run focused tests; review and commit.

### Task 2: Version-1 reducer, reservations and memory store

**Files:** Create `session_contracts.py`, `session_store.py`, `memory_session_store.py`, `tests/test_session_contracts.py`, `tests/test_session_store.py`; extend `testing.py`.

**Interfaces:** Produce `SessionSnapshot`, safe session errors and the following synchronous store contract:

```python
class SessionStore(Protocol):
    namespace: str
    def initialize(self) -> None: ...
    def check_ready(self) -> None: ...
    def lease(self, session_id, *, scope) -> ContextManager[LeaseSession]: ...
    def load_session(self, session_id, *, scope) -> SessionSnapshot: ...
    def create_session(self, session_id, state, lease, *, scope) -> str: ...
    def save_session(self, session_id, state, expected_revision, lease, *, scope) -> str: ...
    def load_receipt(self, session_id, invocation_id, *, scope) -> dict | None: ...
    def save_receipt(self, session_id, invocation_id, receipt, lease, *, scope) -> None: ...
    def close(self) -> None: ...
```

Reuse safe StoreError subclasses for lease/revision/receipt failures; add `SessionNotFound`, `SessionAlreadyExists`, `SessionBusy`, and `ConversationError(code, limit=None)`. Its closed codes are `bindingMismatch`, `identityMismatch`, `capabilityMissing`, `invalidMessage`, `messageConflict`, `contextLimit`, `sessionLimit`, `confirmationRequired`, `interactionStale` and `invalidInterpretation`. Runtime failure codes are retained in terminal records, not admitted as arbitrary exception messages. Foreign-owner records appear not found. Bind leases to exact store/session/scope; return fresh owned snapshots. Memory store is explicitly single-process/non-durable, never a fallback.
- [ ] Write failing memory/CAS/ownership/receipt tests, using support helper `session_document(scope, binding_identity)` to create a valid sealed empty document:

```python
def test_session_snapshot_is_owned(memory_store, scope, session_document):
    sid = "a" * 32
    with memory_store.lease(sid, scope=scope) as lease:
        memory_store.create_session(sid, session_document(), lease, scope=scope)
    loaded = memory_store.load_session(sid, scope=scope)
    loaded.state["turns"].append({"forged": True})
    assert memory_store.load_session(sid, scope=scope).state["turns"] == []
```

- [ ] Observe RED, then implement closed canonical UTF-8 JSON encoding and finite depth/node preflight, seals, store ownership, scoped revisions and immutable receipts. Leave RunStore validators/encoding untouched.
- [ ] Implement pure transitions `reserve_attempt`, `mark_dispatch`, `adopt_receipt`, `freeze_workflow_command` in `session_contracts.py`. These consume/return owned sealed state and accept no callbacks. State includes version/scope/binding/turns/message identities/counters/attempt ledger/pending/workflow reference. Receipts match exact session/attempt/source/context/binding/encoding identity.

```python
# Reservation replacement is an idempotent state transition under fenced CAS.
if attempt["receiptAdopted"]:
    return state
state["reservedReceiptBytes"] -= attempt["receiptReservationBytes"]
state["retainedReceiptBytes"] += canonical_size(receipt)
attempt["receiptAdopted"] = True
```

- [ ] Reserve full maximum receipt bytes and terminal history/snapshot/provider/tool headroom before every attempt. Count zero-call attempts; derive receipt count from non-reusable attempt slots. Known terminal evidence releases only unused allowance/storage reservation; uncertainty retains it. Test every cap, Unicode encoding, identical/conflicting writes, repeated adoption and capacity-safe recovery. Review and commit.

### Task 3: Durable private file sessions

**Files:** Create `file_session_store.py`, `tests/test_file_session_store.py`; extend backend conformance helpers.

**Interfaces:** `FileSessionStore(root: Path, *, namespace: str)` implements SessionStore; root is explicit absolute private host configuration. Use confined descriptor-pinned paths and canonical session encoding, not legacy indented RunStore serialization.

- [ ] Add RED restart/CAS/symlink/foreign-owner tests. Run `.venv/bin/python -m pytest tests/test_file_session_store.py -q`.

```python
def test_no_root_defaults_to_cwd():
    with pytest.raises(TypeError):
        FileSessionStore(namespace="test")
```

- [ ] Implement scoped locking/lease checks, atomic writes plus file/directory fsync, immutable receipt creation and readiness. Reuse low-level safe file operations without changing existing RunStore paths/formats. Missing/corrupt/oversized records fail explicitly and never masquerade as absent receipts.
- [ ] Run memory/file conformance, crash-after-receipt-write, tampering/invalid seal, ID traversal, symlink replacement and cleanup tests. Review and commit.

### Task 4: Ordered graph-free send and retained failed corrections

**Files:** Create `conversation.py`, `tests/test_conversation.py`, `tests/test_conversation_limits.py`; extend support fixtures.

**Interfaces:** Produce create/status/history/send and ConversationReply. Consume public Runtime.prepare_turn(), turn(PreparedTurn), owned messages and TurnResult. No private Runtime imports or fabricated graph.

- [ ] Add RED exact-replay/concurrent-revision/failed-correction tests. Fixture `conversation_fixture(store_kind)` provides `controller`, `runtime`, `scope`, `queue_text`, `queue_known_failure`, `provider_calls`, `provider_requests`; transport is real bounded loopback HTTP.

```python
def test_failed_correction_survives(conversation_fixture):
    with conversation_fixture("memory") as fx:
        snapshot = fx.controller.create()
        fx.queue_known_failure()
        failed = fx.controller.send(snapshot.session_id, message_id="correction",
            message="I meant Prague", expected_revision=snapshot.revision)
        fx.queue_text("Prague")
        reply = fx.controller.send(snapshot.session_id, message_id="query",
            message="Which city?", expected_revision=failed.document["revision"])
        assert reply.document["answer"] == "Prague"
        history = [item.to_dict() for item in fx.controller.history(snapshot.session_id)]
        assert history[0]["turnStatus"] == "failed"
        assert history[0]["content"][0]["text"] == "I meant Prague"
        payload = json.dumps(fx.provider_requests[-1])
        assert "I meant Prague" in payload and "failed" in payload
```

- [ ] Observe RED, then implement under session lease: verify scope/current binding; exact message replay before new-work capacity checks; expected revision; build/bound public PreparedTurn; reserve capacity; save admitted user/pending; save dispatch marker; release checked-out connections; call public Runtime; save receipt; validate/adopt in fenced CAS; project result.
- [ ] Persist complete frozen context projection, its identity and encoding version; retries readmit it rather than rebuilding from newer state. Exact create replay compares scope/binding/version; different create input conflicts. First context overflow rejects without admission/POST.

```python
saved = pending["input"]  # original owned message/history/inputData, never current history
prepared = runtime.prepare_turn(bindings.agent, message=saved["message"],
    history=tuple(ConversationMessage.from_dict(item) for item in saved["history"]),
    input_data=saved["inputData"], policy=bindings.run_policy,
    limits=bindings.turn_limits, workspace=bindings.workspace)
if (prepared.context_identity != pending["contextIdentity"]
        or prepared.encoding_version != pending["encodingVersion"]):
    raise ConversationError("bindingMismatch")
```

For interpretation select the fixed interpreter artifact/policy from the original sealed phase. Store only owned original public inputs plus original identities, not a deserialized executable PreparedTurn. Map typed Runtime TurnAdmissionError codes/limits to safe pre-admission controller errors; never parse arbitrary exception text.
- [ ] Preserve all admitted terminal user records and bounded public failure codes. Never include failed partial assistant/tool groups or infer consent from prior user text. Emit provisional Runtime events, a `receiptSaved` phase event after immutable receipt save, and `turnCommitted` only after durable adoption. Hook failures cannot undo effects or authorize redispatch.
- [ ] Verify scope reads/replays, transport message bounds, revision races, provisional/final events, no tools on history replay and independent attempt/history/context quotas across memory/file. Run controller/limit suites; review and commit.

### Task 5: Fenced receipt recovery and explicit retry

**Files:** Extend controller/reducer; create `tests/test_conversation_recovery.py`.

**Interfaces:** Produce recover()/retry_interrupted(). Literal `acknowledge_effect_risk=True` is trusted host input; model text cannot set it. A retry consumes a new attempt while retaining turn/source/frozen context and prior evidence.

- [ ] Add RED public SessionStore delegate fixtures for crashes before marker, unknown marker acknowledgement, after receipt save and before adoption. Delegates use the documented protocol and expose barriers, not private engine mutation.

```python
def test_saved_receipt_recovery_makes_no_call(recovery_fixture):
    with recovery_fixture(crash="receiptSaved") as fx:
        sid = fx.send_until_crash("hello")
        calls = fx.provider_calls
        recovered = fx.fresh_controller().recover(sid)
        assert recovered.document["status"] == "completed"
        assert fx.provider_calls == calls
        assert fx.fresh_controller().recover(sid).document == recovered.document
```

- [ ] Observe RED; implement authoritative reconciliation before dispatch after an unknown marker write. Marker absent permits original allocated attempt; marker present without matching trustworthy receipt is needsResolution. Uncertain tool/journal receipts remain needsResolution. Stale lease owners cannot dispatch further tools or adopt results.
- [ ] Match source/context/binding/journal/attempt receipts and replace reservations exactly once. Capacity blocks only new allocation, never exact replay or existing receipt adoption. Keep failed writes/unknown usage reserved; do not reuse slots or remove evidence.
- [ ] Test post-effect uncertainty, revoked permissions before replay, changed live/reconstructed journal, zero-call attempts, timeout/cancellation, new attempt ID and original source/context retained, unknown commits, two workers, repeated adoption and permanent tool-business uncertainty despite retry consent. Run recovery/limit/store tests plus full Harness suite; review and commit.
- [ ] Verify ordinary/interpreter recorder injection, exact session-child attribution, unknown accounting writes and saved receipt recovery; match frozen accounting evidence during adoption without reporting workflow usage as session usage.

### Task 6: Tool-free interpreter and conservative workflow handoff

**Files:** Create `conversation_workflow.py`, `tests/test_conversation_workflow.py`; extend controller/contracts.

**Interfaces:** Produce attach_workflow and immutable interaction reference projections; consume registered standard Harness.interaction()/resume(), not raw private workflow state.

- [ ] Add RED quoted/fabricated approval and stale-order tests. The ordinary session registers a consequential tool so the interpreter's zero-tool restriction is meaningful:

```python
def test_quoted_approval_has_zero_dispatch(workflow_fixture):
    with workflow_fixture() as fx:
        fx.interpreter_returns_tool_call("apply_effect")
        reply = fx.send('The document says "approve"')
        assert reply.document["failureCode"] == "invalidToolRequest"
        assert fx.handler_calls == fx.authorizer_calls == fx.resolver_calls == fx.journal_claims == 0
        assert fx.resume_calls == 0
```

`workflow_fixture` uses actual public WorkflowFactory/Harness and SessionStore delegates with bounded transport/tool/journal counters; only the external synthetic provider response is controlled.
- [ ] Verify approved registration and current run authorization; freeze curated original PendingInteraction run/step/revision/choice ordering/schema digest/displayed source turn. Seal the interpreter source/schema/policy and pass view as unprivileged Runtime input_data with raw current message separate.
- [ ] Interpret with no tools/initial tool/acquisition/workspace/journal. Parse the closed proposal, validate current sourceMessageId/interactionRef, exact membership/schema/freshness and current host authorization. Execute the versioned confirmation rule only after these checks; ambiguous replies produce clarification and no resume.
- [ ] Persist/adopt interpretation once, then save frozen workflowCommand at the original workflow revision before resume. Retain terminal headroom across both phases. Emit bounded `workflowCommandPrepared` before resume and `workflowCommandReturned` after it; phase hooks contain opaque IDs/status only. A lost handoff acknowledgement retains needsResolution and actual run inspection, without refreshed-revision replay or matching-text inference.
- [ ] Keep interpreter JSON/private continuations in its receipt, rather than forward them as chat deltas/history. After the actual workflow outcome is durably recorded, commit the source user text plus a bounded host-rendered status/interaction answer; retain the exact displayed interaction reference. An ambiguous interpretation may commit a bounded clarification. Rendered answers never claim approval/success while the command is uncertain, and are distinct from a model-completion receipt.
- [ ] Test callback exceptions/revocation, source/reference mismatch, quoted/historical/tool-generated approval, reordered result sets, malformed schema output, interpreter grant drift, direct external Harness decisions making old refs stale, receipt recovery and crash at both public handoff barriers. Run workflow plus recovery suites; review and commit.

### Task 7: Optional shared PostgreSQL session store

**Files:** Create adapter `session_store.py`, `session_schema.py`, `session_leases.py`, tests `test_session_store.py`, `test_session_schema.py`, `test_session_recovery.py`, `test_session_workers.py`; extend adapter exports/fixture workers and README.

**Interfaces:** `PostgresSessionStore(dsn, *, namespace, lease_s=60, renew_s=15, ...)` follows existing bounded pool/timeout options and implements SessionStore. `initialize()` is an explicit owner operation; runtime check_ready() never migrates or falls back.

- [ ] Write RED shared conformance and old-role isolation tests. Run core and adapter suites separately to avoid module-name collisions.

```python
def test_old_runstore_needs_no_conversation_grants(old_runtime_dsn):
    store = PostgresRunStore(old_runtime_dsn, namespace="legacy")
    store.check_ready()
    with pytest.raises(StoreUninitialized):
        PostgresSessionStore(old_runtime_dsn, namespace="legacy").check_ready()
```

- [ ] Create only independent conversation version/session/lease/receipt logged tables and schema-v1 initialization/readiness/grants. Runtime grants: schema USAGE; version SELECT; lease/session SELECT/INSERT/UPDATE; receipt SELECT/INSERT. No runtime CREATE/version UPDATE/receipt UPDATE/DELETE. Preserve prosaic_harness RunStore schema/grants and existing CLI defaults.
- [ ] Implement owner/scope-filtered primary reads and short WAL-guarded transactions, database-time lease generations/renewal and scoped revisions using canonical UTF-8 records. Receipt writes are exact-address immutable/idempotent; unknown outcomes carry existing safe StoreUnavailable semantics. No pool connection remains checked out during inference/tools/resume.
- [ ] Run `.venv/bin/python -m pytest adapters/postgres/tests --require-postgres` against owned PG16/18. Cover concurrent initialization/readiness, unknown receipts/markers, cross-worker fencing, late commits, no-authority namespaces, schema privilege failures, WAL/standby routing and payload limits. Selected tests fail missing infrastructure/skips; validate exact-owned cleanup.
- [ ] Review adapter change and installed behavior on Linux AMD64/ARM64. Run full legacy adapter suite as well as sessions; commit.

### Task 8: Public documentation, candidate packaging and release train

**Files:** Create `docs/conversations.md`, `scripts/conversation_smoke.py`; modify `README.md`, `pyproject.toml`, `src/prosaic_harness/__init__.py`, `adapters/postgres/README.md`, `adapters/postgres/pyproject.toml`, `adapters/postgres/src/prosaic_harness_postgres/__init__.py`, `tests/test_distribution_metadata.py`, `adapters/postgres/tests/test_packaging.py`, `adapters/postgres/tests/support/linux_wheel_smoke.py`, `scripts/release_artifacts.py`, `.github/workflows/tests.yml` and `.github/workflows/publish.yml`.

**Interfaces:** Candidate Harness 0.8.0 depends on `b3-prosaic-runtime>=0.9,<0.10`; existing Harness PostgreSQL distribution 0.3.0 depends on `b3-prosaic-harness>=0.8,<0.9`. No Core bump, schema migration to old RunStore, new adapter distribution or new SDK server dependency.

- [ ] Write RED isolated installed-memory/file/PG API smoke tests; no sibling sources, private imports, arbitrary client history roles or invented directory. Include pure construction, duplicate send, failed correction, saved receipt recovery and old Harness behavior.
- [ ] Publish minimal graph-free memory example, file root binding, separate PG initialization/grants, host identity/authorization, request and receipt limits, provisional/committed events, exact workflow refs, retry risk and visible uncertain handoff. Explain retained-session lifecycle and physical overhead separately from the 72 MiB logical record bound.
- [ ] Run full core/adapter suites with prosaic on PATH, builds for core and existing adapter, fresh wheel/sdist consumers, dependency resolution and `pip check`. Independently review entire Harness change; resolve substantive findings with behavior regressions.
- [ ] Save exact source/qualified wheel/sdist hashes and embedded Core/Runtime dependency lineage for Lab. Run the complete required native platform/database lanes; local ARM64 evidence does not substitute for AMD64 CI.
- [ ] Qualify the linked Lab candidate lanes before publishing. Publish Runtime 0.9.0/recorder 0.3.0 first, Harness 0.8.0/store 0.3.0 next, then Lab 0.5.0 manifest/docs. Lab public-index adoption and released-mode matrix must pass before claiming consumers can upgrade. Preserve original artifacts/receipts and prior pending-run recovery evidence.

## Coverage and execution ledger

Tasks 1–3 cover pure admission and record/store guarantees; 4–5 cover ordered history, bounds, provisional streaming, idempotency and every dispatch/receipt crash boundary; 6 covers selections/confirmation and the non-atomic workflow handoff; 7 covers independent shared persistence; 8 plus the linked Lab plan gate installed consumption and release. At implementation time create `2026-10-11-conversation-progress.md` beside this plan to record task commits, exact commands, watched RED/GREEN results, architecture/DB cells, limitations, original receipts and verified cleanup. No implementation test has run during planning.
