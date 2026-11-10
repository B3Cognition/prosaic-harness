# Parallel Tool Calls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement natively, task by task; the maintainer's native execution preference is preserved. Obtain an independent whole-branch review before integration. Steps use checkbox (`- [ ]`) syntax for tracking. This document is a plan, not implementation or release authorization.

**Goal:** Execute explicitly admitted independent tool reads concurrently without changing default sequential execution or weakening durable recovery, guards, safe events or citations.

**Architecture:** A synchronous coordinator retains ownership of all Runtime/Harness state and externally supplied callbacks except handlers. Bounded workers execute handlers and return immutable settlements; fixed windows settle before results are reduced in call order. Runtime supplies the engine, Harness pins policy and durable versions, and Lab verifies public consumers across both API protocols.

**Tech Stack:** Existing Python SDKs (Python 3.11–3.13), standard-library threads/queues/contextvars, existing JSON/schema codecs and psycopg adapter; Lab Python >=3.12, PostgreSQL 16/18, Docker/Podman and synthetic HTTP providers. No new concurrency dependency.

**Spec:** [Parallel tool calls design](../specs/2026-11-10-parallel-tool-calls-design.md). Read both documents before executing a task.

## Global constraints

- Baseline: Runtime 0.9.20, Harness 0.9.14, Harness PostgreSQL 0.4.3 and Lab 0.9.13; Core 0.5.0 and Runtime PostgreSQL 0.3.0 stay unchanged.
- Public capability `parallel_tool_calls_v1`; `RunPolicy.parallel_tools=None` and `CustomTool.parallel_read=False` are omitted from legacy canonical material.
- `ParallelToolPolicyV1`: concurrency default 4, valid 1..16; retained-result bytes default 1,048,576, valid 1..8,388,608; pending events default 128, valid 1..2,048; pending-event bytes default 65,536, valid 1..1,048,576. Actual integers only.
- Parallel mode requires finite provider/tool caps, explicit operation scope and `ToolContractBindingsV1`. Eligible tools require `with_context=True`, host `parallel_read=True` and no terminal completion. Ordinary return values remain valid.
- Handler workers only. Authorization, keys, journal calls, budget admission, guards, evidence, events/observers, capture, transcripts and persistence remain on the coordinator.
- Fixed windows within contiguous eligible read runs; serial barriers stay in original order. No next provider request before all results are accepted. No promise of common-source snapshot or hard callback preemption.
- Journal outer protocol/signatures, `ToolOutcome` v1 and CompletedTurn message format remain unchanged. Never automatically retry an uncertain or completed handler.
- Enabled Runtime: `conversation-turn-v5`, frozen input version 3, turn evidence version 4. Enabled Harness: run 5, workflow receipt 4, session 5, session receipt 5. Default-off uses old versions/bytes.
- Storage migration is explicit and owner-only: file/PG run contract 3→4, session 4→5; no new tables, widened columns, automatic worker DDL or rewritten historical records.
- Lab keeps eleven current lanes/370 cases per cell and adds 32 parallel cases for 402 only in a coherent new family. Existing manifests, benchmark history and original SDK archives remain immutable.
- No MCP, sub-agents, workflow-node fanout, concurrent providers, asynchronous public API rewrite, detached callbacks or release-workflow changes. No live/paid inference.
- Implement on clean isolated branches from then-current main. Review the existing worktrees first; do not reset maintainer working copies. Development version selection belongs to implementation kickoff: choose distinct unpublished versions, record exact commit/wheel hashes and never replace a published version. Public adoption, PRs/merges and releases require separate instructions.

## Review focus

1. Fast sibling completes before a slow failing callback: its authoritative journal outcome survives later cancellation, hook failure and lease loss (Tasks 4, 5, 9).
2. Two tool batches or nested budget holders contend for the final allowance: consumed plus pending slots never exceed any enclosing cap, and no reservation is charged twice (Task 3).
3. Repeated operation key inside one window: the second call waits/replays through the owned journal, while a foreign uncertain claim never becomes dispatch authority (Task 4).
4. A valid old checkpoint is opened after new fields/classes exist: all legacy bytes/hashes and sequential prefix-budget behavior remain exact; new versions fail on old readers (Tasks 1, 6–9).
5. Worker code emits events, reenters Runtime or returns mutable data: the caller sink remains single-threaded, authority does not leak, and late mutation cannot change evidence or accepted output (Tasks 2, 4, 5).

