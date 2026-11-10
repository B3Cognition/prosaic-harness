# Safe Tool Events and Citations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The maintainer already chose native execution followed by one independent whole-branch review. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver opt-in safe tool events and evidence-backed final-text citations across Runtime, Harness and Lab while preserving disabled-feature behavior and historical records.

**Architecture:** Runtime owns typed result normalization, safe event projections, evidence/delivery tracking and citation acceptance. Harness binds these contracts to workflow/session identity, context-pack authorization, durable receipts and authorized public views. Lab exercises the public SDK contracts with synthetic tools/providers and owned persistence; it does not copy execution logic.

**Tech Stack:** Existing Python SDKs, frozen/owned JSON codecs, JSON Schema 2020-12 subset, pytest, synthetic OpenAI-compatible/Anthropic HTTP fixtures, existing memory/file/PostgreSQL stores. No new production dependency is required.

**Spec:** [Approved shared contract design](../specs/2026-11-10-tool-result-event-evidence-design.md). Read both documents before execution. The user approved implementing this first increment on 2026-11-10; this turn prepares the plan before product code changes.

## Global Constraints

- First increment: safe tool events, typed results/evidence and citations. **Parallel tool calls, MCP and sub-agents are separate follow-ups.** Execution remains sequential.
- Baselines: Runtime released 0.9.19/main `b2b2e39`; Harness released 0.9.13/main `c43ebb9`; Harness PostgreSQL 0.4.2; Lab 0.9.12. Recheck actual heads before implementation and preserve unrelated user changes.
- Preserve absent-feature descriptors, policy/prepared identities, result/event wire shapes and old receipt encodings. No automatic upgrade or rehash of saved records.
- Independent optional registrations: `result_contract` and `event_policy`. Events-only callers can keep legacy handler returns.
- Capability names: `tool_results_v1`, `safe_tool_events_v1`, `citations_v1`; `toolContractV1` marks new durable bindings. Unsupported enabled combinations fail before dispatch.
- Preserve `ToolOutcome` v1, `ToolFailure`, journal outer frames/protocol, accounting and unknown-effect fencing. No automatic retry of a completed or uncertain effect.
- Evidence permission purposes: `modelUse`, `cite`, `retainedRead`; display permission purpose: `toolProgress`. Require literal true. Exceptions deny without raw diagnostics.
- Model/result provenance, private receipts/guard facts and authorized display projections remain separate views. No argument/result/citation payload enters general observer telemetry.
- Final citation syntax: `[cite:<evidence-id>]`, reserved throughout an opted-in answer. `required` means at least one valid citation in a nonempty answer; semantic claim support remains separate.
- Default bounds: enriched event 4 KiB; display 8 scalar fields, 256 UTF-8 bytes/string, 1 KiB total; evidence 64 declarations/result, 256 active/invocation, 64 KiB sidecar; source key/revision/locator/label 256/128/1,024/128 UTF-8 bytes; pointer 4 KiB; citations 128 tokens and 32 KiB sidecar. Smaller existing bounds win.
- Native CLI execution, builtin file-tool outputs and automatic terminal-completion citations do not acquire new inferred capabilities. `StructuredToolLoop` does not advertise automatic `citations_v1`.
- No live/paid inference, new scheduler, arbitrary URL fetching, blanket schema migration, release publication or changes to release-promotion workflows in this implementation increment.
- Reuse exact candidate wheels after building each SDK head once. Local focused tests per task; complete relevant suites at repository checkpoints. No full CI train for documentation-only edits and no optional duplicate qualification matrices.
- New candidate distributions need distinguishable unpublished development versions, never altered wheels masquerading as an existing stable release. Select/record exact candidate versions at execution kickoff; stable release numbers and public train adoption are a later release decision.

## Review Focus

These five conditions receive explicit tests in the owning tasks:

1. A callback commits an effect, then projection, permission, cancellation or citation acceptance fails: the receipt still proves the effect and recovery executes it zero additional times (Tasks 2, 5, 12–14).
2. Tool data is corrected or compacted between callback return and the actual HTTP body: only the exact submitted, unchanged selected values become citable (Tasks 4–5, 7).
3. A display-only opt-in or a dictionary resembling a typed result accidentally changes legacy result semantics, grants or hashes: old behavior remains exact (Tasks 1–3, 8–10).
4. An old source/call ID appears in another session, a replay or retained history: IDs alone grant nothing; explicit current authorization and submitted bytes are required (Tasks 4, 8, 11, 13).
5. The external structured driver supplies an ordinary `Result` or takes its alternate completion route: neither bypasses delivery proof or final citation acceptance (Tasks 6, 9, 16–17).

---

## Repository and file map

All paths below are relative to the named repository. Implement in clean isolated
branches based on then-current main, without resetting the maintainer's original
working copies. The design/plan live in the Harness documentation branch
`codex/tool-contract-design`; carry them into the Harness implementation branch.

| Repository | New focused modules | Existing integration points |
| --- | --- | --- |
| Runtime | `src/prosaic_runtime/tool_contracts.py` (owned value/binding codecs); `tool_result_contract.py` (normalization/projection); `tool_event_contract.py` (call identity, lifecycle and display); `tool_evidence.py` (registry and delivery); `citations.py` (parser/acceptance) | `tools.py`, `tool_registry.py`, `execution.py`, `runtime.py`, `events.py`, `telemetry.py`, `turn_capture.py`, `conversation.py`, `conversation_preparation.py`, `frozen_turns.py`, `rule_hooks.py`, `rule_facts.py`, `guards/values.py`, `direct_tool.py`, `structured_tools.py`, `adapter.py`, `__init__.py` |
| Harness | `src/prosaic_harness/tool_contracts.py` (binding/admission and receipt helpers); `tool_contract_views.py` (authorized citation/event views); `context_packs/tool_contracts.py` (verified pack-origin adapter) | `factory.py`, `graph_admission.py`, `admission_data.py`, `engine.py`, `contracts.py`, `conversation_bindings.py`, `conversation.py`, `session_contracts.py`, `session_codec.py`, existing stores and context-pack codecs |
| Lab | `src/prosaic_integration_lab/tool_evidence.py` (public-SDK scenario); `lab_runner/tool_evidence.py` (owned runner); `lab_runner/blueprints/tool_evidence/` (copyable example) | `lab_runner/gates.py`, `lab_runner/__main__.py`, blueprint registry/package data, candidate curation/install audits, focused hosted workflow and tests |

