# Parallel tool calls across Runtime, Harness and Lab

Date: 2026-11-10. Status: proposed design for review; implementation and release are not authorized by this document.

## Intent and baseline

Ask Cerebro should execute independent service reads from one model response concurrently, then give the model a complete, correctly correlated batch. Runtime owns execution; Harness supplies workflow/session authority and durable adoption; Lab proves real public-SDK use. Application code must not acquire a second model/tool loop.

Reviewed baseline: Runtime 0.9.20, Harness 0.9.14, Harness PostgreSQL 0.4.3, Lab 0.9.13. Core 0.5.0 and Runtime PostgreSQL recorder 0.3.0 remain unchanged. The existing safe-event, result, citation, context-pack, journal, guard and frozen-turn contracts are foundations, not replacements.

These are proposed engineering choices, not preferences already agreed by the maintainer. The requested deliverable is a detailed design and implementation plan. Native implementation followed by independent review remains the preserved execution preference if implementation is subsequently approved.

## Scope and alternatives

Implement bounded concurrency inside a single provider tool batch. Support the existing OpenAI-compatible Chat Completions and Anthropic Messages execution loops, including streaming responses after their complete tool batch passes admission. Support public `run` and `turn`; Harness uses its existing prepared-turn path.

Three approaches were considered:

| Approach | Benefit | Cost / decision |
| --- | --- | --- |
| Execute every tool through a thread pool | Small initial patch | Rejected: silently overlaps writes, callbacks, journals and shared Runtime state. |
| Fully asynchronous Runtime and Harness APIs | Broad future concurrency | Deferred: forces an API/lifecycle rewrite and does not solve authority or recovery by itself. |
| Host-declared independent reads, coordinated by the existing synchronous owner | Reuses current APIs and preserves single-owner state | Recommended first increment; bounded worker threads execute handlers only. |

MCP, sub-agents, provider-hosted tools, speculative argument streaming, concurrent provider requests, parallel workflow nodes and distributed/global worker pools are separate follow-ups. Shipped builtin/CLI tools remain sequential. External `StructuredToolLoop` drivers and native CLI providers reject enabled parallel mode before external work; a singleton `run_tool` rejects a parallel policy rather than advertising batch execution.

## Public configuration

New Runtime module: `src/prosaic_runtime/tool_parallel_contracts.py`.

```python
@dataclass(frozen=True)
class ParallelToolPolicyV1:
    max_concurrency: int = 4
    max_buffered_result_bytes: int = 1_048_576
    max_pending_events: int = 128
    max_pending_event_bytes: int = 65_536

# Appended optional field; existing positional fields retain their positions.
RunPolicy(..., parallel_tools: ParallelToolPolicyV1 | None = None)

# Appended keyword-only declaration; omitted from old descriptors when false.
CustomTool(..., parallel_read: bool = False)
```

Bounds: concurrency is an actual integer in 1..16; buffered result bytes in 1..8,388,608; pending events in 1..2,048; pending event bytes in 1..1,048,576. Reject bool-as-int, nonfinite/unknown fields, mutable/forged policy objects and malformed serialized declarations. Codecs copy bounded finite JSON and never serialize callbacks.

`parallel_read=True` is a trusted host assertion: the handler is read-only, independent of other admitted reads, safe to invoke concurrently including repeated calls to itself, and uses bounded I/O/cooperative cancellation. Require `with_context=True`; `ToolExecutionContext` already supplies the original absolute deadline, cancellation and `remaining_timeout`. Reject a terminal tool declaring this assertion. A declaration does not grant execution, authorization, display, evidence access, citations or a common database snapshot.

Threads target I/O-bound reads, not CPU parallelism. The concurrency cap is per invocation; the embedding service remains responsible for aggregate request concurrency and connection-pool admission.

Only policy plus eligible registration enables overlap. Registration alone retains sequential execution. A parallel policy requires finite `max_provider_requests` and `max_tool_calls`, operation scope and explicit `ToolContractBindingsV1`; event-only and ordinary legacy return values remain supported. Typed results and citations remain independent opt-ins. Capability: `parallel_tool_calls_v1`.

The default `parallel_tools=None` and `parallel_read=False` must be omitted from every existing canonical descriptor, policy document, binding hash and frozen record. Explicitly enabled policy values and true tool declarations are semantic identity material. Different concurrency, bounds or declarations refuse restore/adoption rather than silently changing an admitted execution.

## Single-owner execution architecture