## File and responsibility map

All paths are relative to their repository. New filenames below are decisions; follow existing nearby modules for style.

| Repo | New modules | Main existing integration points |
| --- | --- | --- |
| Runtime | `tool_parallel_contracts.py` (policy/schedule codecs), `tool_dispatch.py` (shared custom-tool phases), `tool_parallel.py` (coordinator) under `src/prosaic_runtime/` | `tools.py`, `policy.py`, `tool_registry.py`, `runtime.py`, `execution.py`, `budgets.py`, `execution_budget.py`, `events.py`, `telemetry.py`, `turn_capture.py`, `tool_evidence.py`, `conversation.py`, `conversation_preparation.py`, `frozen_turns.py`, `adapter.py`, `direct_tool.py`, `structured_tools.py`, `__init__.py` |
| Harness | `src/prosaic_harness/parallel_tools.py` (admission, version material and receipt validation) | `factory.py`, `graph_admission.py`, `workflow.py`, `engine.py`, `discovery.py`, `conversation_bindings.py`, `conversation.py`, `session_contracts.py`, `contracts.py`, `tool_contract_execution.py`, `session_tool_contracts.py`, Memory/File stores, `context_packs/file_namespace.py`; adapter `schema.py`, `session_schema.py`, `pack_schema.py`, `store.py`, `session_store.py`, `cli.py` |
| Lab | `src/prosaic_integration_lab/parallel_tools.py` (public consumer scenarios), `lab_runner/parallel_tools.py` (owned runner), `lab_runner/blueprints/parallel_tools/` (copyable host) | `lab_runner/gates.py`, `__main__.py`, `stack.py`, blueprint registry, packaging inventory, candidate curation/install audit, `scripts/required_acceptance.py`, `conversation_distribution_smoke.py`, existing required-acceptance workflow |

## Task 1: Public Runtime contract and exact default-off identity

**Files:** create Runtime `src/prosaic_runtime/tool_parallel_contracts.py`, `tests/test_parallel_tool_contracts.py`, `tests/fixtures/parallel_tools/legacy-identities.json`; modify `policy.py`, `tools.py`, `conversation_preparation.py`, `__init__.py`.

**Interfaces:** export `ParallelToolPolicyV1(max_concurrency=4, max_buffered_result_bytes=1048576, max_pending_events=128, max_pending_event_bytes=65536)` with owned `to_dict()` / `from_dict(value)`. Append `RunPolicy.parallel_tools: ParallelToolPolicyV1 | None = None`; append keyword-only `CustomTool.parallel_read: bool = False`. New policy codec uses camel-case fields plus `version: 1`. Tool descriptor emits `parallel_read: true` only when true.