Avoid broad refactoring of the shared execution loop. Keep legacy branches and
new contract helpers explicit until compatibility fixtures establish equivalence.

## Frozen interface decisions

The spec's proposed names become the implementation API below. Python names use
snake case; serialized records use the spec's camel-case fields. All owned types
validate/copy finite bounded JSON on construction and on `from_dict`; callbacks
and credentials are never serialized.

| Interface | Definition / consumer |
| --- | --- |
| `EvidenceDraftV1` | Keyword fields `source_key: str`, `source_revision: str | None`, `locator: str`, `selector: str`, `label: str`. Selector is JSON Pointer into `ToolResultV1.data`. |
| `ToolResultV1` | Keyword fields `data: JSON`, `evidence: tuple[EvidenceDraftV1, ...] = ()`. A plain dictionary is never recognized as this type. |
| `ToolResultContractV1` | `version: str`, `output_schema: dict | None = None`; owned schema and spec limits. Applies only to registered typed results. |
| `ToolDisplayFieldV1` | `source: Literal['arguments','result']`, `pointer: str`. Declared field names map to scalar projections of logical data. |
| `ToolEventPolicyV1` | `version: str`, `fields: Mapping[str, ToolDisplayFieldV1]`; immutable and included in enabled descriptors. No arbitrary formatter. |
| `EvidenceAuthorizerV1` | `identity: str`, `version: str`, `authorize: Callable[[EvidenceUseV1], bool]`; owned scope/source/representation metadata and purpose, never private bodies. |
| `ToolDisplayAuthorizerV1` | `identity: str`, `version: str`, `authorize: Callable[[ToolDisplayUseV1], bool]`; invocation/viewer-bound host authorization for declared fields and `toolProgress`. |
| `CitationPolicyV1` | `mode: Literal['optional','required']`; protocol version fixed at 1. |
| `ToolContractBindingsV1` | `identity`, `version`, owned `InvocationScope`, optional evidence/display authorizers, optional citation policy, explicitly verified retained imports and `ToolContractLimitsV1`. Evidence/citations require an evidence authorizer; events-only operation does not. |
| `EvidenceRegistryV1` | Invocation-owned registry, not a process-global collection. Stages owned projections, authorizes use, binds actual delivery, freezes private evidence and creates a verified eligible snapshot. |
| `validate_citations(text: str, registry: EligibleEvidenceV1 | HostAttestedEvidenceV1, policy: CitationPolicyV1) -> CitationsV1` | Pure parser/membership/hash check; authorization is a separate current gate around acceptance. Contains UTF-8 marker spans, answer SHA256 and registry digest. Automatic Runtime acceptance requires Runtime-observed `EligibleEvidenceV1`. |

Constructor details for `EvidenceUseV1`/`ToolDisplayUseV1` must expose exactly the
owned metadata listed in the spec; represent purpose with closed literals and
represent the authenticated principal through the trusted host binding, not model
arguments. Use existing `InvocationScope` plus the application/Harness-bound
principal; do not invent a second authorization authority.

Internal phase interfaces:

- `normalize_tool_result(tool, value) -> dict`: validated **private** journal frame.
- `prepare_tool_projection(tool, call_identity, private_outcome, registry) -> PendingToolProjectionV1`: candidate model frame plus owned selector origins.
- `finalize_tool_projection(pending, checked_payload, registry) -> ModelToolProjectionV1`: revalidate checked data, retain only unchanged source selections, regenerate trusted compact references.
- `stable_tool_call_id(scope, exchange, batch_index) -> str`: reuse the current conversation hash algorithm; global `callIndex` remains separately recorded.
- `project_tool_event(call_identity, phase, arguments, checked_data, bindings, outcome) -> dict`: closed `toolEventV1`, no raw fallback.
- `EvidenceRegistryV1.prepare_delivery(native_payload, provider, request_id) -> PendingDeliveryV1`, `begin_dispatch(ticket)`, `confirm_delivery(ticket)`: bind final encoded input to an actual HTTP attempt/response boundary.
- `EvidenceRegistryV1.freeze() -> ToolInvocationEvidenceV1`: private receipt payload. `eligible()` returns only verified delivered entries, never a caller-supplied dictionary.
- `import_retained_evidence(receipt, bindings, selected_view) -> RetainedEvidenceV1`: verify receipt/hash/scope and current authorization before later submission.

`HostAttestedEvidenceV1.from_host_records(records, *, bindings)` is an explicit
trusted-host factory and always serializes proof kind `hostAttested`. It cannot
create Runtime delivery tickets or be converted into Runtime-observed proof by
deserializing a model/tool/event dictionary. Both proof kinds still require
current source/use authorization.

Delivery tickets distinguish constructed, attempted, confirmed and unknown. A
connection/write failure without a response cannot establish eligible delivery.
Confirm against the exact request sent only after a real response is acquired;
this is evidence of submission, not evidence of model understanding. A successful
final response must reference a confirmed request. Preserve attempted/unknown
accounting even when nothing becomes citable.

## Execution order and checkpoints

1. **Runtime foundation and safe events:** Tasks 1–3. Events-only behavior can be exercised without rewriting handlers.
2. **Runtime evidence/citations:** Tasks 4–9. Prove both provider wires, finalization, saved input and unsupported surface refusal.
3. **Harness durability/views:** Tasks 10–14. Prove scoped pack adaptation, crash adoption and store capability/capacity.
4. **Candidate SDK consumers and Lab:** Tasks 15–17. Reuse built candidate bytes and run the new focused lane.
5. **Native whole-branch verification/review:** Task 18. No release train is included.

