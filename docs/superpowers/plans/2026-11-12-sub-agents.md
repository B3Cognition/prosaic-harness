# Bounded Sub-agents Implementation Plan

> Use superpowers:executing-plans for native execution and an independent whole-branch review, following the prior Cerebro trains. Track steps with checkboxes.

**Goal** — Ship reusable depth-one delegation to named specialists inside ordinary Prosaic turns and Harness agent nodes.

**Architecture** — Runtime runs a fresh child turn through a marked serial tool registration under a shared root budget. Harness freezes child projections, reserves durable allowance, and adopts parent receipts under its lease. Lab verifies both provider protocols and installed SDKs with owned synthetic fixtures.

**Tech stack** — Python 3.11–3.13 SDKs, Lab Python 3.12+, existing JSON Schema, journal, recorder and PostgreSQL 16/18 infrastructure.

**Spec** — [Bounded sub-agents design](../specs/2026-11-12-sub-agents-design.md).

## Global constraints

- Branch from current main in each repo. Start from Runtime 0.9.22, Harness 0.9.16, Harness PostgreSQL 0.4.4 and Lab 0.9.15. Preserve Core 0.5.0, recorder 0.3.0 and published artifacts. No dependency additions.
- Depth one, synchronous serial delegate calls, same resolved provider/model, API turns over OpenAI-compatible Chat Completions and Anthropic Messages. Children use explicitly reviewed local read-only tools.
- Limit to 8 registered aliases, 1–8 launches, 8 KiB canonical task, 16 KiB canonical result and 64 KiB aggregate frozen child projections, 64 source references and 16 KiB private provenance per outcome, subject to existing tighter caps.
- Scope authority to the trusted principal and actual parent invocation. Recheck authorization after journal lookup and before exposure. Parent lease fencing controls parent adoption. Use existing process-local and durable allowance contracts at their respective boundaries.
- New formats are opt-in. Verify byte equality on prior prepared inputs, descriptors, persisted state and receipts. Provision compatible storage explicitly with the owner. Use only exact installed SDK artifacts for integration qualification.
- Implementation uses credential-free synthetic services. Candidate qualification is distinct from release. Publication and active Lab pin updates require a separate instruction.

## Review focus

- A blocking journal read returns after the host revokes access. Deny exposure without a new child call or evidence. Tasks 2 and 5.
- A child returns a citation string pointing at an unsubmitted source. The parent gets no citation authority. Tasks 3 and 6.
- A child consumes the final provider request or an unknown usage response is followed by a retry. Keep continuation capacity and stop unknown capped dispatch. Task 2.
- A worker loses the parent lease after the journal commit. A second owner cannot use the child outcome to recreate an interrupted parent turn. Tasks 4–6.
- A mixed SDK or old store sees a delegation-enabled frame. Reject before dispatch, resource allocation or automatic migration. Tasks 1, 4 and 6.

## Runtime

### Task 1. Registration, frame and admission

**Files** — Create `src/prosaic_runtime/sub_agents.py` and `tests/test_sub_agent_admission.py`. Modify `src/prosaic_runtime/{__init__,runtime,conversation,conversation_preparation,direct_tool,structured_tools,tool_parallel}.py` and README.

**Interfaces** — Export `SubAgentSpecV1`, `SubAgentPolicyV1`, `SubAgentFrameV1`, `SubAgentAccessV1` and `bind_sub_agent_tools(specs, *, existing=None) -> dict[str, CustomTool]`. Specs carry the owned artifact, child policy/tool inventory, guard/pack and authorization revisions, closed schemas and bound output policy. Frame carries the per-invocation scope, root caps and frozen child projections. Add optional `sub_agent_frame=None` to `prepare_turn`, `turn` and `restore_turn`, with equality/readmission checks for prepared input. Add `sub_agent_access=None` to execution only for live authorizers and ownership checks. Expose `sub_agents_v1` on Runtime capabilities.