The calling thread is the coordinator. It alone mutates budgets, registry state, guard state, evidence registries, turn capture, transcripts, journal state and event sinks. Worker threads receive owned arguments and per-call context, invoke exactly one trusted handler, normalize its return into a bounded owned outcome, and report a local immutable settlement. They never call a shared `BoundedToolRegistry.execute_message`.

Refactor the current `execute_custom_tool` internals into prepare / invoke / settle helpers. Reuse those helpers through the unchanged sequential wrapper as well as the new coordinator; do not create a second implementation of result validation, authorization or journal signatures. Pure normalization may run on the worker with a call-local outcome collector. All externally supplied callbacks except the handler run on the coordinator: authorization, operation-key resolution, journal claim/commit, guards, display/evidence grants, events and observers.

Internal modules:

- `tool_dispatch.py`: owned call preparation, handler invocation and authoritative settlement shared with sequential dispatch.
- `tool_parallel.py`: ordered admission, bounded windows, cancellation/draining and ordered result reduction.
- `tool_parallel_contracts.py`: public policy, internal immutable call/settlement values and closed versioned schedule codecs.

Do not blindly use `copy_context()`: it shallowly carries references to mutable capture/registry objects. Install a fresh worker event context, cancellation event, immutable scope/accounting attribution and a worker marker. Preserve text withholding. Worker-originated existing events/progress enter the bounded coordinator queue; no user sink or observer runs on a worker. Intercept worker emission before the current `events.emit` observer call, and deliver/observe it once on the coordinator. Do not merely install a queue-backed sink after the observer has already run. Direct reentry into public Runtime execution from a parallel handler is rejected before child provider/tool dispatch in V1. Existing nested execution remains available in sequential mode; concurrent delegates are a separate design.

## Admission, budgets and scheduling

1. Receive the entire provider batch. Preserve existing duplicate-ID, JSON/schema, grants, terminal-singleton and malformed-stream checks. No handler, authorization callback or journal claim may run on a malformed batch.
2. Run existing whole-batch `before_tool` rules and revalidate rewritten arguments. Stable call IDs and invocation-wide indexes follow the final admitted wire order, never worker completion order.
3. In enabled mode, atomically reserve the entire batch's tool-attempt allowance against invocation and all enclosing `ExecutionBudget` objects before any callback/claim. Acquire enclosing locks in the existing stable order; include the invocation counter in the same commit. Denial changes no counter and dispatches nothing. This deliberately differs from legacy sequential prefix execution and applies only to enabled mode.
4. Counters remain actual admitted attempts, not speculative callbacks. Reserve distinct pending slots, convert each once at authorization/refusal/claim dispatch admission, and release unconsumed slots on stop. Other tool dispatches check consumed plus pending slots, so another branch cannot steal the reserved tool capacity. Provider accounting and token reservation remain independently authoritative. Neither replay nor refusal gets a free attempt; neither is double charged. A provider response already obtained remains counted if batch admission fails.
5. Partition admitted calls into maximal contiguous runs of eligible custom reads, separated by serial barriers. Within a read run use fixed wire-order windows of at most `max_concurrency`. Do not refill a window merely because its fastest call finished: settle the window and apply ordered guards before opening the next window. This bounds work admitted before an after-tool stop.
6. Preflight the declared retained result bound for every read window before dispatching any batch member: `sum(tool.max_result_bytes + 1536)` must fit `max_buffered_result_bytes`. This is a bound on retained encoded outcomes/metadata, not Python RSS or arbitrary memory allocated by trusted callbacks. Existing event, evidence, request, turn and receipt ceilings also apply independently. Oversized admission dispatches zero callbacks; actual malformed/oversized returns still use existing outcome rules.
7. Immediately before each start, coordinator checks deadline/cancellation/current ownership, then per-tool execution permission and journal authority. Dispatch authorized members of the fixed window in wire order. Process all returned settlements even after a fatal condition. Never launch later windows or barriers after stop.
8. Unmarked tools, builtin tools, context-pack readers and shipped CLI registrations are barriers. All earlier windows settle and reduce before a barrier starts; the barrier settles before later calls start. Do not infer safety from a name, description, provider annotation, JSON schema, result shape or model claim.

One model response is one tool round irrespective of windows. Wait for all accepted results before the next provider request. OpenAI tool messages retain their matching IDs; Anthropic gets one next user message containing the batch's tool-result blocks before text. No provider flag alone grants local concurrency. Retain existing provider request bytes: V1 does not add `parallel_tool_calls` or `disable_parallel_tool_use` automatically, because both parsers already accept batches and OpenAI-compatible servers vary.