Each task ends in a small local commit. Work need not be distributed to separate
implementer agents. Later tests consume the interfaces above rather than copying
another task's implementation.

### Task 1: Freeze legacy behavior and add owned contract types

**Files:** Create Runtime `tool_contracts.py`, `tests/test_tool_contract_codecs.py`,
`tests/test_tool_contract_legacy.py`, `tests/fixtures/tool_contracts/legacy/`;
modify `tools.py`, `__init__.py`.

**Interfaces:** Produce the public owned types above and optional
`CustomTool(..., result_contract=None, event_policy=None)` registration. Descriptor
fields are absent when unconfigured. Reuse existing JSON/schema validation.

- [ ] Capture baseline descriptor/result/event/policy/prepared-input/receipt fixtures from untouched 0.9.19/0.9.13 public artifacts; record their existing Lab manifest hashes. Fix scope and clock from construction so fixtures do not depend on wall-clock races.
- [ ] Add tests `test_absent_tool_contract_is_byte_identical`, `test_dictionary_is_never_a_typed_result`, `test_event_policy_does_not_require_result_contract`, and parameterized bound/schema/type failures. Assert `descriptor == baseline_descriptor`, old wire bytes/hashes match, and input mutation cannot alter an owned registration.
- [ ] Run `python -m pytest -q tests/test_tool_contract_codecs.py tests/test_tool_contract_legacy.py`; confirm the new codec/keyword tests fail for the missing feature.
- [ ] Implement registration/codecs and run that command plus `tests/test_custom_tools.py`. All must pass; do not yet advertise unimplemented backend capabilities.
- [ ] Commit: `feat: add owned optional tool contract registrations`.

### Task 2: Normalize typed results without changing effect semantics

**Files:** Create Runtime `tool_result_contract.py`, `tests/test_tool_result_contract.py`;
modify `tools.py`, `tool_effects.py`, `tool_registry.py`.

**Interfaces:** Produce `normalize_tool_result`; retain existing journal
`status/result` or `status/error` outer frame. Store private v1 `data/sources`
inside success `result`; wire projection is a separate operation.

- [ ] Add tests `test_output_schema_checks_data_before_commit`, `test_replay_validates_pinned_contract`, `test_invalid_journaled_result_preserves_uncertainty`, `test_commit_precedes_later_cancellation`, and `test_replay_keeps_source_revision`. Assert `handler_calls == 1` across two invocations and no invocation-specific citation ID enters the reusable journal outcome.
- [ ] Run `python -m pytest -q tests/test_tool_result_contract.py` and confirm failures at the new behavior.
- [ ] Implement owned result normalization and both size checks, preserving plain returns and `ToolFailure`. Never reinterpret model/legacy dictionaries or change `ToolOutcome` meanings.
- [ ] Run that file plus `tests/test_tool_effects.py tests/test_controlled_tool_failure.py tests/test_tool_outcome_transport.py tests/test_tool_contract_legacy.py`; all pass with the same effect counts.
- [ ] Commit: `feat: validate typed tool results before journal commit`.

### Task 3: Add independently opt-in safe event lifecycle and display

**Files:** Create Runtime `tool_event_contract.py`, `tests/test_safe_tool_events.py`;
modify `execution.py`, `tools.py`, `tool_registry.py`, `runtime.py`, `events.py`,
`turn_capture.py`, `direct_tool.py`, `structured_tools.py`; test `test_telemetry.py`.

**Interfaces:** Produce stable call identity and `project_tool_event`; thread
optional `tool_contract_bindings` through `run`, `run_tool` and structured dispatch.
Enabled executor paths own one lifecycle sequence; legacy emission stays intact.

- [ ] Add `test_events_only_keeps_legacy_return`, `test_display_grant_is_separate_from_execution`, `test_denied_or_invalid_call_has_no_argument_display`, `test_journal_replay_never_reports_new_start`, and `test_each_attempt_has_one_completion`. Assert approved `component/count` values appear and a neighboring secret sentinel never appears in `on_event` display or general telemetry.
- [ ] Add bound/control-character cases and `test_bad_projection_does_not_retry_effect`; assert missing/invalid scalar projection is omitted, oversized display has `displayUnavailable: true`, and `handler_calls == 1`. Check start occurs after authorization/claim and before callback entry.
- [ ] Run `python -m pytest -q tests/test_safe_tool_events.py` to observe failures, then implement the shared identity/lifecycle/projection path and explicit conversation field pass-through.
- [ ] Run it with `tests/test_telemetry.py tests/test_custom_tool_transport.py tests/test_direct_tool.py tests/test_structured_tools.py tests/test_tool_contract_legacy.py`. Check payload-free observer allowlists and existing critical sink failure semantics.
- [ ] Commit: `feat: expose bounded authorized tool event projections`.

### Task 4: Implement private evidence registry and authorization

**Files:** Create Runtime `tool_evidence.py`, `tests/test_tool_evidence.py`;
extend `tool_result_contract.py`, `tool_contracts.py`.

**Interfaces:** Produce staged/finalized projections, `EvidenceRegistryV1`,
`ToolInvocationEvidenceV1`, eligible snapshots and retained import codecs.
Registry factories accept owned producer records, never arbitrary model JSON.

- [ ] Add `test_ids_bind_scope_call_selector_and_value`, `test_hash_is_computed_from_captured_selection`, `test_stage_is_not_delivery`, `test_cross_scope_id_is_not_authority`, and `test_authorizer_exception_denies`. Assert changing source revision, selector or captured value changes identity and `eligible()` is empty before confirmed delivery.
- [ ] Add tests for all three permission purposes, 64/65 per-result declarations, 256/257 active entries, the 64 KiB sidecar, pointer escapes and null revisions. Assert model-use denial produces `evidenceUseDenied` without another provider dispatch while retaining completed tool evidence.
- [ ] Run `python -m pytest -q tests/test_tool_evidence.py` for red, then implement the registry and bounded canonical codecs with no process-global state or raw-body duplication.
- [ ] Run that file with `tests/test_tool_result_contract.py tests/test_guard_input_views.py`; unchanged selections retain references after a rewrite, affected selections lose them, and private guard-only facts never register.
- [ ] Commit: `feat: track scoped captured tool evidence and exposure grants`.