- [ ] Add `test_selected_delegate_round_trips_frozen_frame`, `test_binding_drift_refuses_before_journal`, `test_delegate_refused_outside_api_turn` and `test_unselected_registration_keeps_legacy_bytes`. Cover changed schema, artifact, source revision, scope, policy and projection, collisions, unsupported modes, hard size boundaries, and attempts to fall back to another route.
- [ ] Run `python -m pytest -q tests/test_sub_agent_admission.py` and confirm failures at the new API.
- [ ] Implement immutable descriptor, closed private frame and marked CustomTool admission. Use prepared-turn v6/frozen-input v5 only for selected aliases. Apply an explicit serial barrier even when the parent enables parallel calls. Reject malformed or missing frame data at prepare time. At execution, require trusted accounting context, recorder, grant and journal before provider I/O.
- [ ] Run the new file plus Runtime conversation preparation, direct-tool, MCP and parallel-tool regressions. Record exact commands and successful exit status. Commit Runtime admission.

### Task 2. Dispatch, nested budgets and accounting

**Files** — Create `src/prosaic_runtime/sub_agent_execution.py` and `tests/test_sub_agent_dispatch.py`. Extend `src/prosaic_runtime/{runtime,tool_dispatch,execution_budget,operation_context}.py` at existing phase boundaries.

**Interfaces** — Consume the frame and marked tool from Task 1. The internal child handler uses `ToolExecutionContext` and a Runtime-owned launch counter. Derive journal key and child ID from namespace/parent invocation/ordinal. Seal the frame digest into the journal signature. Journal the bounded private `subAgentReceiptV1` envelope. Pass only its validated inner `ToolResultV1` or proven `ToolFailure` to parent result handling.

- [ ] Add failing tests `test_child_charges_shared_dispatch_and_frozen_attribution`, `test_child_preserves_one_parent_continuation`, `test_replay_reauthorizes_after_lookup`, `test_unknown_usage_stops_capped_dispatch` `test_child_inherits_cancellation_and_deadline`, `test_revocation_after_new_claim_closes_slot_without_launch` and `test_child_token_exhaustion_prevents_parent_dispatch`. Use a three-request parent/child/parent exchange, then a four-request exchange with a child read. Assert independent wire and recorder counts, exact parent linkage and preserved attribution, one launch per claimed slot, no work beyond any cap, and bounded cancellation with synchronization barriers.
- [ ] Run `python -m pytest -q tests/test_sub_agent_dispatch.py` and verify the expected missing behavior.
- [ ] Activate the root budget before the first parent request. Clamp and activate the child budget, enter through the existing Runtime turn loop and preserve request lineage. Perform journal authorization at claim, handler entry and replay exposure. Keep parent-local result usage and shared actual usage separate. Settle only known outcomes and retain uncertain claims.
- [ ] Verify with `python -m pytest -q tests/test_sub_agent_dispatch.py tests/test_execution_budget.py tests/test_tool_effects.py tests/test_mcp_dispatch.py`. Add installed-wheel entry-point coverage on both wires. Commit Runtime execution.

### Task 3. Typed result and evidence projection

**Files** — Extend `src/prosaic_runtime/sub_agent_execution.py`, `tool_evidence.py` and `tool_result_contract.py` under `src/prosaic_runtime/`. Create `tests/test_sub_agent_evidence.py`.

**Interfaces** — Accept a bounded validated child proposal and optional host-selected exact child observations. Emit ordinary typed result data and `EvidenceDraftV1` selectors. The parent's tool-contract bindings remain the authority for provider delivery and citations.