- [ ] Capture released fixtures before modifying canonicalization: ordinary/event-only/typed descriptors, `RunPolicy` documents, prepared context identity and frozen input. Keep fixture source release/commit in the JSON.
- [ ] Add tests `test_parallel_policy_bounds_and_closed_codec`, `test_parallel_read_requires_context_and_refuses_terminal`, `test_absent_parallel_fields_preserve_released_bytes`, `test_enabled_limits_and_tool_declaration_change_identity`. Assert every bound above, including bool, unknown keys, forged nested objects and independent defensive copies.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_parallel_tool_contracts.py`; expect new API tests to fail before implementation.
- [ ] Implement the public contract and one shared policy canonicalizer used by preparation/restore; omit None/false before encoding, not by post-hoc hash rewriting. Add capability only when execution Tasks 4–6 are wired; registration alone does not advertise execution.
- [ ] Run new tests plus `tests/test_custom_tools.py tests/test_tool_contract_turns.py tests/test_tool_contract_legacy.py`; expect all pass and unchanged fixtures. Commit `feat: define opt-in parallel read policy and registrations`.

## Task 2: Share custom-tool prepare/invoke/settle phases without behavior drift

**Files:** create Runtime `src/prosaic_runtime/tool_dispatch.py`, `tests/test_tool_dispatch_phases.py`; modify `tools.py`, `tool_registry.py`, `direct_tool.py` only at dispatch seams.

**Interfaces:** internal frozen `PreparedToolCallV1` owns `call_id`, invocation-wide `call_index`, `batch_index`, registered tool, owned arguments, `ToolExecutionContext` and journal references. Internal frozen `WorkerSettlementV1` owns call identity, bounded normalized outcome or safe failure code, `handler_entered`, `started_at`, `finished_at`. Neither type is a public authority token.

Functions: `prepare_custom_tool_call(tool, raw_arguments, *, call_id, call_index, batch_index, options) -> PreparedToolCallV1 | WorkerSettlementV1`; `invoke_prepared_tool(call: PreparedToolCallV1) -> WorkerSettlementV1`; `settle_custom_tool_call(call, settlement, *, on_completion) -> WorkerSettlementV1`. Preparation owns current authorization/key/claim checks; invocation owns handler and pure normalization; settlement owns journal commit and authoritative completion. `execute_custom_tool` remains the existing public wrapper using these phases sequentially.

- [ ] Add tests covering ordinary/typed returns, denied auth, controlled failure, unexpected exception, journal dispatch/replay/uncertain/lost-commit, terminal tools, failed start/completion sinks and late mutation. Assert old return envelopes, outcome codes, callback order and signatures exactly.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_tool_dispatch_phases.py`; expect absent helpers to fail.
- [ ] Extract shared phases while keeping legacy callbacks on the caller thread. Terminal/direct behavior must stay on the old sequential wrapper; no new parallel branch yet.
- [ ] Run phase tests and `tests/test_tool_effects.py tests/test_direct_tool.py tests/test_tool_contract_review_regressions.py tests/test_controlled_tool_failure.py`; expect all pass. Include assertions that known completion precedes a failing hook.
- [ ] Commit `refactor: share custom tool admission and settlement phases`.

## Task 3: Atomic tool-batch allowance reservations

**Files:** modify Runtime `budgets.py`, `execution_budget.py`, `runtime.py`; create `tests/test_parallel_tool_budgets.py`.

**Interfaces:** internal `reserve_tool_batch(invocation: InvocationBudget, enclosing: tuple[ExecutionBudget, ...], size: int) -> ToolBatchReservationV1`. Reservation has `start(index: int) -> ToolAttemptPermitV1`, `release_unstarted() -> None`, read-only admitted/consumed/released counts. A permit is internal, scoped to this reservation/call and consumable exactly once; the registry must not call ordinary `before_tool_dispatch` again for it.

- [ ] Add `test_two_call_parallel_batch_with_cap_one_dispatches_nothing`, `test_default_sequential_batch_still_executes_first_call_with_cap_one`, `test_parent_child_reservations_commit_atomically`, `test_competing_invocations_cannot_steal_pending_slots`, `test_cancel_releases_only_unstarted_slots`, `test_refused_and_replayed_calls_are_counted_once`.
- [ ] Use a barrier with two contenders and one remaining parent slot; assert at most one successful reservation, no negative pending count, no partial debit on denial. Run `.venv/bin/python -m pytest -q tests/test_parallel_tool_budgets.py`; expect failure.
- [ ] Add invocation lock/pending counts and enclosing pending tool counts. Use one ordered-lock transaction to validate all relevant tool caps and reported-usage admission before any reservation; convert pending to consumed before authorization/refusal/claim admission; release only unused pending slots. Preserve provider/token reservation algorithms and existing sequential counters.
- [ ] Run new tests plus existing nested-budget/accounting suites selected from `tests/` by `rg --files tests | rg '(budget|nested|accounting)'`; execute those exact files, then record the list. Expect no overspend/double debit and existing sequential tests unchanged.
- [ ] Commit `feat: reserve parallel tool attempts atomically`.

## Task 4: Bounded handler coordinator, barriers and authoritative draining

**Files:** create Runtime `src/prosaic_runtime/tool_parallel.py`, `tests/test_parallel_tool_scheduler.py`, `tests/test_parallel_tool_recovery.py`; extend internal contracts in `tool_parallel_contracts.py`, dispatch phases and registry seam.

**Interfaces:** `ParallelToolCoordinator(policy, *, check_boundary, reservation, dispatch, reduce, emit)` is invocation-local. `execute(calls: tuple[dict, ...]) -> ParallelBatchResultV1`; the result owns ordered messages, stop/failure classification and bounded schedule evidence. `dispatch` consumes Task 2 phases and Task 3 permits; `reduce(call, settlement)` is a coordinator callback supplied by Task 5. Policy/calls are admitted before construction. The coordinator is not exported as an alternative application loop.