### Task 5: Bind evidence to actual API delivery and checked results

**Files:** Create Runtime `tests/test_tool_evidence_delivery.py`; modify
`execution.py`, `runtime.py`, `openai_compatible.py`, `anthropic.py`,
`openai_compatible_compaction.py`, `rule_hooks.py`, `rule_facts.py`.

**Interfaces:** Consume Task 4 projections/tickets. Prepare after final native
encoding/compaction; begin at the existing budget/accounting dispatch reservation;
confirm against the real response for that exact request. Capture final checked
model data separately from raw journal completion.

- [ ] Parameterize actual synthetic OpenAI-compatible and Anthropic transports: `test_only_submitted_value_and_reference_become_eligible`, `test_compaction_cannot_cite_omitted_original`, `test_unsent_result_has_no_delivery`, and `test_connection_failure_retains_attempt_but_not_eligibility`. Inspect received HTTP bodies and exact input digests, not event assertions alone.
- [ ] Add `test_post_tool_fix_withdraws_changed_selection`, `test_replay_is_visible_and_not_a_fresh_observation`, and `test_earlier_confirmed_delivery_survives_later_compaction`. Assert checked `.data` reaches the model; private source locators do not; wire IDs map to the same Runtime call record.
- [ ] Include `test_post_tool_fix_must_still_satisfy_output_schema`: recheck the final logical data and framing; reconstruct references from owned unchanged selections rather than accepting guard-edited reference dictionaries. Retain the original completed outcome even if this finalization refuses model continuation.
- [ ] Run `python -m pytest -q tests/test_tool_evidence_delivery.py` for red, then integrate projection/finalization and ticket transitions at real transport hooks. No success acknowledgment is inferred from constructed prompts or observer callbacks.
- [ ] Run that file with `tests/test_rule_tool_facts.py tests/test_http_boundaries.py tests/test_context_execution.py tests/test_tool_outcome_boundaries.py`; all pass without added provider/tool attempts.
- [ ] Commit: `feat: bind tool provenance to finalized provider input delivery`.

### Task 6: Implement the pure citation parser and sidecar

**Files:** Create Runtime `citations.py`, `tests/test_citations.py`;
extend `tool_contracts.py`.

**Interfaces:** Produce `CitationPolicyV1`, owned `CitationsV1` serialization and
`validate_citations(text, registry, policy)`. Caller must provide a typed verified
eligible registry; host-attested proof is explicitly distinguishable from
Runtime-observed proof.

- [ ] Add `test_optional_validates_every_present_marker`, `test_required_needs_a_valid_marker`, `test_unknown_private_and_foreign_ids_fail`, `test_utf8_spans_select_exact_marker_bytes`, and `test_tokens_in_code_blocks_follow_reserved_syntax`. Assert exclusive `end`, answer hash and ordered marker spans, including repeated references and non-ASCII text.
- [ ] Add 128/129 marker and 32 KiB sidecar tests, malformed/truncated syntax, empty-answer policy cases and forged registry dictionaries. Both modes reject malformed markers; `required` rejects an answer with no valid citation. Empty `optional` answers may have no citations; ordinary application guards still decide usefulness.
- [ ] Run `python -m pytest -q tests/test_citations.py` for red; implement bounded linear parsing/hash/membership checks without provider calls, source fetches or semantic entailment claims.
- [ ] Run it with `tests/test_tool_evidence.py`; ensure host-attested registry output never claims Runtime-observed delivery.
- [ ] Commit: `feat: validate scoped final-answer citation references`.

### Task 7: Integrate answer guards, withholding and existing repair caps

**Files:** Create Runtime `tests/test_citation_execution.py`; modify `execution.py`,
`rule_hooks.py`, `rule_facts.py`, `guards/values.py`, `events.py`, `runtime.py`.

**Interfaces:** After ordinary final text fixes, authorize `cite`, validate the
entire final text and attach `CitationsV1` plus private invocation evidence.
Use closed failures `citationViolation` and `evidenceUseDenied` at invocation
level; do not add or reinterpret `ToolOutcome` codes.

- [ ] Add cross-provider `test_citations_checked_after_final_text_fix`, `test_final_text_is_withheld_until_all_checks_accept`, and `test_safe_tool_progress_continues_while_text_withheld`. Assert no rejected text reaches text events/console previews and accepted spans/hash match actual `stdout`.
- [ ] Include citation-enabled runs with no ordinary rules: withholding still applies, and `test_no_repair_binding_means_no_extra_request` asserts a violation stops without another call. Reuse a registered ordinary repair allowance when one exists; citation policy alone never creates one.
- [ ] Add `test_citation_repair_consumes_existing_allowance`, `test_denied_citation_is_not_model_repair`, and `test_hash_digits_are_not_domain_fact_support`. Assert a hard provider cap of 1 never becomes 2; repair cannot redispatch a completed effect. Extend `value_in_tool_output(..., tool_result_contract=None)` with explicit opt-in value `"v1"`: only that registration projects logical `.data` and uses a new guard version. The default remains `value-in-tool-output-v2` with identical descriptor/fingerprint. Never infer this setting from a model dictionary.
- [ ] Run `python -m pytest -q tests/test_citation_execution.py` for red; implement finalization and shared budget/guard integration. Do not add a formatting request or a second repair pool.
- [ ] Run it with `tests/test_generic_guards.py tests/test_generic_guard_edges.py tests/test_rule_tool_facts.py tests/test_guard_input_disclosure.py tests/test_invocation_budgets.py`.
- [ ] Commit: `feat: enforce citations within guarded answer acceptance`.

### Task 8: Add Runtime saved-input/evidence versions and legacy readmission