- [ ] Add failing tests `test_parent_cites_only_delivered_approved_child_observation`, `test_forged_child_citation_and_private_transcript_stay_private` `test_revocation_blocks_replayed_observation` and `test_uncited_protected_source_revocation_hides_entire_finding`. Prove exact source revision/value, two independent grants, no eligibility before parent delivery and fixed sanitized failure on malformed child results.
- [ ] Run `python -m pytest -q tests/test_sub_agent_evidence.py` and observe expected failures.
- [ ] Seal all protected frozen and delivered read source references, including uncited sources. Validate the output and copy only verified observed child values into explicit parent result fields. Reuse existing display and event contracts. Cover unsupported child source types with refusal.
- [ ] Run the Runtime delegation files, tool evidence/guard regressions and full source suite, then build and install the isolated wheel. Commit Runtime evidence and operator documentation.

## Harness and its PostgreSQL adapter

### Task 4. Host bindings, frozen attempts and durable reservations

**Files** — Create `src/prosaic_harness/sub_agents.py`, `tests/test_sub_agent_admission.py`, `tests/test_sub_agent_storage.py`. Modify `src/prosaic_harness/{factory,graph_admission,discovery,workflow,engine,conversation_bindings,conversation,contracts,session_contracts,tool_contract_execution}.py` and the context-pack workflow execution path. Update `file_store.py`, `file_session_store.py`, `memory_session_store.py`, store capability protocols and adapter `{schema,session_schema,store,session_store,cli}.py`.

**Interfaces** — Add optional `sub_agents=None` to `Workflow.load`, `WorkflowBindings` and `ConversationBindings`. Proposed `SubAgentBindingsV1` owns specs, named pack bindings, root caps, current authorizers and delegated-turn session token allowance. Compile selected specs into Task 1's frame. Add `initialize(sub_agents=True)` and `migrate_sub_agent_storage()` following the existing owner-migration protocol. Workflow markers advance 4→5 and conversation markers 5→6.

- [ ] Add failing tests `test_yaml_native_and_chat_admit_the_same_sealed_alias`, `test_generated_workflow_and_interpreter_cannot_select_delegate`, `test_frozen_pack_preserves_guard_and_history_isolation` and `test_legacy_namespace_and_records_are_byte_identical`. Include selected versus merely registered aliases, v6 creation and mixed old/new readers, pack plus parallel plus ordinary parent MCP, binding drift, scope swaps, denied DDL, old-reader refusal and the migration progression. An existing session cannot opt in through resume.
- [ ] Add `test_delegate_attempt_reserves_once_and_unknown_retains_allowance`. Prove pre-dispatch quota refusal, exact reservation across prepared restart, no double charging parent-local usage, and retained allowance after dispatch ambiguity.
- [ ] Run `python -m pytest -q tests/test_sub_agent_admission.py tests/test_sub_agent_storage.py` and verify expected failures.
- [ ] Implement host-only admission, projection freezing, durable allowance and versioned attempt/receipt state. Provision explicit file and PostgreSQL markers, retaining existing tables, grants and older records. Verify only owners migrate; older workers refuse the new marker and new workers read prior records.
- [ ] Run the new suite and existing context-pack, workflow factory, conversation, parallel storage and adapter packaging regressions. Commit Harness admission and storage.

### Task 5. Execution and receipt-first recovery

**Files** — Create `tests/test_sub_agent_recovery.py`, `adapters/postgres/tests/test_sub_agent_recovery.py` and `docs/sub-agents.md`. Modify `src/prosaic_harness/{engine,conversation,tool_contract_execution,tool_contract_views}.py` and `context_packs/workflow_execution.py` for the shared execution and recovery paths.

**Interfaces** — Consume the frozen attempt and reservation from Task 4 and pass the exact frame to Runtime. Preserve existing lease-fenced save/adopt APIs, the separate accounting context and current evidence grants.