### Worker control and start handshake

Control delivery is independent of the progress queue. Each submitted slot owns one `Future` terminal settlement and readiness/permit events; there are at most `max_concurrency` active slots. A full progress queue cannot block or drop readiness, handler-entry classification or the terminal settlement. Progress uses nonblocking bounded insertion; overflow sets the stop signal and suppresses subsequent progress. The coordinator prioritizes terminal settlements, drains started callbacks and checks boundaries at waits no longer than 50 ms (excluding time spent inside trusted callbacks). Futures/control state and owned result bytes remain covered by window capacity; there is no unbounded fallback queue.

A worker first announces ready and waits for a coordinator permit. Only after authorization, a successful journal claim if configured, readiness and the final boundary check does the coordinator emit `tool_started`. If start delivery succeeds, dispatch is committed: release the permit, and the worker must enter the handler exactly once even if cancellation arrives immediately afterward; its context reports that cancellation so the handler can stop cooperatively. This preserves the existing start-before-handler boundary while never emitting starts for merely queued jobs. The wrapper records actual handler entry in its terminal settlement.

If cancellation/start-sink failure occurs after journal claim but before successful start delivery, abort the waiting worker without calling the handler. The consumed attempt remains counted; the claimed journal stays conservatively uncertain under the existing protocol. Schedule evidence records `handlerEntered: false` and `journalState: claimedUncertain`; it must not label this `notStarted` or automatically reclaim it. With no journal claim and no committed dispatch, a cancelled call is genuinely `notStarted`. A replay records `handlerEntered: false` and `journalState: replayed` and emits no start. An unexpected worker failure after dispatch commitment is uncertain even if entry cannot be proved.

## Journals, failures and cancellation

Journal APIs and signatures stay `tool-journal-v1`; journal methods remain on the coordinator and therefore need no new thread-safety promise. Keep authoritative completion before fallible projection/events. A read declaration never makes unknown execution retryable.

| Condition | Required behavior |
| --- | --- |
| Two calls share an in-flight operation namespace/key and signature | Keep distinct call IDs/attempt slots; second waits for the locally owned first settlement, then reclaims through the journal and obtains authoritative replay. No second handler. Never wait on an unowned uncertain claim. |
| Same operation key, different signature | Identity conflict stops new admission; drain any started sibling and retain its known outcome. No silent aliasing or redispatch. |
| Journal returns uncertain, claim/commit acknowledgement is lost, handler raises unexpectedly, or result cannot establish completion | Existing unknown-effect/reconciliation semantics stop further dispatch. Preserve completed siblings; do not synthesize success or retry. |
| Controlled `ToolFailure` | Preserve completed failure and existing recovery-policy behavior. If the current policy requires stop, started siblings may already have completed; no next window. Otherwise return one bounded error result for that call. |
| Authorization denied | No handler/start event/journal claim for that call; preserve the existing denied outcome and stop policy. Other already-started calls drain. |
| After-tool rule returns terminal `STOP` | Apply in call order. Later members of the current window may already have completed; retain their private outcomes, withhold unapproved model evidence and stop later windows/provider dispatch. |
| After-tool rule returns a repairable bounded `ruleFeedback` message | Preserve existing behavior: reduce that message in order, admit later windows unless another stop occurs, and allow the next provider request only under the existing explicit repair allowance and remaining budgets. Refused data does not become seen facts or citable evidence. |
| Cancellation, deadline, ownership loss, observer/event failure | Set worker cancellation, stop dispatch, cancel jobs not started and drain/join started handlers. Commit authoritative known settlements before final failure; do not run a final provider request. |
| Running callback ignores cancellation | Invocation waits for that callback to return. No unsafe thread kill, detached background completion or hard wall-clock timeout guarantee. Host code must impose I/O timeouts. |
| Failure after known completion | Private receipts/journals retain completion even when display, guards, evidence limits or citation acceptance fail. No completed tool becomes “not started.” |

If multiple fatal conditions occur, settle everything first. Existing journal/unknown-effect failures dominate observation failure, which dominates cancellation/timeout, which dominates guard/evidence/citation rejection; ties of the same class select the lowest call index. Keep original safe failure-code families and record each per-call outcome; never expose raw exceptions.

Coordinator polling must continue processing worker messages and checking cancellation while it drains; Harness lease renewal remains active. No handler continues after the Runtime invocation returns. User events already queued may be discarded on fatal sink failure; authoritative journal settlement must still run.

## Events, guards and citations