**Files:** Create Runtime `tests/test_tool_contract_turns.py`; modify
`conversation.py`, `conversation_preparation.py`, `frozen_turns.py`,
`turn_capture.py`, `input_views.py`, `runtime.py`, `adapter.py`.

**Interfaces:** `prepare_turn`, `turn`, `restore_turn` and variant preparation take
optional `tool_contract_bindings`. Allocate `TurnEvidence` v3 and prepared/frozen
encoding `conversation-turn-v4` for enabled contracts, after confirming these
slots remain unused. Existing evidence v1/v2 and prepared encodings v1–v3 retain
their exact old branches. V4 preserves optional context-view semantics explicitly.

- [ ] Add `test_disabled_prepared_input_and_evidence_are_identical`, `test_enabled_binding_changes_identity`, `test_incapable_reader_rejects_new_marker`, and `test_saved_answer_sidecar_matches_frozen_projection`. Assert old fixtures decode/replay with no new fields and new proof records reject missing/foreign hashes.
- [ ] Test finite attempt caps and reservation failures before spend; count citation instructions, new wire framing, events and sidecars within existing limits. Set fake clocks before constructing budgets/preparation for deterministic deadline tests.
- [ ] Run `python -m pytest -q tests/test_tool_contract_turns.py` for red; implement closed new codecs, restoration/capability checks and complete owned receipt capture without editing old encoded documents.
- [ ] Run it with `tests/test_frozen_turns.py tests/test_conversation_failure_evidence.py tests/test_context_pack_legacy.py tests/test_guard_input_views.py tests/test_conversation_bounds.py`.
- [ ] Commit: `feat: preserve tool contracts in versioned Runtime turn evidence`.

### Task 9: Complete direct/structured paths and capability coverage

**Files:** Create Runtime `tests/test_tool_contract_surfaces.py`,
`tests/test_tool_contract_installed.py`, `scripts/tool_contract_smoke.py`,
`.github/workflows/tool-contract-candidate.yml`; modify
`direct_tool.py`, `structured_tools.py`, `runtime.py`, `adapter.py`, `__init__.py`;
update `docs/structured-tools.md`, `docs/tool-effects.md` and new
`docs/tool-events-citations.md`; update `pyproject.toml` and
`tests/test_distribution_metadata.py` for the selected development identity.

**Interfaces:** Expose the three capabilities only on supporting surfaces. Direct
calls capture completed data/events with zero delivery records. Structured loops
support result/event codecs and explicit host-attested pure validation only.

- [ ] Add `test_direct_tool_has_zero_provider_exposure`, `test_structured_admit_route_needs_host_proof`, `test_structured_tool_outcome_route_needs_host_proof`, `test_bare_result_cannot_confirm_delivery`, and `test_native_terminal_and_incapable_pool_refuse_before_dispatch`. Assert callback/provider count 0 on unsupported admission and no public citation sidecar falsely reports Runtime delivery.
- [ ] Run `python -m pytest -q tests/test_tool_contract_surfaces.py` for red; finish plumbing/capability checks and scoped event ID remapping across the public entry points.
- [ ] Run it with `tests/test_direct_tool.py tests/test_structured_tools.py tests/test_terminal_completion.py tests/test_run_adapter.py tests/test_execution_budget.py tests/test_tool_contract_legacy.py`.
- [ ] Document actual supported combinations, event-only adoption, source-claim trust, reserved citation syntax, withholding, limits and explicit permission purposes. Add no MCP/parallel/delegation flag. Prepare the installed smoke case here so later tasks do not invalidate the completed Runtime candidate with missing Runtime files.
- [ ] Commit: `feat: expose supported tool contract surfaces and compatibility`. Then run the Runtime source checkpoint and build/qualify one exact-head development candidate `R*` with source audit plus the installed smoke, retaining original bytes. The focused candidate workflow produces the same `qualified-release` format with workflow name `Tool contract candidate`, exact source commit, artifact hashes and success; no publish step or native release-promotion matrix. Existing required SDK PR checks remain unchanged. Harness Tasks 10–15 install/use this exact `R*`, not old public Runtime wheels.

### Task 10: Bind Harness contracts and preflight capacity/identity

**Files:** Create Harness `tool_contracts.py`, `tests/test_tool_contract_bindings.py`;
modify `factory.py`, `graph_admission.py`, `admission_data.py`,
`conversation_bindings.py`, `conversation_rules.py`, `__init__.py`,
`.github/workflows/tests.yml`; create `tests/test_ci_tool_contract_upstream.py`.

**Interfaces:** Add optional `tool_contracts` to trusted workflow and conversation
bindings. `admit_tool_contracts(runtime, descriptors, bindings, limits) -> dict`
returns the owned identity/capability/reservation declaration; it performs no
handler, provider or source work.

Freeze an enabled-only schema allocation table before changing writers: use the
next unused strict version in each run/session/receipt family and record it in
the compatibility fixtures. Existing versions remain byte-for-byte readers and
writers; `toolContractV1` is not an unknown-field extension of an old schema.

- [ ] Add `test_absent_contract_preserves_workflow_and_session_identity`, `test_events_only_admits_legacy_tools`, `test_unknown_capability_refuses_before_spend`, and `test_contract_binding_change_requires_readmission`. Assert exact prior hashes/default omissions and zero calls on refusal.
- [ ] Add worst-case event/evidence/result framing reservation tests, per-policy smaller bounds, finite attempt cap tests and a default-capacity success witness. No silent dropping of required citation evidence to fit storage.
- [ ] Install candidate `R*` for Harness source tests and bind its full source identity in the existing upstream CI pin. Assert `test_harness_contract_ci_uses_exact_runtime_source` and admission refuse a mixture with public 0.9.19. Do not change unrelated release workflows or pretend the old version supports the new API.
- [ ] Run `python -m pytest -q tests/test_tool_contract_bindings.py` for red; implement owned binding serialization, current runtime registry verification and preflight reserves.
- [ ] Run it with `tests/test_admission_data.py tests/test_runtime_adapter_binding.py tests/test_conversation_bindings.py tests/test_workflow_rules_admission.py tests/test_context_pack_capacity.py`.
- [ ] Commit: `feat: admit scoped tool contracts in Harness bindings`.