- [ ] Add deterministic tests: two reads rendezvous before either is released; active handlers never exceed 2; a fifth read does not enter before the first two-read window reduces; `[read A, serial B, read C]` preserves barriers; no user callback other than handlers runs off owner thread.
- [ ] Add journal tests for same-key/same-signature local wait then replay, different signature conflict, foreign uncertain claim, lost acknowledgement, and a fast completed sibling followed by a slow exception. Add cancellation tests proving the invocation does not return until started callbacks settle and no next window starts.
- [ ] Add worker reentry, event-queue overflow, malformed/oversized output, mutated result alias, two concurrent invocation-isolation start-permit handshake tests (cancel after claim before start; failing start sink; cancel after successful start must enter the handler once), and fixed failure-priority tests. Run `.venv/bin/python -m pytest -q tests/test_parallel_tool_scheduler.py tests/test_parallel_tool_recovery.py`; expect failure.
- [ ] Implement lazy per-invocation bounded threads, fixed windows, per-slot Future/readiness/permit control state and a separate bounded nonblocking progress queue; coordinator alone claims/commits journals. A full progress queue must not block or drop terminal settlements: set stop, suppress more progress, drain Futures first. Poll boundaries at waits <=50 ms. Implement the spec's claim/start/permit state machine; pre-start aborted claimed work remains uncertain and counted, never retryable `notStarted`. Keep owned in-flight operation-key mapping; recheck permission before replay admission. Install fresh worker context and reject Runtime reentry before child dispatch. Drain all started calls after any failure, settle known commits and join before returning.
- [ ] Run the new tests repeatedly under all explicitly controlled finish permutations, not probabilistic sleeps. Expect deterministic order and zero leaked workers/ambient contexts. Commit `feat: coordinate bounded parallel read windows safely`.

## Task 5: Integrate provider loops, ordered rules, safe progress and citations

**Files:** modify Runtime `execution.py`, `runtime.py`, `tool_registry.py`, `events.py`, `telemetry.py`, `tool_event_contract.py`, `tool_evidence.py`, `turn_capture.py`; create `tests/test_parallel_tool_wires.py`, `test_parallel_tool_events.py`, `test_parallel_tool_citations.py`.

**Interfaces:** reuse the existing whole-batch `before_tools`, `after_tool`, TurnCapture and EvidenceRegistry APIs on the owner thread. Extract an ordered per-call reduction helper from the existing loop and supply it as Task 4 `reduce`; it returns one accepted tool message or the existing stop sentinel. New event `tool_execution_settled` owns only the spec's <=1 KiB `parallelToolV1` object. `Result.metadata['parallel_tools_v1']` owns schedule evidence, with no callbacks or raw display payload.

- [ ] For both wires and streaming/nonstreaming, queue a valid multi-call batch with reversed handler finishes. Assert IDs and call indexes match admitted order, after-tool guard facts and request messages are ordered, and Anthropic returns all results in one next user message before text.
- [ ] Assert a malformed later call, invalid rewritten arguments or insufficient batch reservation causes zero handler/auth/key/journal callbacks. Assert serial mode's existing prefix behavior still passes `tests/test_conversation_tool_batches.py`.
- [ ] Assert fast settlement observation is delivered before the slow call finishes, contains no result/argument/display/source data, and all sinks run on the owner thread. Existing projected `tool_completed` follows ordered guards; replay has no fake start. Intercept worker emission before observer delivery and assert the owner observer sees each event exactly once. Failing sink/overflow retains all known sibling completions.
- [ ] Assert finish-order permutations preserve evidence IDs/digest and model-visible history for fixed outcomes/replay classification. Test repairable after-tool `ruleFeedback` separately from terminal `STOP`: feedback preserves the existing bounded repair/provider continuation and counts, while STOP blocks later windows. Assert guard-edited, refused, unsent, compacted or currently revoked evidence never becomes citable; guarded/citation-enabled drafts stay withheld. Run the three new test files; expect failure before integration.
- [ ] Wire the coordinator only when policy is enabled; preserve old provider payload flags and exact default-off loop. Settle capture immediately but freeze index-ordered arrays; run guards/staging/history only in ordered reduction. Add closed telemetry allowlists for new observations; reject native/structured/direct unsupported combinations before external work. Advertise capability after working integration.
- [ ] Run new tests plus all `test_tool_contract_*.py`, `test_conversation_tool_batches.py`, structured/direct/terminal and provider conformance tests. Expect both wires correct with zero cross-call leakage. Commit `feat: integrate parallel reads with guarded tool evidence`.