Keep existing `tool_started` and `tool_completed` meanings and safe `toolEventV1` projection. Start follows actual admission and journal dispatch/replay classification; queued/not-started work produces no fake start. Journal replay produces no new start.

Add one bounded observational event, `tool_execution_settled`, only in enabled mode. Its `parallelToolV1` object contains version 1, batch ID, stable call ID/index, fixed settlement state (`completed`, `replayed`, `uncertain`, `notStarted`), safe `ToolOutcome` code (nullable when a call was cancelled before any attempt outcome), `handlerEntered`, `journalState` (`notUsed`, `claimedUncertain`, `replayed`, `committed`) and duration. Validate state/entry/journal combinations; `notStarted` never describes an uncertain claim. Cap the encoded object at 1 KiB. No arguments, outputs, display fields, source metadata, tenant/actor strings or citation bodies. This lets a fast sibling report actual settlement before an earlier slow sibling's guard processing. It is not answer acceptance or proof of model delivery. Emit no settlement claim without authoritative callback/journal classification.

Existing `tool_completed` with approved result display follows ordered after-tool validation/projection; it may arrive later than the new observation. Keep start/settlement/projection causal order per call. Callback delivery is serialized on the coordinator; queue overflow is a safe observation failure, not unbounded accumulation or silent loss of authoritative completion. General telemetry receives only the explicitly approved lifecycle/closed-code fields.

Reduce after-tool guards, guard facts, result repairs, model messages, evidence declarations and citation registry staging in wire order, after each window settles. Private raw outcomes may be captured earlier; they never automatically become model-visible or citable. Freeze known call outcomes and registry arrays in call-index order. Keep actual timings/settlement order only in observational schedule evidence, excluded from semantic identity. For identical scope, admitted calls, outcomes and replay classification, changing finish order cannot change guard inputs, next-request message order, evidence IDs or registry digest.

The existing encoded-request/HTTP-response proof remains the only Runtime-observed model-delivery proof. Permission is rechecked for model use, citation acceptance and retained reads. No synthetic delivery for successful tools whose results never reached another provider request. Context packs keep their exact captures and permissions; read overlap does not imply a common source revision or snapshot.

## Durable formats and Harness authority

Enabled Runtime turns use encoding `conversation-turn-v5`, frozen input version 3 and turn evidence version 4. Required `parallelToolsV1` binding pins the policy and scheduler contract; evidence pins admitted call order, attempt/settlement states and correlation. Existing `toolContractV1` remains unchanged and required for enabled mode. Default-off continues existing encoding/versions byte for byte; CompletedTurn message version and ToolOutcome/journal outer protocols stay unchanged.

Harness enabled records extend the role-aware tool-contract route: run state version 5, workflow receipt version 4, session state and receipt version 5. Require explicit `ToolContracts`, which may be event-only with ordinary tool returns. Context-pack composition remains supported. New readers accept every old supported version without rewriting records; old readers refuse new versions. Feature-off never upgrades an existing run/session. Preserve original scopes, semantic bindings, receipts and accepted answer on adoption.

Workflow authority:

```python
WorkflowPolicy(..., parallel_tools=ParallelToolPolicyV1(max_concurrency=4))
```

An agent node may request `parallel_tools: {max_concurrency: 2}`; omitted means sequential. Host policy is a ceiling, not an automatic grant to every node. The closed node map accepts only `max_concurrency`, an integer 1..16 no larger than the host ceiling; other bounds come unchanged from the host. Tool/human/end nodes reject the field. Markdown node declarations and WorkflowFactory JSON use the same schema and admission. Model-proposed YAML/JSON cannot create a host grant or mark a handler parallel-safe. ConversationBindings use an explicit `RunPolicy.parallel_tools` and existing registration checks; interpretation remains tool-free/sequential and workflow bridge handoffs retain the selected admitted policy.

Pin policy, true tool declarations, scheduler capability and store capability in admission fingerprints. Readmit before every dispatch and resume. A changed policy, handler version, node declaration or registration refuses recovery. Accepted receipts adopt without provider/handler calls; interrupted dispatched invocations retain existing reconciliation rules rather than restarting the whole batch. New workers cannot reclaim an uncertain handler through a lease takeover.

Memory/File/PostgreSQL stores advertise `parallel_tool_calls_v1` only after explicit storage-contract enablement. Extend owner-only `initialize` with `parallel_tools=True`, default false, and add `migrate_parallel_tool_storage()`; migrate known contracts monotonically while preserving all existing JSON bytes, constraints, grants and fencing. File run contract marker advances 3 to 4; file session marker advances 4 to 5. PostgreSQL run storage contract advances 3 to 4 and session schema/storage contract 4 to 5. No new tables, replacement journals, column widening or automatic worker DDL. Readiness checks reject a worker role with migration privileges. PostgreSQL adapter changes are required even if data columns remain unchanged.