### Task 11: Adapt exact context-pack exposures into evidence

**Files:** Create Harness `context_packs/tool_contracts.py`,
`tests/test_context_pack_citations.py`; modify `context_packs/authorization.py`,
`context_packs/reader.py`, `context_packs/records.py`, `context_packs/bindings.py`.

**Interfaces:** `pack_evidence_bindings(frame, runtime_evidence, bindings)` creates
owned initial/read origin records from verified pack exposure data. Add explicit
pack authorization purpose `citation`; both generic and pack authorizers must
allow it. Preserve legacy `ctx_...` IDs and reader wire behavior when disabled.

- [ ] Add `test_inline_selected_context_is_citable`, `test_index_only_entry_is_not_citable`, `test_partial_read_cannot_cite_parent`, and `test_generic_and_pack_authorizers_both_required`. Assert the partial representation/hash and lineage match actual captured bytes; no source refetch occurs.
- [ ] Add `test_private_authoritative_facts_never_become_sources`, `test_unrecognized_citation_purpose_denies`, and revocation before model use/citation/view. Assert matching IDs/hashes cannot override a denied authorization.
- [ ] Run `python -m pytest -q tests/test_context_pack_citations.py` for red; implement the adapter and versioned enabled reader path, including decoding new private result frames before deriving actual reads.
- [ ] Run it with `tests/test_context_pack_reader.py tests/test_context_pack_authorization.py tests/test_context_pack_validation_scope.py tests/test_context_pack_workflow_disclosure.py tests/test_context_pack_legacy.py`.
- [ ] Commit: `feat: bind citations to verified context-pack exposure`.

### Task 12: Persist workflow evidence and preserve recovery

**Files:** Create Harness `tests/test_tool_contract_workflow.py`,
`tests/test_tool_contract_recovery.py`; modify `engine.py`, `contracts.py`,
`tool_contracts.py`, `context_packs/workflow_execution.py`,
`context_packs/workflow_records.py`.

**Interfaces:** `freeze_tool_contract_receipt(...)` and
`validate_tool_contract_receipt(...)` bind raw completion, model projection,
delivery, final answer/sidecar and reservations to the invocation. Allocate an
enabled run/receipt version with `toolContractV1`; preserve older state paths.

- [ ] Add `test_saved_workflow_receipt_adopts_without_new_execution`, `test_projection_failure_preserves_completed_effect`, `test_unknown_delivery_cannot_be_recovered_from_events`, and `test_corrupt_sidecar_blocks_adoption`. Assert after crash/save/reopen `provider_calls_delta == 0` and `handler_calls_delta == 0`.
- [ ] Add a guarded workflow using selected pack context plus complete private facts; assert both old guard authority and current citation authorization survive adoption. Capture each public event with the same call/attempt/step identity.
- [ ] Run `python -m pytest -q tests/test_tool_contract_workflow.py tests/test_tool_contract_recovery.py` for red; integrate receipt-first adoption and existing repeatable controller validation without rerunning Runtime guards.
- [ ] Run them with `tests/test_recovery_contracts.py tests/test_bounded_tool_recovery.py tests/test_context_pack_workflow_recovery.py tests/test_terminal_first_tool_recovery.py`.
- [ ] Commit: `feat: adopt workflow tool evidence from durable receipts`.

### Task 13: Add conversation retention and authorized citation views

**Files:** Create Harness `tool_contract_views.py`,
`tests/test_tool_contract_conversation.py`, `tests/test_tool_contract_views.py`;
modify `conversation.py`, `session_contracts.py`, `session_codec.py`,
`conversation_packs.py`.

**Interfaces:** `resolve_citation_view(receipt, evidence_id, view_bindings) -> dict`
returns an authorized captured representation or closed unavailable result;
`project_retained_tool_event(...)` reauthorizes display. Retained imports require
verified receipts, current model-use permission and a new submitted view.

- [ ] Add `test_next_turn_requires_explicit_retained_import`, `test_old_id_in_text_grants_nothing`, `test_cross_tenant_receipt_is_refused`, `test_view_revocation_does_not_rewrite_accepted_answer`, and `test_retained_event_needs_current_display_grant`. Assert private locators/guard facts never enter public views and no URL is fetched.
- [ ] Add crash/adoption/retry tests proving answer/citation hashes stay paired and completed work is not repeated. New actor/policy defaults cannot replace saved binding identity silently.
- [ ] Run `python -m pytest -q tests/test_tool_contract_conversation.py tests/test_tool_contract_views.py` for red; implement enabled conversation/session/receipt versions and safe view helpers.
- [ ] Run them with `tests/test_conversation_recovery.py tests/test_conversation_failed_retry.py tests/test_conversation_input_caps.py tests/test_context_pack_history.py tests/test_context_pack_conversation_recovery.py`.
- [ ] Commit: `feat: retain and resolve authorized conversation citations`.

### Task 14: Verify memory/file/PostgreSQL record and capacity support

**Files:** Create Harness `tests/test_tool_contract_stores.py`; modify only as
needed `memory_session_store.py`, `file_session_store.py`, `file_store.py`,
`store.py`, `run_store.py`, `session_store.py`, `contracts.py`, `session_codec.py`,
and adapter `adapters/postgres/src/prosaic_harness_postgres/{store,session_store}.py`.

**Interfaces:** Supporting stores explicitly admit the enabled record marker and
advertise writer/reader support. New codec versions are not silently accepted by
old readers. Existing fencing, row/state limits and namespace ownership persist.