## Task 6: Runtime frozen formats and installed compatibility

**Files:** modify Runtime `conversation.py`, `conversation_preparation.py`, `frozen_turns.py`, `turn_capture.py`, `adapter.py`, `__init__.py`, `scripts/tool_contract_smoke.py`; create `tests/test_parallel_tool_turns.py`, `tests/test_parallel_tool_installed.py`, `tests/fixtures/parallel_tools/formats.json`; document `docs/parallel-tools.md` and README capability table.

**Interfaces:** enabled frozen input v3/encoding `conversation-turn-v5` and evidence v4 add required `parallelToolsV1` while preserving `toolContractV1`. Existing `FrozenTurnInput`, `TurnEvidence` and restore entry points accept the new exact versions. `parallel_tools_v1` observation is not authority to reconstruct a binding.

- [ ] Add fixtures for disabled ordinary/tool-contract/pack turns and enabled parallel turns. Assert None/false stays byte-identical, enabled values change context identity, policy/tool/bounds drift refuses restore, old formats do not silently gain concurrency, and old readers reject new enabled formats.
- [ ] Test partial failure with completed siblings, record-capacity failure and stale citation permissions after restore; assert complete known outcomes retained within existing bounds and no synthetic provider delivery. Run `.venv/bin/python -m pytest -q tests/test_parallel_tool_turns.py`; expect failure.
- [ ] Implement strict new codecs and admission/capability checks without upgrading historical documents. Ensure `run` returns the bounded schedule sidecar and `turn` provides both new durable frames and existing accepted CompletedTurn history.
- [ ] Commit the SDK code and its Runtime README/parallel-tools documentation, then build candidate archives once for that committed head with the existing artifact builder and record commit/hash receipt. Use those original bytes in an isolated wheel environment; run `test_parallel_tool_installed.py` with `python -I -m pytest -o pythonpath=tests`, plus existing tool-contract smoke. Document exact preparation commands from current repository tooling rather than rebuilding wheels for each consumer.
- [ ] Run the full relevant Runtime source suite and installed/provider qualification checkpoint. Expect green legacy fixtures and new surface. The source commit from the preceding step is `feat: version parallel turn evidence and restore bindings`; fixes require a new source commit and newly identified candidate bytes, never replacement of a qualified archive. Do not assign a stable release or dispatch a release workflow.

## Task 7: Harness host ceilings, per-node selection and immutable admission

**Files:** create Harness `src/prosaic_harness/parallel_tools.py`, `tests/test_parallel_tool_bindings.py`, `tests/test_parallel_tool_workflow.py`; modify `factory.py`, `graph_admission.py`, `workflow.py`, `engine.py`, `discovery.py`, `conversation_bindings.py`, `tool_contract_execution.py`, `__init__.py` and existing Markdown node schema integration.

**Interfaces:** append `WorkflowPolicy.parallel_tools: ParallelToolPolicyV1 | None = None`. Agent-node closed field `parallel_tools: {max_concurrency: int}` requests <= host ceiling; all other bounds inherit host policy. `parallel_material(workflow, runtime=None) -> dict` emits `{}` when absent and versioned admission material otherwise; `parallel_policy(workflow, step_name) -> ParallelToolPolicyV1 | None` narrows concurrency. ConversationBindings consume existing `RunPolicy.parallel_tools`, with explicit ToolContracts and Runtime capability required. Interpretation is always sequential/tool-free.