## Lab and verification

Add a copyable `parallel-tools` blueprint using public Runtime/Harness APIs, thread-safe bounded fake read services, exact releases/candidate manifests and the existing event/citation types. Applications wrap their own read tools; no Lab scheduler or model/tool-loop copy.

Add 16 logical real-stack cases over both provider wires: 32 required cases per AMD64/ARM64 and PostgreSQL 16/18 cell. Scenarios:

1. Prove two handler intervals overlap using deterministic rendezvous.
2. Prove concurrency cap and fixed-window admission.
3. Reverse finishes; verify ordered guard facts/history/citations.
4. Serial tool barrier between read groups.
5. Malformed later call and budget shortfall each dispatch zero handlers.
6. Current authorization denial/revocation before a queued start.
7. Cancellation drains callbacks, retains known commits and dispatches no next window.
8. Unknown claim or lost acknowledgement fences recovery.
9. Duplicate operation key yields one handler and authoritative replay.
10. Controlled failure follows recovery policy without rerunning siblings.
11. Guard stop after sibling completion retains private facts but exposes no unapproved evidence.
12. Safe event delivery is serialized and fast settlement carries no payload.
13. Evidence/current permissions and actual provider delivery control citations.
14. Bounded results/events fail without erasing known completion.
15. Fresh controller adopts accepted receipt with zero provider/tool work.
16. Lease takeover and foreign owner cannot dispatch or expose the original owner's work.

Retain all eleven current lanes (370 cases/cell). A coherent new feature family adds `parallel-tools` for 402 cases/cell; previous public families keep their original gate inventory. Mixed or partially published families fail closed. Candidate qualification uses exact original SDK wheels and unmodified Core/recorder archives; do not switch active public manifests before separate publication/adoption authorization.

Unit tests must use barriers/events and controlled finish orders, not timing ratios. Test actual callback overlap, one owner thread for all non-handler callbacks, separate concurrent invocations, result/error association, identical evidence under finish permutations, nested budget reservation contention, worker reentry refusal, journal failure after sibling completion, unsupported providers and legacy golden bytes. A diagnostic latency report may measure real intervals but is not a flaky pass/fail speed threshold.

Use source suites, isolated installed wheel consumers and rebuilt-source Lab consumers; Linux AMD64/ARM64, macOS Intel/ARM, Python 3.11–3.13 for SDKs; Lab Python >=3.12; PostgreSQL 16/18; dependency floors. No live/paid inference without separate authorization. No weakening of CI gates or release workflows in this implementation.

## Backward compatibility and rollout

- Preserve legacy sequential prefix-budget behavior, call ordering, errors, tool wire values, safe-event/result/citation formats and old identity fixtures with both new options absent.
- Existing unmarked handlers, authorizers, event sinks and journal objects acquire no new threading requirement.
- Enabled callers knowingly permit already-started siblings to finish after another sibling fails. They do not gain preemption, snapshot isolation or exactly-once execution.
- Explicitly enabled frozen bindings and durable versions require new readers; deployments upgrade readers/adapter and run owner migrations before enabling parallel nodes.
- Current accepted sessions/runs remain under their admitted policy. Start new parallel-enabled records instead of mutating an in-flight sequential execution.
- Implementation order: Runtime contract/dispatch, Runtime evidence, Harness admission/storage/recovery, Lab adoption. Preserve native execution and independent review; stable version assignment, PR publication, merges and releases are separate later instructions.

## Sources and why they matter

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling#parallel-function-calling): a response may contain multiple function calls; provider batch generation and local execution authority are separate.
- [Anthropic parallel tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use): application chooses execution order; return correlated results together in the next user message. Independent reads are the recommended parallel case.
- [Python 3.11 futures](https://docs.python.org/3.11/library/concurrent.futures.html#concurrent.futures.Executor.shutdown): cancellation does not kill running callbacks; shutdown/join behavior must be explicit.
- [Python context variables](https://docs.python.org/3/library/contextvars.html): worker contexts must avoid accidentally sharing mutable invocation state.

Current provider APIs also discuss asynchronous/background tools and programmatic execution. Those are distinct from this bounded join-before-next-model design and are not required to deliver Cerebro's parallel reads.