- [ ] Parameterize `test_new_contract_roundtrips_and_reopens`, `test_legacy_records_are_unchanged`, `test_old_reader_refuses_enabled_marker`, and `test_default_capacity_accepts_bounded_contract`. Test both run and session records against memory/file and PostgreSQL 16/18.
- [ ] Add malformed/truncated sidecar, record-capacity refusal, worker DDL denial, displaced owner and lost-acknowledgment recovery witnesses. Assert completed effects stay fenced and startup/readiness emits no schema DDL.
- [ ] Run new memory/file cases for red, then implement explicit codec/capability support using existing JSON storage if it satisfies limits. If actual schema changes are necessary, stop this task and document a separate owner migration before adding DDL.
- [ ] Run `python -m pytest -q tests/test_tool_contract_stores.py tests/test_session_contracts.py tests/test_run_store.py tests/test_file_session_store.py tests/test_context_pack_stores.py`; run the same new store cases on owned PostgreSQL 16/18 with existing repository fixture configuration.
- [ ] Commit: `feat: support bounded tool contract records in durable stores`.

### Task 15: Qualify Runtime/Harness installed consumers once

**Files:** Runtime reuses Task 9's installed test, smoke and original `R*` artifact;
create Harness `tests/test_tool_contract_installed.py`,
`scripts/tool_contract_smoke.py`, `.github/workflows/tool-contract-candidate.yml`;
update Harness public exports, relevant docs and package inventories.
Development-version/package metadata changes belong at each repository's final
candidate checkpoint, before its exact source commit is built. Include
`pyproject.toml`, adapter metadata if changed, and
`tests/test_distribution_metadata.py`: candidate Harness requires the actual
new Runtime candidate version floor; a changed adapter requires the actual new
Harness candidate floor. Do not advertise installability with old public SDKs
that lack imported APIs; final stable floors are chosen during later release work.

**Interfaces:** One source-identified Runtime candidate wheel and one Harness
candidate wheel, plus adapter wheel only if its implementation changed. Record
full source commits/versions/hashes; keep Core/recorder original bytes. Do not
replace stable artifacts or public dependency manifests.

- [ ] Add subprocess consumer tests that import only installed SDKs outside checkout paths, execute event-only legacy callbacks and a typed result/cited answer, and reopen a Harness receipt. Assert actual import ownership, exact bytes and supported capabilities, not just symbol existence.
- [ ] Reuse original Runtime `R*`; build the completed Harness head once as `H*` using the existing artifact machinery and run the smoke scripts against that exact pair. Build an adapter candidate only if Task 14 changed it. Add rebuilt-source resource/import coverage to the same qualification invocation rather than building another candidate later.
- [ ] Run the affected Harness source suite at this checkpoint, including the new regression files and existing guards, tool effects, conversations and pack compatibility. Runtime's source checkpoint is Task 9; repeat it only if Runtime actually changed afterward. Use focused reruns for concrete failures.
- [ ] Document candidate source identities, new record/readmission rules and limits in `docs/tool-events-citations.md` in each SDK. Update current source README/backlog descriptions without touching historical release notes or artifacts.
- [ ] Commit Harness consumer/documentation changes before building final `H*`; retain the exact candidate bytes plus a complete five-SDK local handoff manifest for Lab. The focused Harness candidate workflow records `R*` provenance and emits the original `qualified-release` artifact under `Tool contract candidate`, not `Publish SDK`. There is no publishing/release-promotion step. Lab Tasks 16–17 install/audit this pair; source-development imports are never presented as installed candidate qualification.

### Task 16: Add the Lab public-SDK scenario and copyable blueprint

**Files:** Create Lab `src/prosaic_integration_lab/tool_evidence.py`,
`lab_runner/tool_evidence.py`, `lab_runner/blueprints/tool_evidence/{__init__,host}.py`,
`lab_runner/blueprints/tool_evidence/{README,LICENSE,NOTICE,runtime.yml}`,
`lab_runner/blueprints/tool_evidence/.prosaic/subagents/analyst.md`,
`tests/unit/test_tool_evidence_scenarios.py`,
`tests/blueprint_acceptance/test_tool_evidence.py`; modify blueprint registry,
`pyproject.toml`, `dependencies/public-build-inputs.json` and distribution inventory tests.

**Interfaces:** `require_tool_evidence_sdk()` checks exact installed payloads and
capabilities before resources; `run_tool_evidence_scenario(...) -> dict` returns a
bounded sanitized report. Blueprint copy name is `tool-evidence`.

- [ ] Add a synthetic `dependents` tool returning 14 actual fixture records, authorized component/count events and a citation to captured output. Parameterize both supported API provider wires; do not implement SSE/model execution inside Lab that duplicates SDK logic.
- [ ] Add negative scenario tests for hidden neighboring fields, fabricated IDs, index-only evidence, partial reads, replay, revocation and unsupported native/structured automatic citations. Assert exact handler/provider counts and public/private view separation.
- [ ] Install and audit the complete Task 15 local handoff manifest before scenario tests; keep Core/recorder original bytes. Task 17 adds hosted run-ID curation for this same manifest contract, not a different execution path.
- [ ] Run `python -m pytest -q tests/unit/test_tool_evidence_scenarios.py tests/blueprint_acceptance/test_tool_evidence.py` for red in the exact candidate SDK environment; implement the host/scenario/complete copyable resources.
- [ ] Run those tests plus existing blueprint copy/package inventory tests. Verify wheel and rebuilt-source resources contain the full example and no neighboring private test/config artifacts.
- [ ] Commit: `feat: demonstrate safe tool events and captured citations in Lab`.

### Task 17: Add a focused candidate acceptance lane

**Files:** Create Lab `tests/acceptance/test_tool_evidence.py`,
`tests/unit/test_tool_evidence_hosted.py`, `.github/workflows/tool-evidence.yml`;
modify `lab_runner/__main__.py`, `lab_runner/gates.py`,
`lab_runner/stack.py`, `scripts/provision.py`,
`scripts/prepare_sdk_candidates.py`, `src/prosaic_integration_lab/dependencies.py`
only where candidate validation needs new explicit fields, and related curation tests.

**Interfaces:** New explicit mode `--mode tool-evidence`, using a complete paired
candidate manifest and the Task 15 original wheels. It uses owned conversation/
context-pack infrastructure, a sanitized report and required-case accounting.
Current released manifests/trains and historical mode requirements remain unchanged.