- [ ] Test host-none + proposed parallel node fails, host ceiling 4/node 2 succeeds, node 5 fails, omitted node is sequential, non-agent nodes reject the field, and Markdown/YAML/WorkflowFactory JSON have identical admission. Forged tool schema/description cannot mark an unregistered handler safe.
- [ ] Test changes to policy bounds, true tool declaration, handler version or model-proposed node request change fingerprint/refuse readmission; absent new fields preserve old workflow/session identity. Source admission must call zero auth/source/provider/handler/journal callbacks.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_parallel_tool_bindings.py tests/test_parallel_tool_workflow.py`; expect missing admission APIs to fail.
- [ ] Implement host ceiling and per-node narrowing through the existing `_invocation_policy` and role-aware prepared-turn route. Require existing ToolContracts but do not force typed returns or citation mode. Reject unqualified Runtime/adapter/store capabilities before dispatch, and pass no policy into interpretation or direct-tool nodes.
- [ ] Run new tests plus tool-contract workflow/binding, context-pack node authoring, workflow factory and conversation admission suites. Expect no callback work during admission and unchanged old hashes. Commit `feat: admit per-node parallel read policies`.

## Task 8: Harness durable frames and explicit storage enablement

**Files:** modify Harness `parallel_tools.py`, `contracts.py`, `session_contracts.py`, `session_codec.py`, `tool_contracts.py`, `session_tool_contracts.py`, `run_store.py`, `memory_session_store.py`, `file_store.py`, `file_session_store.py`, `session_context.py`, `context_packs/records.py`, `context_packs/workflow_records.py`, `context_packs/file_namespace.py`; adapter `schema.py`, `session_schema.py`, `pack_schema.py`, `store.py`, `session_store.py`, `cli.py`. Create `tests/test_parallel_tool_stores.py`, `adapters/postgres/tests/test_parallel_tool_stores.py`, `tests/fixtures/parallel_tools/storage-versions.json`.

**Interfaces:** new enabled records: run 5, workflowReceipt 4, session 5, sessionReceipt 5; all previous formats remain readable without rewriting. All stores expose `parallel_tool_calls_v1` only after explicit opt-in. Extend `initialize(..., parallel_tools=False)` and add `migrate_parallel_tool_storage()` to run/session owners. Memory stores receive the same explicit constructor/initialization opt-in as their current tool-contract storage option.

- [ ] Snapshot old Memory/File/PostgreSQL records, sealed digests, receipts, scopes, grants and journal state. Add tests that ordinary records retain their versions and bytes before/after migration, new enabled records fail on unprepared stores, and old readers refuse new records.
- [ ] Test file run marker 3→4, file session 4→5, PG run schema/storage 3→4 and PG session 4→5. Assert older compatible contracts migrate monotonically after intact readiness checks, both `context_packs_v1` and `tool_contracts_v1` remain advertised at higher versions, and concurrent owner migration uses the existing lock/drained-writer gate.
- [ ] Test worker role cannot initialize/migrate, readiness refuses excessive grants, no new table/column/size grant appears, and receipt/state validators reject forged/missing parallel bindings. Run `.venv/bin/python -m pytest -q tests/test_parallel_tool_stores.py`; expect failure.
- [ ] Implement strict new-frame codecs and existing owner migration paths; preserve all historical JSON documents. Audit the existing exact-version branches in tool-contract, context-pack and session-context helpers, so parallel-enabled version 5 retains its parent contract/pack behavior and unknown future versions still fail closed. Extend currently equality-based capability/version tests to compatible monotone checks without accepting unknown future contracts. Add explicit CLI initialization/migration selection, default off.
- [ ] Run Memory/File tests and the adapter's supported local-cluster test command for PostgreSQL 16 and 18, using actual `adapters/postgres/tests/support/local_cluster.py` help and exact owned manifests. Expect restricted-role/readiness/migration tests green and zero leftover owned resources. Commit `feat: persist parallel execution with explicit store contracts`.

## Task 9: Harness receipt adoption, cancellation and lease fencing

**Files:** create Harness `tests/test_parallel_tool_conversation.py`, `tests/test_parallel_tool_recovery.py`; extend adapter `test_parallel_tool_stores.py`; modify `engine.py`, `conversation.py`, `tool_contract_execution.py`, `session_tool_contracts.py`, `parallel_tools.py` only where the new versions need integration.

**Interfaces:** reuse current `save_receipt(..., lease)` and accepted-receipt adoption APIs. Versioned receipt validation binds the exact Runtime frozen/evidence frames and scheduler policy. No per-worker run/session controller, new tool journal or unfenced save API.

- [ ] Test accepted workflow/session receipt adopts on a fresh controller with zero provider and handler calls; changed parallel policy/registration/tenant/scope refuses adoption before work. Repeat with context packs and required citations.
- [ ] Force lease loss while two callbacks run. Assert no new worker/window/provider starts; completed journal outcomes survive; stale controller cannot save state/receipt; a fresh controller reconciles uncertain dispatch rather than executing the entire batch again.
- [ ] Force known sibling completion before event failure, guard stop, evidence capacity failure and cancellation. Assert current permissions gate retained views/history, callbacks are drained and known completion is never downgraded. Run the new tests; expect failure before integration.
- [ ] Wire enabled frame versions into existing prepared attempt, receipt save/adopt and bounded public-view routes. Keep renewal alive while Runtime drains; use existing ownership checks as admission boundaries and claim-token journal settlement for started callbacks.
- [ ] Run new tests plus existing tool-contract recovery, workflow-rule recovery, conversation lifecycle and context-pack adoption suites, including actual PostgreSQL lease races. Finish Harness README/parallel-tools documentation, commit the head, build that candidate once and verify isolated installed `test_parallel_tool_installed.py` plus existing smoke; add that focused test file in this task. Commit `feat: recover parallel tool receipts without redispatch`.

## Task 10: Lab copyable host and owned parallel acceptance

**Files:** create Lab `lab_runner/blueprints/parallel_tools/{__init__.py,host.py,README.md,LICENSE,NOTICE,runtime.yml,.prosaic/subagents/analyst.md}`, `src/prosaic_integration_lab/parallel_tools.py`, `lab_runner/parallel_tools.py`, `tests/unit/test_parallel_tool_scenarios.py`, `tests/blueprint_acceptance/test_parallel_tools.py`, `tests/acceptance/test_parallel_tools.py`. Modify blueprint registry, packaging inventory and `pyproject.toml`, `lab_runner/gates.py`, `__main__.py`, stack host registration and owned resource provisioning as required by existing runner interfaces.

**Interfaces:** scenario module exports `CASES` (exact 16 names from the spec), `require_parallel_tool_sdk()` and `run_case(case: str, provider: str, *, settings: dict) -> dict`. Owned runner returns existing sanitized lane schema with `mode='parallel-tools'`, `test_count=32`, zero skips, original dependency audit and verified cleanup. Blueprint exports `build_host(...)` using public SDK registrations/policies, never Task 4 internal coordinator.

- [ ] Add failing tests for copyable complete package contents, actual handler overlap, exact per-call events and ordered citations; execute all 16 scenarios on both provider wires with deterministic barriers. Assert no application scheduler/model loop and no private SDK imports.
- [ ] Add tests for source/installed provenance, explicit owner schema initialization, bounded fake HTTP services, foreign owner denial and owned cleanup on failure. Run `.venv/bin/python -m pytest -q tests/unit/test_parallel_tool_scenarios.py tests/blueprint_acceptance/test_parallel_tools.py`; expect missing capability/host failures.
- [ ] Implement copyable host and public-SDK scenarios, reusing exact new Runtime/Harness candidate wheels and original Core/recorder archives. Local candidate manifests must bind committed heads, original build receipts and wheel hashes; do not present development wheels as published stable releases.
- [ ] Run owned focused lane on PostgreSQL 16 and 18 with immutable consumer image ID, candidate manifest and both protocols. Use `lab_runner test --mode parallel-tools --candidate --candidate-manifest PATH --consumer-image sha256:ID --postgres-version 16` (then 18); expect 32/32, zero skips, actual overlap and verified cleanup. Use the installed wheel and rebuilt source archive for the blueprint consumer tests.
- [ ] Commit `test: qualify public parallel tool consumers across both wires`.

## Task 11: Integrate Lab gates, document compatibility and review the branch

**Files:** create Lab `tests/unit/test_parallel_tool_hosted.py`, `docs/parallel-tools.md`; modify candidate curation/build support, `scripts/required_acceptance.py`, `conversation_distribution_smoke.py`, `lab_runner/gates.py`, existing required-acceptance workflow, README/feature map/build inventory. Verify the Runtime/Harness README and `docs/parallel-tools.md` frozen at their SDK checkpoints, update Harness `docs/cerebro-requests.md` and this plan's completed checkboxes/evidence links.

**Interfaces:** new exact candidate-family predicate `supports_parallel_tools(manifest) -> bool` validates the complete family, not a minimum-version guess. New curation selection `parallel_tools=True` / CLI `--parallel-tools` uses exact original candidate artifacts and does not repin stable manifests. Extend supported-context/tool-evidence gates so the coherent new family retains every existing lane. Stable family selection is added only during a separately authorized publication/adoption phase.

- [ ] Test old families preserve their exact lane sets; new coherent candidate requires all twelve lanes/402 cases per cell; mixed family, fake wheel/source/hash, skipped new cases and absent installed SDK capability reject. Assert all previous 370 cases remain and original Core/recorder/historical snapshots are untouched.
- [ ] Test installed wheel and rebuilt-source distribution consumers execute the new blueprint plus existing blueprints/native evals. Preserve source-only tests before installing the Lab wheel. Extend current hosted AMD64/ARM64 × PG16/18 inventory without replacing existing source/required checks or adding a second release train.
- [ ] Run focused new tests, all affected source suites, both SDK isolated-wheel checkpoints, Lab native/blueprint/distribution suites and owned PG lanes. Record real commands, counts, original candidate hashes, permitted exclusions and cleanup; use no latency-ratio gate. Broader tests repeat only after new changes/failures justify them.
- [ ] Document thread-safety assertion, barriers, fixed-window behavior, pending-vs-consumed budget accounting, cooperative cancellation limitation, new/old codec matrix, explicit owner migration, supported surfaces and first-increment exclusions. Mark the released safe-event/citation family accurately in Cerebro backlog and parallel work as implemented candidate only after evidence exists; keep MCP/sub-agents separate.
- [ ] If review or documentation changes alter an SDK source tree after its checkpoint, commit a new head, build once for that new head and refresh only the affected candidate/consumer evidence; never claim earlier bytes were built from the later commit.
- [ ] Obtain independent review across all three committed diffs with special attention to the five Review Focus conditions. Reproduce/fix material findings, rerun affected checks and record review outcome. Commit `docs: document parallel read authority and compatibility`. Stop at reviewed implementation: do not push PRs, merge, alter deployment policy, assign stable release versions or publish without the maintainer's next instruction.

## Acceptance and compatibility checklist

- [ ] Positive concurrency is proved by overlapping callback intervals and deterministic rendezvous; cap 1 is sequential under the enabled contract; default None follows the untouched legacy path.
- [ ] Multiple call IDs/outputs/facts remain correctly associated under all tested finish orders and both provider wire encodings.
- [ ] Reservations and physical settlements are bounded; one model response remains one tool round; final provider dispatch uses the existing global budget and encoded-input/citation checks.
- [ ] Events never invoke user sinks concurrently or expose unapproved data. Fast settlement observation does not claim projected acceptance or model delivery.
- [ ] Cancellation/faults drain started callbacks, retain known outcomes and suppress later dispatch; no thread runs after invocation return.
- [ ] Journals, accepted receipt adoption, current permissions and lease/claim fencing prevent accidental redispatch; no exactly-once claim.
- [ ] Disabled golden bytes/old record readers remain valid; enabled records and policy changes require explicit new readers/storage contracts.
- [ ] Existing 370 Lab cases remain required; 32 new cases pass per coherent candidate cell with zero required skips and verified cleanup.
- [ ] Readmes and compatibility documentation match actual supported surfaces; independent review is resolved; no unrelated feature/release train has started.

## Plan self-review

Coverage: public authority/defaults → Task 1; shared dispatch → Task 2; atomic reservations → Task 3; windows/journals/drain → Task 4; wire/rules/events/citations → Task 5; Runtime durable formats → Task 6; Harness nodes → Task 7; store contracts → Task 8; durable adoption/fencing → Task 9; public Lab witnesses → Task 10; complete gates/docs/review → Task 11. All five Review Focus conditions have explicit tests in their owning tasks. Fresh builder review found and resolved three design gaps: separate undroppable settlement control, guarded worker-start permits with conservative claimed-work uncertainty, and repairable after-tool feedback distinct from terminal STOP. Recheck reported no remaining design blocker. The spec's callback/format/version names are the interface source of truth; implementation must not silently substitute a second scheduler or new authority mechanism.