- [ ] Add failing tests `test_lost_parent_receipt_ack_adopts_with_endpoints_offline`, `test_child_commit_without_parent_receipt_keeps_parent_interrupted`, `test_uncertain_child_claim_does_not_redispatch` and `test_stale_parent_owner_cannot_advance_state`. Exercise both parents and process replacement, competing leases, missing versus committed receipts, authorization drift, retained history and evidence views under revoked result grants, and existing explicit retry/resume entry points.
- [ ] Run the new file and confirm expected missing capability. Run the adapter counterpart with the repo's owned PostgreSQL test harness and owner/worker roles.
- [ ] Route delegation through existing prepared execution including the context-pack path. Preserve interruption on dispatched attempts without parent receipts. Adopt verified parent receipts once and recheck current view permission. Include an operator table for safe actions at each persistence boundary.
- [ ] Run full Harness pytest, installed wheel smoke and owned PostgreSQL suites on 16 and 18. Exercise current file/memory codecs and both versions of the adapter against appropriate readers. Commit recovery and documentation.

## Lab

### Task 6. Copyable Ask Cerebro blueprint and exact installed qualification

**Files** — Create `lab_runner/blueprints/sub_agents/`, `tests/blueprint_acceptance/test_sub_agents.py`, `tests/acceptance/test_sub_agents.py`, and `docs/sub-agents.md`. Update `lab_runner/blueprints/__init__.py`, `pyproject.toml`, `dependencies/public-build-inputs.json`, `lab_runner/{gates,__main__}.py`, `scripts/{prepare_sdk_candidates,required_acceptance,conversation_distribution_smoke}.py`, hosted acceptance and rule-admission workflows, feature map and verification ledger.

**Interfaces** — Consume installed public Runtime/Harness/adapter APIs and Lab's existing owned journal and recorder. Copy with `python -m lab_runner.blueprints copy sub-agents DESTINATION`. Expose `python -m lab_runner test --mode sub-agents --postgres-version 16|18` on the qualifying family.

- [ ] Add installed blueprint coverage for a dependency analyst and optional reviewer. Use graph fixtures with one supported transitive dependency and one unsupported claim. Inspect actual parent/child provider bodies for scope, decoys and delivery order. Verify proposal and citation admission, parent-owned final answer and filtered progress.
- [ ] Implement a required matrix of 12 scenarios on each wire, 24 cases per architecture/database cell. Scenarios cover ordinary chat, authored workflow, two siblings, scoped pack and actual evidence delivery, unauthorized/forged delegate, nested or write-tool refusal, budget exhaustion, cancellation, revoked replay, uncertain child, committed child with interrupted parent, and lost parent receipt acknowledgment. Assert independent tool/provider/recorder counts and verified cleanup.
- [ ] Run the new tests before capability integration to verify required mode fails for the old SDK family. Add exact candidate admission before historical mixture checks, inherited MCP lock and all existing lanes. Keep the Lab 0.9.15 family at 13 lanes/426 cases. The new exact family targets 14 lanes/450 cases. Refuse mismatched capabilities, missing infrastructure and skips.
- [ ] Build exact Runtime, Harness and Harness adapter wheels with receipts and checksums. Build the consumer image and qualify the required lane on PostgreSQL 16/18 with restricted worker roles. Run isolated installed blueprint and wheel/rebuilt-sdist consumers on the approved candidate. Preserve previous public pins, provenance profiles and freezes.
- [ ] Run complete Lab source tests, rule and reasoning matrices, and the native AMD64/ARM64 × PostgreSQL 16/18 acceptance matrix. Record no-skip case counts, cleanup, platform, source hashes, provenance and actual commands. Update the guide and feature map. Commit Lab qualification.
- [ ] Review the complete three-repo change independently, prioritizing scope crossing, journal/lease races, budget retention and legacy bytes. Resolve findings and rerun the affected gates before handing off.

## Execution order

Runtime admission → Runtime dispatch/evidence → Harness bindings and durable
execution → Lab installed acceptance. Lab fixture design can proceed against the
specified public interfaces. SDK qualification uses exact built artifacts and
verified upstream receipts. A future authorized release would promote Runtime,
then Harness and its adapter, then adopt their verified public hashes in Lab.