- [ ] Define twelve named logical cases: safe approved event; event-only legacy return; denied/secret display; admitted typed output; fabricated citation; selected inline citation; exact deferred partial read; replay with one effect; receipt adoption with zero new work; retained-source revocation; metadata-number guard isolation; unsupported/forged delivery refusal. Parameterize all twelve over provider IDs `openai-compatible` and `anthropic`: **24 required pytest cases per architecture/database cell**. Gate names include those parameter IDs; `ALL_COUNTS['tool-evidence'] = 24`. No required case skips.
- [ ] Add runner tests proving missing/mismatched candidates or host wheel bytes refuse before stack allocation, every required case is present, no candidate case skips, sanitized failure reports expose no arguments/locators, and cleanup is verified on success/failure.
- [ ] Add `test_tool_contract_storage_is_enabled_only_by_owned_provisioner`: thread an explicit `tool_contracts` fixture flag through `OwnedStack` and its private provision config; run required namespace initialization under the owned schema principal. Worker startup/readiness does not migrate or infer permission from the CLI mode.
- [ ] Run `python -m pytest -q tests/unit/test_tool_evidence_hosted.py tests/unit/test_tool_evidence_scenarios.py` for red; implement explicit `--tool-contracts` candidate curation and the mode. In this feature mode only, admit the exact `Tool contract candidate` workflow path `.github/workflows/tool-contract-candidate.yml`, successful run/source commit and original `qualified-release` digests from Tasks 9/15; do not relax existing `Publish SDK` validation for other modes. Feature tests remain capability-gated outside this lane; the lane turns missing SDK support into failure, not skip.
- [ ] Run owned `python -m lab_runner test --mode tool-evidence --candidate --candidate-manifest PATH --postgres-version 16` and repeat with 18 using the already curated wheels. Hosted workflow requires AMD64/ARM64 × PostgreSQL 16/18, zero required-case skips, the installed blueprint check and the original consumer image digest. Reuse original candidate inputs; do not dispatch unrelated release matrices.
- [ ] Commit: `test: qualify tool events and citations with exact candidate SDKs`.

### Task 18: Final regression, compatibility audit and independent review

**Files:** Update the Harness Cerebro backlog/design implementation status and the
SDK/Lab feature documentation to match actual behavior. No new subsystem belongs here.

**Interfaces:** Produce a reviewer-ready cross-repository change set with exact
source/candidate identities, focused test evidence and explicit unsupported cases.

- [ ] Self-audit every spec requirement against Tasks 1–17 and the acceptance matrix below. Recheck disabled golden fixtures against their original provenance; never regenerate them merely to make a failing assertion pass.
- [ ] Verify both SDK source suites, installed wheel/rebuilt-source consumers, targeted store cases and the new Lab lane have passing evidence on the actual final code. Repeat only suites invalidated by later code changes; documentation-only edits need diff/link/example checks.
- [ ] Use the user's selected native method: one fresh independent whole-branch review after implementation, concentrating on disclosure, false delivery proof, replay, schema/readmission and legacy identities. Resolve substantive findings with focused regression tests.
- [ ] Confirm clean implementation branches, record each repo commit, candidate hash and precise validation commands/results. Present reviewable diffs/PR scope in Runtime → Harness → Lab dependency order. Existing required hosted checks still apply when PRs are opened; do not bypass them or add duplicate optional promotion runs.
- [ ] Stop at implemented/reviewed changes. Merge, stable-version selection, public manifest adoption and release publication are separate authorized follow-on work; keep parallel execution, MCP and sub-agents in the backlog.

## Acceptance and backward-compatibility matrix

| Boundary | Required evidence | Owner |
| --- | --- | --- |
| Feature absent | Byte-identical descriptors, outputs, event shapes, prepared hashes, old receipt replay | Tasks 1, 8, 10, 14 |
| Events only | Same handler/result shape; approved scalars only; payload-free telemetry | Tasks 3, 9, 16 |
| Typed success/failure | Data schema and both framing limits; `ToolFailure`/effect uncertainty unchanged | Tasks 2, 4 |
| Journal replay | One effect total, old captured revision, present-invocation identity, explicit replay labeling/current grants | Tasks 2–5, 12–14 |
| Guard correction/compaction | Actual checked/submitted selections only; metadata excluded from domain fact support | Tasks 5, 7 |
| Citation acceptance | Exact eligible reference, current permission, final UTF-8 spans/hash, bounded existing repair, withheld text | Tasks 6–8 |
| Pack source | Selected inline or actually read representation; no index/private/parent-widening authority | Task 11 |
| Crash/reopen | Receipt-first adoption, zero repeat provider/tool/Runtime-guard work, current viewing/import grants | Tasks 12–14 |
| Unknown/new records | Explicit capable readers; old versions/markers fail closed; no automatic rewrite | Tasks 8, 10, 14 |
| Native/terminal/external structured driver | Explicit supported capability matrix and refusal before unsupported automatic execution | Tasks 6, 9, 16–17 |
| Packaging/public consumer | Original candidate bytes, imports outside checkout, complete copied resources, immutable stable manifests | Tasks 15–17 |

## Validation cadence and dependency handoff

Use repository virtual environments and existing synthetic/owned resource fixtures.
Run the named focused files after each task. Record actual pass/fail counts rather
than prescribing counts for existing evolving suites. PostgreSQL checks use owned
namespaces and fixed tested versions; never a shared application database.

Runtime is the first dependency checkpoint. Harness consumes that completed
Runtime candidate, then Lab consumes the exact completed pair. If a dependency
changes, invalidate only the affected downstream evidence and rerun those checks.
Do not call old public wheels capable merely because the API names were planned.
New feature manifests are candidate manifests until real stable artifacts exist.

This plan document itself requires local link/path consistency and diff checks.
It does not run product tests, build distributions, modify dependencies, open PRs
or trigger CI. Execution preference remains native implementation with one
independent whole-branch review; it does not need to be selected again.
