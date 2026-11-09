# Context Packs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Harness workflow declare each agent/node's context from Markdown files, admitted input or accepted earlier outputs, with bounded Runtime fitting, complete private validation facts, and durable recovery.

**Architecture:** Harness owns typed source snapshots, named pack declarations, per-node resolution, evidence projection, authorization and controller persistence. Runtime owns role-separated preparation, guarded input views, one bounded fitting transaction and public frozen restoration. Existing pack-free execution and serialized records remain compatible; PostgreSQL stays optional.

**Tech Stack:** Python 3.11+, existing dataclasses/JSON/jsonschema/PyYAML, pytest and build; existing optional psycopg adapter. No new production dependency, database requirement, model execution engine, Core Markdown kind, Node execution, or Echelon import.

**Spec:** [Context-pack design](../specs/2026-11-08-context-packs-design.md), with [review findings CP-01–CP-15](../specs/2026-11-08-context-packs-review.md). Read both before executing a task.

**Status:** Implemented locally through native execution and one independent review.
The original task checklists below preserve the approved plan; actual completed
checks, exact artifact hashes and limitations are in the
[qualification report](../../verification/2026-11-09-context-packs-qualification.md).
Hosted promotion gates remain pending. No push, tag or publication was performed.

## Global Constraints

- Python 3.11+; use apply_patch for edits. Run `.venv/bin/python -m pytest` and `.venv/bin/python -m build` in each implementation repository.
- Serialized new public contracts use camelCase; Python APIs use normal snake_case. Closed records, finite JSON, owned copies, bounded nesting and strict UTF-8; no executable deserialization.
- Per-node declared business evidence is the opted-in model projection. Undeclared input fields, file bodies and artifact bodies do not fall through. The original task is mandatory.
- Pure construction/composition invokes no authorization callbacks, source reads, models, tools, migrations or probes. Existing explicit file-evidence capture happens before composition.
- Runtime alone encodes/counts provider-native requests. No token/4 estimates, universal tokenizer claim, hidden summarization, source refresh, semantic reranking or automatic larger-model escalation.
- GuardContext.input_data remains the actual initial model input. Authoritative input is separate and never implicitly a tool output, seen-ID source, reader permission or model instruction.
- Private-access guards are fail-only: `action=fail`, `fixes=False`, `echo_values=False`. Model-only guards retain existing bounded repairs/retries.
- Context authorization covers a bounded logical invocation, with checks on deferred reads and subsequent retained-history reuse. It does not retract bytes already sent.
- The controller owns state writes. Save reconstructable pending data before dispatch; completed receipts follow execution. No automatic retry after uncertain effects.
- Same-attempt recovery preserves work charges; an explicitly acknowledged new retry gets admitted execution allowance under the existing aggregate quotas and frozen selection.
- Runtime guards do not rerun on receipt adoption. Harness controller validators may repeat, against frozen CheckContext, under explicit repeatable/read-only host attestations.
- Retain current store quotas. Default workflow receipt/state limits remain 1 MiB / 4 MiB. Count every duplicated occurrence and reserve output, failure, metadata and tool-outcome headroom before effects.
- Core 0.5.0 contracts and distribution names remain unchanged. Runtime PostgreSQL recorder 0.3.0 is a compatibility witness, not a schema migration target.
- New neutral agent prose uses paired ALWAYS/NEVER behavioral rules; model IDs, endpoint credentials and source permissions remain host configuration.
- Preserve dirty working trees, old release bytes, qualification evidence and unrelated branches. Do not use sibling editable installs as installed-package qualification.
- All contract tests use local synthetic providers and disposable stores; no paid calls or production data. Required database/platform qualification fails when infrastructure is missing instead of silently skipping.

### Exact limits to implement

| Policy field | Default |
| --- | --- |
| max_source_aliases / max_slots / max_captured_items | 16 / 32 / 128 |
| max_item_bytes / max_total_content_bytes | 262144 / 2097152 |
| max_snapshot_bytes | 3145728 |
| max_inline_bytes / max_index_bytes | 49152 / 8192 |
| max_variants / max_variant_bytes | 8 / 524288 |
| max_labels_per_item / max_json_depth / max_json_nodes | 16 / 32 / 16384 |
| composition_timeout_ms | 250 |
| reader max_body_bytes / max_result_bytes | 16384 / 24576 |
| AuthoritativeInputLimits max_bytes / max_depth / max_nodes | 2097152 / 32 / 65536 |
| feedback catalog per entry / entries / total encoded bytes | 512 / 64 / 32768 |

These are independently bounded ceilings, not a promise that all maxima fit one default receipt. Keep the existing ContextPolicy defaults and limits; reuse its cumulative ContextWorkState.

## Review Focus

- Same agent used twice with different packs: no mutable default leaks into the second node; required pins and task context survive overrides (Tasks 6, 7, 13).
- Revocation after a reader result or derived answer is committed: even a later turn without a pack cannot silently resend that history (Tasks 8, 14).
- Source data contains quotes/control characters, decomposed Unicode or repeated revision labels: identity, encoded capacity and attribution remain exact (Tasks 1, 2, 12).
- A lost storage acknowledgement occurs between authorization, readmission, provider dispatch, receipt save and adoption: no automatic repeated effect or replenished work (Tasks 9–11, 13, 14).
- A custom guard/validator/factory copy drops an access declaration or returns a secret in an error string: fail before effects or produce only safe feedback, including public observers (Tasks 3, 6, 8, 13).

## Baseline, repositories and execution order

This is one coordinated plan because Runtime/Harness share prepared-turn and receipt interfaces; they are not independent products to redesign separately. Runtime tasks still produce a separately testable public API before Harness orchestration consumes it.

Upstream main was inspected read-only on 2026-11-08:

| Repository | Reviewed commit | Project version |
| --- | --- | --- |
| Runtime | `3bdcd79198f770af5a0ef8630064ac9bb8c877f2` | 0.9.17 |
| Harness | `197d3820dff7f94f9c3457b9d6eac671a742d763` | 0.9.12 |

The local Runtime branch is older and dirty. Local Harness main is also older than upstream, with the four design commits and unrelated dirty edits. Start code work from current verified upstream in isolated implementation workspaces; do not overwrite either checkout or rebuild missing context-assembly code from the old branches. Preserve the design/plan independently when carrying documentation into the Harness implementation branch.

Use task-local root variables in execution records: `RUNTIME_TREE`, `HARNESS_TREE`, `LAB_TREE`, `PACK_WHEELHOUSE`. Commands below are run from the task's indicated repository root; paths are repository-relative within those roots. They do not assume these worktrees already exist.

Dependency order:

```text
0 -> 1 -> 2 ---------------------> 6 -> 7 -> 8 -> 9 -> 10 -> 11
0 -> 3 -> 4 -> 5 ---------------------------------------> 12
                 7,8,9,10,11,12 ------------------------> 13 -> 14
                                                          13,14 -> 15 -> 16
```

Tasks 1–2 can be tested without a new Runtime. Tasks 3–5 can be tested without Harness. Never expose orchestration as complete until Tasks 13–16 qualify it.

## File and responsibility map

Paths marked new are intentional; other paths exist in the reviewed upstream tree, even where absent from the older local checkout.

| Repository / files | Responsibility |
| --- | --- |
| Harness `src/prosaic_harness/context_packs/__init__.py`, `types.py`, `codec.py` (new) | Public immutable records, policies, errors and canonical encoding using existing bounded JSON primitives. |
| Harness `context_packs/selection.py`, `sources.py`, `projection.py` (new, under that package) | Pure selection/variants; source normalization; per-node resolution and complete model projection. |
| Harness `context_packs/bindings.py`, `authorization.py`, `reader.py` (new) | Trusted declarations, use/read authorization and exposure lineage; invocation-scoped reader. |
| Harness `context_packs/records.py`, `capacity.py`, `feedback.py` (new) | V3 controller extensions, encoded reservations and safe feedback. |
| Runtime `src/prosaic_runtime/input_views.py`, `frozen_turns.py`, `input_variants.py` (new) | Private input bounds/bindings, frozen restoration, candidate preparation. |
| Runtime `conversation.py`, `conversation_preparation.py`, `runtime.py`, `turn_capture.py` | PreparedTurn integration, public methods, execution readmission and private evidence. |
| Runtime `context_assembly.py`, `context_work.py`, `context_execution.py` | One shared fitting transaction; finalization/readmission exactly once. |
| Runtime `rule_types.py`, `rule_hooks.py`, `rules.py`, `guards/*.py` | Access-aware guard protocol, enforcement and qualified generic registrations. |
| Harness `factory.py`, `graph_admission.py`, `workflow.py`, `bundles.py`, `workflow_rules.py`, `conversation_rules.py` | Authoring/catalogue admission, copies/fingerprints, v2 guarded-pack proof. |
| Harness `engine.py`, `conversation.py`, `conversation_bindings.py`, `conversation_workflow.py` | Existing controller integration; no parallel execution engine. |
| Harness `contracts.py`, `session_contracts.py`, `session_context.py`, `session_store.py`, `run_store.py` | Preserve legacy reducers; add closed opt-in record/capability branches. |
| Harness `file_store.py`, `file_session_store.py`, `memory_session_store.py`; PostgreSQL adapter schema/store/CLI modules | Explicit storage initialization, migrations, owner/CAS/lease semantics. |
| Both repositories' `scripts/*smoke.py`, `.github/workflows/*`, metadata and docs | Installed ownership, legacy/new gates and release artifacts. |

## Interface decisions used throughout the tasks

These signatures are the implementation target. New optional keywords must be forwarded by frozen copies and snapshots. Absent/default options must not enter legacy identity material.

### Harness records and source bindings

Task 1 defines `ContextScope(namespace, environment, application, tenant, actor, billing_account=None)` with the same bounded owner fields as ConversationScope; `from_conversation(scope)` copies that identity, never derives authorization from accounting.

Define immutable records:

```python
ContextSource(alias, identity, revision, outcome, *, ranked_item_ids=())
ContextItem(item_id, source_alias, source_revision, content, *,
            locator=None, label=None, labels=None, derived_from=())
ContextSnapshot.from_items(items, *, sources, scope_binding) -> ContextSnapshot
ContextSlot(source, *, item_ids=(), labels=None, required=False,
            min_items=None, max_items=1, priority=0,
            representation=None, availability='inline', allow_partial=False)
ContextPackSpec(identity, version, slots, *, task_source=None)
ContextPackPolicy(...)  # fields/defaults in the exact-limits table
ContextPacker(*, policy=ContextPackPolicy())
ContextPacker.compose(spec, snapshot) -> ContextPackCandidates
ContextPacker.select(candidates, index, envelope_digest) -> PreparedContextPack
```

The Python-only `min_items=None` means omitted: normalize it to 1 for required slots and 0 otherwise. Explicit zero remains distinguishable; a serialized null minItems is invalid, and canonical records always contain the normalized integer. `sources` is explicit so an empty capture has a complete/partial/unavailable status rather than an invented completion claim. Align the illustrative design example with this keyword when implementing public documentation.

`ContextPackCandidates` exposes owned `variants`, `reports`, `candidate_identity`, `snapshot` and `spec`. A variant is an evidence envelope, not the complete Runtime input root. `PreparedContextPack` exposes owned `envelope`, `report`, `reference`, `snapshot`, `spec` and `pack_identity`. Use canonical `to_dict()`/bounded `from_dict()` for data records; callbacks are never hydratable records.

Source bindings are inert typed values: `InputSource(pointer)`, `EvidenceSource(path)`, `ArtifactSource(step)`. Built-in normalization yields a `root` item for each bound input/file/output value. Do not implicitly fan out arbitrary JSON arrays or parse Markdown headings; finer units come from explicit supplied snapshots/prior steps. Preserve exact locators and captured provenance.

Task 6 defines:

```python
ContextAuthorizer(identity, version, authorize)  # (ContextUse) -> literal bool
ContextPackBindings(*, specs, sources, scope, authorizer,
                    agent_defaults=None, required_packs=None)
```

Use normalized pin maps `required_packs={'agents': {...}, 'nodes': {...}}`; applicable pins must agree. Source/spec/agent/node aliases are bounded references. The binding identity includes descriptors and static declarations, not callback repr/source. ContextUse has purposes `invocation`, `deferredRead`, `historyReuse`, `validation`, `retainedRead`.

### Runtime APIs

Task 3 defines `AuthoritativeInputLimits(max_bytes=2097152, max_depth=32, max_nodes=65536)` and first extends prepare_turn with the private/profile keywords. Task 4 completes the frozen interfaces, then Task 5 adds variant fitting:

```python
ProsaicRuntime.prepare_turn(artifact, *, message, history=(), input_data=None,
    policy=None, limits=None, workspace=None, context_policy=None,
    token_counters=None, context_selection=None, context_report=None,
    context_work=None, input_profile=None, authoritative_input_data=None,
    authoritative_input_profile=None, authoritative_input_limits=None) -> PreparedTurn

ProsaicRuntime.prepare_turn_variants(artifact, *, message, history=(),
    input_data_variants, policy=None, limits=None, workspace=None,
    context_policy, token_counters, input_profile=None,
    authoritative_input_data=None, authoritative_input_profile=None,
    authoritative_input_limits=None) -> PreparedTurn

PreparedTurn.export_frozen_input() -> FrozenTurnInput
ProsaicRuntime.restore_turn(artifact, *, history=(), frozen_input,
    policy, limits, context_policy=None, token_counters=None,
    workspace=None, context_work=None, fresh_attempt=False) -> PreparedTurn
```

Preserve any existing optional arguments not displayed in this signature, including rule/accounting/lifecycle integration. Context work is a separately checked mutable resource ledger. Default restoration rejects a reset relative to retained work. Only a trusted controller that has independently admitted a new attempt may set fresh_attempt=True; Runtime validates the reset against saved initial preparation charges and required readmission headroom. This flag is never an HTTP/client field or inferred consent to retry.

PreparedTurn adds `selected_input_data` and `input_variant_selection`. Task 4 defines immutable bounded `FrozenTurnInput` and `InputVariantSelection`, both with owned `to_dict()`. Accept typed or plain bounded frozen data in restore, but readmit against actual approved artifact, policies, history and live descriptor registrations. No frozen record is authority.

Guard gets optional `input_access='shared'`; accepted values are `shared`, `model`, `authoritativeAndModel`. `generic_guards(*, input_access='shared')` permits explicit audited model registrations without changing the no-keyword legacy results. GuardContext adds `authoritative_input_data`, guarded by access mode. Task 3 must also extend individual generic-guard constructors consistently.

### Controller extension points

Task 6 adds optional `WorkflowBindings(context_packs=..., feedback_catalog=..., repeatable_validators=...)` and forwards those through factory/bundle copies. Trusted static loading accepts `Workflow.load(..., context_packs=..., feedback_catalog=..., repeatable_validators=...)`. Existing positional/keyword callers remain valid.

Task 14 adds `ConversationBindings(..., context_packs=None)` and `Conversation.send(..., context_pack=None)`. Authoritative conversation facts derive from the supplied complete snapshot; there is no client-controlled authoritative-input passthrough. Attached workflow interpretation still rejects pack arguments.

Task 12 defines `ContextPackReader(bindings, *, max_body_bytes=16384, max_result_bytes=24576)`, `as_tool() -> CustomTool`, and `activate(invocation_scope, prepared_pack) -> context manager`. Reader registration is stable; activation does not mutate the tool descriptor. Registry entries are local to the reader instance, lock-protected and keyed by actual invocation scope, never process-global or assumed to propagate through contextvars to worker threads.

## Task 0: Establish clean execution baselines and legacy witnesses

**Files:** Create ignored `output/context-packs/baseline.json` and ignored wheelhouse/qualification directories in each implementation checkout; create Harness `tests/fixtures/context_packs/legacy/` and Runtime `tests/fixtures/frozen_turns/legacy/` during this task's compatibility commit.

**Interfaces:** Consumes the reviewed upstream commits and design commits. Produces a recorded clean base, installed released-package witnesses and immutable legacy fixture bytes for Tasks 3–16.

- [ ] Detect existing worktree isolation and follow using-git-worktrees at execution time; prefer native worktree tools. Use `codex/context-packs-runtime` and `codex/context-packs-harness`. Do not stash, reset, check out over, or commit unrelated local edits.
- [ ] Refresh upstream read-only refs, compare against the reviewed commits, and record any newer changes before choosing the implementation base. Carry the design/review/this plan into the Harness checkout as documentation-only commits; never cherry-pick unrelated user code.
- [ ] Create per-checkout `.venv`; install declared test/build dependencies and verified Core 0.5.0. Prepend that environment's bin directory to the test process PATH so inspection resolves its installed prosaic CLI, not a sibling checkout or unrelated global command. Record exact Python/platform, dependency versions and base SHAs. Run `.venv/bin/python -m pytest` in each clean checkout and the existing conversation smokes. Existing failures are recorded/resolved before attributing regressions to this work.
- [ ] In a separate environment install released Runtime 0.9.17, Harness 0.9.12 and Harness PostgreSQL 0.4.1 with verified hashes. Generate synthetic representative Runtime v1/v2 preparation identities, rule fingerprints, session v1/v2 records/receipts and workflow checkpoint v2/receipt v1. Retain their canonical bytes and provenance; use no real prompts/DSNs.
- [ ] Add `test_released_legacy_fixtures_load_unchanged` in each repository's new legacy-witness test file. Assert known fixture digests, identity values and record versions before new fields exist. The assertion is exact byte/identity equality, not regenerating an expected value with the new encoder.
- [ ] Commit only synthetic fixtures and their tests: `test: pin released context compatibility witnesses`. Worktree setup/venvs/run artifacts remain ignored.

## Task 1: Harness immutable pack contracts

**Files:** Create `context_packs/{__init__,codec,types}.py`; modify `src/prosaic_harness/__init__.py`; create `tests/test_context_pack_contracts.py`, `tests/support/context_pack_cases.py`.

**Interfaces:** Consumes existing bounded session_codec behavior. Produces all Harness records/limits/source bindings described above, and test helpers `snapshot_case()`, `spec_case()`, `scope_case()` with synthetic content and explicit source outcomes.

- [ ] Write failing tests `test_snapshot_owns_nested_values`, `test_empty_capture_requires_source_outcome`, `test_all_policy_defaults`, `test_records_are_closed_finite_utf8`, `test_task_slot_is_nonempty_input`, `test_record_roundtrip_preserves_identity`. Pin constants from the limits table and reject bool-as-int, cycles, duplicate keys, surrogates and over-bound metadata.
- [ ] Run `.venv/bin/python -m pytest tests/test_context_pack_contracts.py -q`; observe missing contract failures.
- [ ] Implement the constructors/codecs and ContextPackError closed codes from the spec. Own encoded JSON once and return copies; do not introduce a second subtly different canonical hash algorithm. Item identity includes source alias/identity, revision, item ID, source locator, representation and content digest. Pure pack modules must not eagerly import new Runtime classes: use TYPE_CHECKING annotations and capability-checked local imports for new execution APIs so legacy-only imports remain usable in the controlled compatibility harness.
- [ ] Add boundary tests for multi-byte labels/ranges, RFC 6901 escapes, absent vs partial vs complete-empty sources, `required=True,min_items=0`, and default-single-item cardinality. Required task uses one whole nonempty item and cannot be generated from a prior artifact.
- [ ] Rerun the task tests and legacy witnesses. Commit `feat: add immutable context pack contracts`.

## Task 2: Pure selection, bounded variants and coverage reports

**Files:** Create `context_packs/selection.py`; modify package/root `__init__.py` exports; create `tests/test_context_pack_selection.py`, `tests/test_context_pack_limits.py`; extend test helpers.

**Interfaces:** Consumes Task 1 records. Produces ContextPacker.compose/select, stable opaque citation IDs, private reports and aggregate safe projections; no Runtime dependency needed beyond the existing installed dependency.

Extend test helpers with `two_source_case() -> (spec, snapshot)` (two required root items, independent aliases, revision v1, identical content) and `required_optional_case() -> (spec, snapshot)` (one required and one optional small inline unit).

- [ ] Write the red tests with these exact assertions:

```python
def test_equal_revision_and_content_do_not_merge_independent_sources():
    spec, snapshot = two_source_case()
    candidates = ContextPacker().compose(spec, snapshot)
    assert len(candidates.variants[0]['items']) == 2
    assert len({i['citationId'] for i in candidates.variants[0]['items']}) == 2

def test_one_variant_keeps_required_and_omits_optional():
    spec, snapshot = required_optional_case()
    result = ContextPacker(policy=ContextPackPolicy(max_variants=1)).compose(spec, snapshot)
    assert len(result.variants) == 1
    assert result.reports[0]['requiredCoverageComplete'] is True
    assert result.reports[0]['omittedItemCount'] == 1
```

- [ ] Run `.venv/bin/python -m pytest tests/test_context_pack_selection.py tests/test_context_pack_limits.py -q`; confirm the missing packer failures.
- [ ] Implement label intersection/value-union filtering, explicit ID order > captured ranking > stable-ID fallback, strict cardinalities, exact projections and attribution-preserving deduplication. Reports identify slots by their ordered index.
- [ ] Build mandatory task/evidence/index first. Greedily add whole optional units only when actual encoded envelopes fit; skip oversized optional units with `byteLimit`. Create bounded grouped-removal variants ending at the base; `max_variants=1` yields only the base. Enforce cumulative encoded bytes and cooperative time using an injectable internal clock.
- [ ] Test no callbacks/I/O via forbidden-call sentinels, required overflow, index overflow, optional omission, partial coverage, filter-to-empty required dependency failure, immutable ranking and non-normalized Unicode. Verify safe reports contain no source IDs/paths/content/hashes by default.
- [ ] Run the two files plus Task 1. Commit `feat: compose bounded context pack variants`.

## Task 3: Runtime explicit guard input views

**Files:** Create `input_views.py`; modify `__init__.py`, `rule_types.py`, `rule_hooks.py`, `rules.py`, `guards/{__init__,ids,values,links,strict}.py`, `conversation.py`, `conversation_preparation.py`, `turn_capture.py`, `runtime.py`; create `tests/test_guard_input_views.py` and `tests/test_guard_input_disclosure.py`.

**Interfaces:** Consumes existing Guard/RuleHooks/TurnEvidence. Produces AuthoritativeInputLimits, access-aware registrations, owned private view bindings and computed `inputViewsIdentity` evidence. Advertise guard_input_views_v1 only with execution support.

- [ ] Write `test_shared_guard_refuses_separated_inputs_before_http`, `test_model_guard_cannot_access_authoritative_property`, `test_private_guard_rejects_retry_fix_or_echo_binding`, and `test_private_facts_validate_without_entering_payload`. Assert zero provider/tool calls on admission failures.
- [ ] Run `.venv/bin/python -m pytest tests/test_guard_input_views.py tests/test_guard_input_disclosure.py -q`; observe unsupported-input/access failures.
- [ ] Implement access declarations and identity material only for nondefault access. Keep GuardContext.input_data model-visible, add the separately owned authoritative property, and bind private facts at every guard stage without putting them in message/tool/counter data. Connect authoritative/profile prepare_turn arguments and turn readmission now, so the task's synthetic HTTP tests are independently executable before frozen export exists. Enforce fail-only access at compilation, not after spending.
- [ ] Add explicit private TurnEvidence version 2 for v3 turns, with a closed inputViews extension containing computed profile/digest/access identities; default version-1 evidence stays byte-compatible. Bound combined prepared ownership and evidence before effects. Task 4 extends this same unpublished v3 preparation profile with frozen/selection metadata rather than changing legacy encodings.
- [ ] Test each shipped generic guard in audited model mode. Crucially, args_reference_seen_ids rejects `PRIVATE-731` found only in authoritative input, then accepts an appropriately shaped ID after an actually observed permitted tool result. value_in_tool_output never treats private facts as tool output.
- [ ] Test a private guard returning secret reason/refused/fixed values or throwing a secret-bearing exception: public Result/events/provider retries contain none; only safe rule outcome fields survive. Exercise before_tool and answer stages. Verify accounting capture still records actual provider data, not private facts.
- [ ] Run new files plus existing `tests/test_rule_hooks.py`, `tests/test_rule_admission_golden.py`, `tests/test_generic_guards.py` and legacy witnesses. Commit `feat: separate authoritative guard facts from model input`.

## Task 4: Runtime profiled inputs and public frozen restoration

**Files:** Create `frozen_turns.py`; modify `conversation.py`, `conversation_preparation.py`, `runtime.py`, `turn_capture.py`, `__init__.py`; create `tests/test_frozen_turns.py`, `tests/test_profiled_turns.py`.

**Interfaces:** Consumes Task 3 view bindings. Produces frozen_turn_inputs_v1, FrozenTurnInput, InputVariantSelection, PreparedTurn new properties/export, prepare_turn profile keywords, and restore_turn signature above. Single-variant byte admission is useful independently of Task 5.

- [ ] Write `test_frozen_restore_keeps_exact_current_message`, `test_restore_runs_no_counter_guard_probe_or_source_callback`, `test_private_fact_change_changes_invocation_not_wire_payload`, and `test_default_prepare_identity_stays_v1_or_v2`.
- [ ] Run `.venv/bin/python -m pytest tests/test_frozen_turns.py tests/test_profiled_turns.py -q`; observe missing frozen/profile API failures.
- [ ] Implement closed versioned frozen records, bounded at 8 MiB/64 JSON levels/65536 nodes in addition to field-specific caps. Keep immutable selection material separate from checkpointed work. Save exact current message, selected input bytes, source-history digest/range, profiles, native digest/size and effective descriptors. Credentials/callbacks are excluded.
- [ ] Implement pure restoration against approved artifact/current actual registrations and supplied original history. The host supplies workspace separately; readmit against policy rather than granting roots from a serialized value. No source discovery or counter callbacks during restore.
- [ ] Execute restored turns through normal Runtime readmission: reserve work before native encoding/counting and compare exact saved wire digest/report. Test changed endpoint/tool/guard/profile/counter/workspace, corrupted current message, foreign history, forged variant digest and oversized combined data; no dispatch on failure.
- [ ] Advertise frozen_turn_inputs_v1 only after export/restore and profiled single-variant execution work. Preserve v1/v2 bytes and legacy report schemas; consume Task 3's private TurnEvidence v2 view-binding extension. Test default work reset rejection and explicit fresh_attempt reset with retained initial charges and a new admitted attempt ledger.
- [ ] Run task tests, `tests/test_conversation_contracts.py`, `tests/test_conversation_turns.py`, `tests/test_context_execution.py`, legacy witnesses. Commit `feat: export and restore frozen profiled turns`.

## Task 5: Runtime one-budget history-first variant fitting

**Files:** Create `input_variants.py`; modify `context_assembly.py`, `context_work.py`, `context_execution.py`, `conversation_preparation.py`, `runtime.py`, `__init__.py`; create `tests/test_input_variants.py`, `tests/test_input_variant_work.py`; extend `tests/support/context_counter.py`.

**Interfaces:** Consumes Task 4 APIs. Produces context_input_variants_v1 and prepare_turn_variants, final InputVariantSelection and one final readmission reservation.

- [ ] Write `test_optional_evidence_cannot_evict_more_history`, `test_nonadditive_counter_checks_actual_candidates`, `test_all_variants_share_work_state`, `test_unfunded_optional_trial_keeps_verified_base`, `test_running_counter_timeout_fails_without_dispatch`.
- [ ] Run `.venv/bin/python -m pytest tests/test_input_variants.py tests/test_input_variant_work.py -q`; observe missing variant execution failures.
- [ ] Refactor fitting into internal nonfinalizing candidate checks plus one finalizer. Fit the mandatory base's history suffix first; test richer complete inputs against that same suffix. Never call the current finalizing assembler separately for each candidate. Count construction, encoding and callbacks under one ContextWorkBudget.
- [ ] Reserve headroom for one eventual execution readmission. If another trial is unfunded, return the verified base with selectionWorkLimited; if a running callback exceeds time/work, fail. Final reports must describe the actual selected input, not the baseline or last rejected variant. Do not assume additive or monotone token counts.
- [ ] Parameterize OpenAI-compatible and native Anthropic native payloads; test tools/framing/output reservation, deterministic conservative counters, max checks/bytes/time, interruption reservations and restoration without reselection. Qualified counters are host registrations; synthetic counters remain clearly labeled.
- [ ] Run new tests plus `tests/test_context_assembly.py`, `tests/test_context_execution.py` and legacy witnesses. Commit `feat: fit input variants with one context budget`.

## Task 6: Harness named packs, source bindings and node authoring

**Files:** Create `context_packs/bindings.py`; modify package/root `__init__.py`, `workflow.py`, `factory.py`, `graph_admission.py`, `bundles.py`, `conversation_rules.py`; create `tests/test_context_pack_authoring.py`, `tests/test_context_pack_bindings.py`; extend factory/bundle regression tests.

**Interfaces:** Consumes Tasks 1–2 records and Runtime access descriptors. Produces ContextPackBindings/ContextAuthorizer, trusted YAML contextPacks/agentContextPacks, node contextPack, and preserved host bindings. Model proposals select public aliases only.

- [ ] Write tests for same agent/two nodes/different packs, node override > agent default, explicit task-only narrowing, null/unregistered rejection, conflicting required pins and missing task source. Assert legacy ROOT_KEYS/STEP_KEYS acceptance remains unchanged when new options are absent.
- [ ] Run `.venv/bin/python -m pytest tests/test_context_pack_authoring.py tests/test_context_pack_bindings.py -q` and observe missing authoring failures.
- [ ] Add trusted YAML parsing and native factory host registrations. Only trusted `build()`/static configuration can define specs/defaults; `build_json()` cannot add sources, specs, defaults, callbacks, scope or pins. Proposal schema permits only enumerated public pack aliases on nodes.
- [ ] Bind source kinds input/evidence/artifact; validate referenced files are declared evidence and artifact producers are the node's declared dependencies. Do static graph/binding checks before source resolution/effects. Do not add a hidden retriever/crawler/database connection kind.
- [ ] Extend `_frozen_copy`, `_bundle_material`, WorkflowBundle reconstruction and guard registration-copy helpers. Seal nondefault input_access, pack/source declarations, scope/authorizer descriptors, feedback catalog and validator attestations; default absent values must not alter old identities.
- [ ] Test mutated live nested declarations/callback descriptor drift, clone/reconstruct preservation and describe/proposal_schema privacy (no private paths/revisions/selectors/snapshots). Run factory admission, bundle, rules-admission and legacy tests. Commit `feat: declare context packs per workflow agent and node`.

## Task 7: Harness source normalization and declared-only model projection

**Files:** Create `context_packs/sources.py`, `context_packs/projection.py`; create `tests/test_context_pack_sources.py`, `tests/test_context_pack_projection.py`; add `tests/fixtures/context_packs/markdown/`.

**Interfaces:** Consumes Tasks 2/6 and accepted run state. Produces `resolve_pack(step, agent, bindings) -> ContextPackSpec | None`, `capture_sources(spec, original_arguments, evidence, bindings) -> ContextSnapshot`, and `project_step(step, original_arguments, candidates) -> StepPackProjection`.

StepPackProjection owns full Runtime input roots, pack-index mapping, complete-root digests, original argument digest, private facts and frozen controllerValidationContext. It must distinguish nested envelope hashes from full-root hashes.

- [ ] Write a Markdown-only fixture with requirements/constraints files, a build output, a user task and an unrelated `UNSELECTED-419` value. Test exact chosen body membership, required task, no undeclared fallback, preserved original controller data and byte-exact source provenance.
- [ ] Run `.venv/bin/python -m pytest tests/test_context_pack_sources.py tests/test_context_pack_projection.py -q`; observe unresolved-source/projection failures.
- [ ] Reuse explicit existing workflow file capture; composition reads the frozen evidence ledger only. Normalize strict input pointers, captured files and accepted artifact values into owned root items. Existing freshness checks still run; a missing/stale/partial/unavailable source cannot silently refresh.
- [ ] Build workflow-pack-input-v1 with only task reference, controller safety/header facts and selected pack data. Keep originalArguments and rule_facts complete privately. Required dependencies need an actually selected inline representation; a filtered-to-empty required slot is not coverage. A represented complete empty JSON artifact is valid.
- [ ] Freeze the existing CheckContext shape separately, including all artifacts/bindings visible to controller checks. Test arrays/pointer escapes, malformed UTF-8 capture, wrong producer dependency, changed files after capture, partial collection and same-agent repeated-node independence.
- [ ] Run task tests plus legacy workflow tests. Commit `feat: project only declared workflow context sources`.

## Task 8: Harness authorization, exposure lineage and safe feedback

**Files:** Create `context_packs/authorization.py`, `context_packs/feedback.py`; modify `conversation_errors.py`; create `tests/test_context_pack_authorization.py`, `tests/test_context_pack_feedback.py`.

**Interfaces:** Consumes ContextPackBindings and frozen projections. Produces `authorize_context_use(bindings, use) -> None` (safe ContextPackError on denial), immutable ExposureBindings and SafeFeedback records, and `safe_feedback(kind, check_alias, count, catalog) -> SafeFeedback`.

- [ ] Write tests for all five ContextUse purposes, exact scope/revision/representation membership, non-boolean/exception denial and absence of callback execution during pure construction. Test retainedRead can succeed while invocation/historyReuse is denied.
- [ ] Write `test_validator_secret_never_enters_public_feedback`: for issues `['expected owner SECRET-884']`, public feedback is code validationFailed with count 1, no secret/raw reason; a registered constant catalog message may appear unchanged, with no interpolation.
- [ ] Run `.venv/bin/python -m pytest tests/test_context_pack_authorization.py tests/test_context_pack_feedback.py -q`; observe missing policy failures.
- [ ] Implement conservative source exposure unions for actual inline/index inputs, disclosed reader representations and inherited history. Keep private validation-use bindings separate from model exposure. Authorization failures do not delete evidence or turn internal receipt settlement into a new provider use.
- [ ] Implement safe-feedback-v1 codes validationFailed/schemaViolation/humanResponseInvalid/gateInputInvalid/validatorFault, aggregate counts and static catalog limits. No issue-string classification or dynamic declassification. Private diagnostics remain bounded and never become model-facing feedback/public observer messages.
- [ ] Test Unicode catalog bounds, false-looking truthy returns, source revocation and private diagnostics in check/schema/human/gate faults. Run task tests and legacy public-error tests. Commit `feat: authorize context reuse and sanitize controller feedback`.

## Task 9: Harness closed v3 records and capacity admission

**Files:** Create `context_packs/records.py`, `context_packs/capacity.py`; modify `contracts.py`, `session_contracts.py`, `session_context.py`; create `tests/test_context_pack_records.py`, `tests/test_context_pack_capacity.py`.

**Interfaces:** Consumes frozen Runtime inputs, projections, exposure/feedback records. Produces v3 session/checkpoint extensions and exact reservations; legacy decoders remain version-dispatched.

- [ ] Write red tests for session/receipt v3 equality, workflow checkpoint v3/receipt v2 pairing, wrong-family rejection, null pack extensions on unprofiled purposes, and byte/identity equality of all Task 0 fixtures.
- [ ] Run `.venv/bin/python -m pytest tests/test_context_pack_records.py tests/test_context_pack_capacity.py -q` and confirm unsupported-record failures.
- [ ] Implement `reserve_pack_attempt(...)`, `match_pack_receipt(...)`, `adopt_pack_receipt(...)` as pure reducers in records.py. Frozen data includes current message, source bytes, original args, selected envelope/root mapping, validation context, exposure references, work and proof bindings. Completed receipts bind those values only after execution.
- [ ] Implement `reserve_pack_capacity(...) -> PackReservation` using actual bounded canonical bytes/nodes plus maximum provider/tool result, failure, feedback and metadata headroom. Count duplicated values; references are valid only with retained reconstructable bytes. Do not expand old store caps.
- [ ] Test one-byte/node-short refusal before dispatch, current message/locator/profile tampering, missing retained references, unknown acknowledgement transitions and work monotonicity. Acknowledged retries get a separate admitted epoch; ordinary recovery cannot reset charges.
- [ ] Include the default capacity witness: 16 items, 32 KiB encoded snapshot, 64 KiB private facts, 16 KiB model evidence, two full 24 KiB reader-result reservations, ordinary output/failure room, under 1 MiB receipt/4 MiB state. Larger legal per-field ceilings may correctly fail aggregate admission.
- [ ] Run task tests plus session/contracts/context/recovery legacy suites. Commit `feat: persist bounded context pack invocation records`.

## Task 10: Memory and filesystem storage capabilities/migrations

**Files:** Modify `run_store.py`, `session_store.py`, `memory_session_store.py`, `file_session_store.py`, `file_store.py`; create `tests/test_context_pack_stores.py`, `tests/test_context_pack_file_migration.py`.

**Interfaces:** Consumes Task 9 versioned reducers. Produces dynamic storage capability context_packs_v1 and explicit `initialize(*, context_packs=False)` / `migrate_context_pack_storage()` on owning stores. Existing no-argument initialization stays legacy-compatible.

- [ ] Write tests for fresh opted-in namespaces, reading old namespaces without migration, refusal to write pack records into old storage, and no automatic migration in construction/readiness/first model call.
- [ ] Run `.venv/bin/python -m pytest tests/test_context_pack_stores.py tests/test_context_pack_file_migration.py -q`; observe missing capability/migration failures.
- [ ] Add closed namespace-marker support: new pack-enabled workflow storage contract 2 and session storage contract 3; old workflow contract 1 and session contracts 1/2 remain readable for legacy operation. Existing namespaces require explicit migration, drained writers and preserved old record bytes. Memory requires explicit opt-in readiness but no on-disk migration.
- [ ] Keep CAS/lease/owner/immutable-receipt APIs unchanged apart from optional initialization/capability access. Migration is idempotent, checks expected old marker/schema and never rewrites existing runs or unresolved receipts. Old binaries reject the new marker rather than silently writing mixed state.
- [ ] Exercise process restart, fsync/atomic replacement/unknown acknowledgement, stale leases, symlink/hardlink/path containment and foreign scope. Preserve existing store guarantees; do not introduce a third blob protocol.
- [ ] Run new tests plus `tests/test_file_session_store.py`, `tests/test_session_store.py`, `tests/test_run_store.py` and all storage regression tests. Commit `feat: gate pack records with explicit local storage migration`.

## Task 11: PostgreSQL explicit schema qualification

**Files:** Modify `adapters/postgres/src/prosaic_harness_postgres/{schema,session_schema,store,session_store,cli}.py`; create `adapters/postgres/tests/test_context_pack_migrations.py`, `adapters/postgres/tests/test_context_pack_recovery.py`; extend existing session_documents/workers helpers and adapter README.

**Interfaces:** Consumes Task 10 capability/initialization contract. Produces matching optional PostgresRunStore/PostgresSessionStore behavior; workflow schema/storage 2, conversation schema/storage 3 only through explicit owner migration.

- [ ] Write red tests: runtime role cannot migrate; ordinary readiness does not migrate; migration owner upgrades exact old schema once; old binaries/writers fail readiness on the new marker; old records retain exact bytes/digests.
- [ ] Run `.venv/bin/python -m pytest adapters/postgres/tests/test_context_pack_migrations.py -q` with the existing disposable local-cluster fixture. Confirm failures are the missing feature, not missing DB infrastructure.
- [ ] Implement named owner API `migrate_context_pack_storage()` and CLI command `migrate-context-packs` with explicit `--store workflows|conversations`, using the adapter's existing profile/role mechanism. Drain all writers to the affected shared schema, not merely one namespace. Preserve CAS revisions, lease fencing and runtime-role grants; no transaction spans inference/callback execution.
- [ ] Test two workers racing, lease loss during checkpoint, committed-but-unacknowledged receipt, immutable receipt conflicts, foreign owner, database restart and fresh process restoration. Verify cleanup of exact disposable resources.
- [ ] Run both new files and full `adapters/postgres/tests`; qualify PostgreSQL 16 and 18 on the adapter's existing x86/ARM lanes. Required lanes must fail if the owned database cannot be provisioned. Commit `feat: migrate postgres storage for context pack records`.

## Task 12: Invocation-scoped captured-evidence reader

**Files:** Create `context_packs/reader.py`; modify package/root `__init__.py` exports; create `tests/test_context_pack_reader.py`, `tests/test_context_pack_reader_threads.py`; extend Runtime synthetic tool fixture only if public cross-library tests need it.

**Interfaces:** Consumes Tasks 2/8/9 and normal contextual CustomTool API. Produces ContextPackReader.as_tool/activate and stable read_context_item tool version `context-pack-reader-v1`.

- [ ] Write tests for allowed/narrowed reads, cross-invocation/tenant denial, undiscoverable item denial, and strict no source I/O. Run `.venv/bin/python -m pytest tests/test_context_pack_reader.py tests/test_context_pack_reader_threads.py -q`; confirm missing reader failures.
- [ ] Register once with with_context=True and fixed argument/result bounds. Activate only the selected allowlist under actual InvocationScope after pending persistence and before dispatch. Use a reader-instance locked map, not a process-global pack or implicit worker-thread contextvar inheritance.
- [ ] Implement UTF-8 byte-range paging with exact next offset under 16 KiB body/24 KiB encoded result, including escape/provenance overhead. JSON remains whole at an admitted pointer or returns safe contextReadLimit. Never widen an admitted excerpt/pointer to a parent.
- [ ] Verify current deferredRead authorization and deadline/cancellation on each call. Remove active entries on normal completion/failure/cancellation; reconstruct from saved pending bytes on an explicit execution path, not ambient files. Missing binding returns a safe unavailable result without fallback.
- [ ] Run two real worker threads with distinct packs and same record IDs; prove no crossover after timeout/rebinding/cleanup. Exercise normal Runtime guards/tool budgets and actual post-guard outcomes, not direct handler calls only. Commit `feat: read captured context through scoped tools`.

## Task 13: Workflow execution and guarded v2 proofs

**Files:** Modify `engine.py`, `workflow_rules.py`, `conversation_rules.py`, `observations.py`, `interaction.py`; create `tests/test_context_pack_workflow.py`, `tests/test_context_pack_workflow_recovery.py`, `tests/test_context_pack_workflow_disclosure.py`; add runnable Markdown workflow fixtures.

**Interfaces:** Consumes Tasks 5–12. Produces end-to-end named per-node packs in static/native workflows, complete private validation and workflow_rules_v2. Primary user-facing milestone.

- [ ] Write a failing two-node Markdown workflow test: implementer default pack contains task/requirements/constraints; reviewer override contains task/requirements/candidate; both omit an unrelated business sentinel. Assert only declared evidence reaches real captured native payloads, while controllers/authoritative guards retain complete original facts.
- [ ] Run `.venv/bin/python -m pytest tests/test_context_pack_workflow.py tests/test_context_pack_workflow_recovery.py tests/test_context_pack_workflow_disclosure.py -q`; observe missing workflow integration failures.
- [ ] Integrate in the existing drive/adopt paths: dependency freshness -> source normalization -> original/validation snapshot -> pure composition/projection -> current authorization -> Runtime preparation -> exact capacity reservation -> pending save -> reader activation/readmission -> dispatch -> completed receipt -> controller validation/adoption. Source capture/projection may be computed before use authorization only within trusted host memory; no provider or external callback receives unauthorized data.
- [ ] Switch only pack-enabled agent nodes to prepare/turn. Reject acquisition, require_reads, args interpolation and existing unsupported guarded terminal combinations before effects. Pack-free node payloads/rules retain old semantics; opted-in runs still use safe feedback/storage wrappers for all nodes.
- [ ] Implement workflow_rules_v2 with full original-facts digest, both profile/digest pairs, inputViewsIdentity, selected pack identity, Runtime context identity and rule receipt. Recompute expected views from owned controller data and compare against Runtime private evidence. Reject v1 substitution and mixed-source/projection proofs.
- [ ] Route agent/check/schema/gate/human validator outcomes and events through safe-feedback-v1 at their source. Require repeatable_validators for every validator used in the opted-in run. Reconstruct frozen CheckContext on receipt adoption; do not promise exactly-once validators or rerun Runtime guards.
- [ ] Fault-inject before/after pending save, work reservation, dispatch marker, provider return, receipt save and adoption. Verify zero repeated provider/tool/guard work when adopting a saved receipt, correct unknown-effect state otherwise, scope checks on retries and no budget reset on recovery.
- [ ] Run new files plus `tests/test_workflow_rules_execution.py`, `tests/test_workflow_rules_recovery.py`, existing human/gate/terminal/factory tests and legacy witnesses. Commit `feat: execute declared workflow context packs durably`.

## Task 14: Conversation packs and retained-history authorization

**Files:** Modify `conversation_bindings.py`, `conversation.py`, `conversation_workflow.py`, `session_contracts.py`, `session_context.py`; create `tests/test_context_pack_conversation.py`, `tests/test_context_pack_history.py`, `tests/test_context_pack_conversation_recovery.py`.

**Interfaces:** Consumes Tasks 5/8–12 and v3 records. Produces the public host-only send argument, context-pack-snapshot-v1 private facts, exposure sidecars and retainedRead authorization, without requiring a graph.

- [ ] Write `test_send_accepts_host_candidates_without_workflow`, `test_same_message_id_changed_pack_conflicts`, `test_exact_replay_never_recaptures_or_dispatches`, and `test_revoked_reader_history_blocks_send_without_new_pack`.
- [ ] Run `.venv/bin/python -m pytest tests/test_context_pack_conversation.py tests/test_context_pack_history.py tests/test_context_pack_conversation_recovery.py -q`; observe missing integration failures.
- [ ] Admit ContextPackCandidates against allowed immutable bindings/scope. Construct context-pack-input-v1; guarded turns derive their complete private snapshot facts under the separately sealed profile. Never accept arbitrary HTTP input_data/authoritative roles or allow a pack to overwrite workflow interaction fields.
- [ ] Persist per-turn exposureBindings, including conservative inherited history unions and actual disclosed reader representations. Check historyReuse before fitting even without a new pack; separately check retainedRead for replies/history/status/private projections. A denied view does not prevent internal adoption of already completed effects.
- [ ] Reuse Runtime public export/restore; no candidate recomposition or counters in restoration. Reserve/checkpoint work before execution callbacks. Keep current message explicit and exact. Earlier inline envelopes remain private receipt data; portable history retains actual user/assistant/tool groups unchanged.
- [ ] Test memory/file/PostgreSQL reopen, read permitted/use denied, cancellation, revoked source after tool outcome, failed-turn history, quota exhaustion, explicit retry allowance, original message/pack binding and mixed ordinary/interpreter v3 receipt wrappers. Reject packs during attached-workflow interpretation and preserve confirmation identity.
- [ ] Run new files, existing conversation/context/rules/recovery suites and legacy witnesses. Commit `feat: attach context packs to durable conversations`.

## Task 15: Installed-wheel and cross-repository qualification

**Files:** Create Runtime `scripts/context_pack_wheel_smoke.py`, Harness `scripts/context_pack_smoke.py`; extend both repositories' existing conversation smokes and release/test workflows. Add Harness `tests/test_context_pack_installed.py` and both distributions' package/export tests.

**Interfaces:** Consumes completed public APIs, never source-path/private imports. Produces immutable candidate artifact receipts, compatibility matrix results and the spec's default-capacity witness.

- [ ] Write installed tests that assert every prosaic module originates in the fresh wheel environment, then exercise both new Runtime APIs and a two-node Harness Markdown workflow. Use a temporary working directory outside both source trees, `python -I`, and no PYTHONPATH/editable dependencies.
- [ ] Build each source with `.venv/bin/python -m build`. Create a clean qualification environment, install exact candidate wheel paths plus verified Core/recorder witnesses and optional adapter, then `python -m pip check`. Record artifact SHA-256, source SHA, platform, dependency versions and command output in ignored qualification receipts.
- [ ] Run Runtime installed gates from a temporary CWD outside the source trees using the qualification environment's absolute Python path and absolute script paths: `"$PACK_QUAL_PY" -I "$RUNTIME_TREE/scripts/wheel_smoke.py"`, and likewise native_wheel_smoke.py, production_wheel_smoke.py, conversation_wheel_smoke.py, terminal_completion_smoke.py, rule_admission_wheel_smoke.py and context_pack_wheel_smoke.py. Run Harness workflow_factory_smoke.py, conversation_smoke.py, conversation_smoke.py --context-assembly, terminal_completion_smoke.py and context_pack_smoke.py using `$HARNESS_TREE/scripts/` absolute paths under that same environment. PACK_QUAL_PY is the task-specific absolute path to the clean environment's Python.
- [ ] The new Harness smoke covers tool-free/file-backed packs, structured-record outputs, guarded smaller model input with full private validation, two reader calls, safe feedback, restart, and legacy/new records. New smoke CLI flags are `--postgres-dsn-env NAME` for owned PostgreSQL fixtures and `--require-postgres` to forbid a skip in required DB jobs. No secret values appear in shell arguments or reports.
- [ ] Test old Harness against new Runtime for all pack-free APIs, new Harness against old Runtime in legacy mode, and explicit capability refusal for requested packs on old Runtime. New package metadata may enforce a newer Runtime floor; test old Runtime behavior in an intentionally controlled no-deps compatibility harness and do not represent that combination as supported installation.
- [ ] Qualify all current Python 3.11/3.12/3.13 platform cells and PostgreSQL 16/18 x86/ARM cells; preserve dependency-floor and original-recorder gates. Reuse current release_artifacts receipts; do not replace a failing required gate with a skip or only a source test.
- [ ] Commit `test: qualify installed context pack SDKs and compatibility` only after the observed failures have become passing installed checks.

## Task 16: Consumer adoption, documentation and release preparation

**Files:** Harness `docs/context-packs.md` (new), `docs/conversations.md`, README, examples with two Markdown evidence files/workflow (new); Runtime `docs/context-packs.md` (new), conversations/rules-admission docs; both pyproject/__init__/CHANGELOG/CI pins; Harness adapter metadata/README/CLI docs. Integration Lab consumer files are a small separately isolated acceptance change, described below.

**Interfaces:** Consumes qualified candidate wheels. Produces documented public use, exact compatible artifact set and a consumer acceptance report. Uploading/releasing remains a separate final action.

- [ ] Write/run documentation examples through installed_smoke fixtures: local Markdown per-node declarations with no DB, dynamic accepted-output sources, task-only override, explicit file limits, private guard views, qualified-counter opt-in and byte-only status, deliberate history authorization and storage migration.
- [ ] Show both Runtime and Harness APIs without private imports. Document fail-only private guards, safe static feedback, repeatable validators, no automatic memory/retrieval, explicit retry risk, and current inference-vs-view authorization. Explain how to move file producers to application records without changing the pack's source aliases.
- [ ] In an isolated Integration Lab branch, add a public-wheel context-pack lane using existing candidate manifests/owned-stack setup. New files: `src/prosaic_integration_lab/context_packs.py` (consumer scenarios), `lab_runner/context_packs.py` (qualification driver), `tests/unit/test_context_pack_scenarios.py`, `tests/acceptance/test_context_packs.py`; extend `lab_runner/__main__.py`, `lab_runner/stack.py`, candidate capability admission and existing conversation-lane setup. Route the new mode through all relevant conversation provisioning, candidate-manifest, acceptance-selection and cleanup branches, not just argparse. Use `python -m lab_runner test --mode context-packs --candidate --candidate-manifest /absolute/path/to/manifest.json` as the new documented command. It must fail rather than silently skip missing requested capabilities/DB infrastructure.
- [ ] Consumer cases are (1) Markdown document review, (2) service impact via accepted structured lookup outputs, including missing/partial/contradictory evidence. Use only installed public APIs. Record known expected context membership, zero undeclared disclosures, citations, tool counts, restart and capacity. This lane must not copy pack/recovery engines into the lab.
- [ ] Plan separate optional real-model evaluation of baseline/static/reader packs on a pinned held-out set: correctness, required-fact recall, unsupported claims, stale/conflicting errors, citations, duplicate reads, total input tokens, latency and full cost. Do not run paid models until explicitly enabled, and do not infer quality gains from synthetic correctness.
- [ ] Select unallocated release versions only after rechecking upstream at execution time. Provisional development versions are Runtime 0.9.18.dev0, Harness 0.9.13.dev0 and Harness PostgreSQL 0.4.2.dev0; replace them coherently if already allocated. Final compatible floors must name the first pack-capable Runtime/Harness and retain `<0.10` / current family contracts where compatible. Do not republish Core or the original recorder unnecessarily.
- [ ] Rebuild final-version artifacts and rerun exact installed/platform/PostgreSQL/dependency-floor gates after metadata changes. Dev-wheel evidence is not final-byte qualification. Prepare changelogs, migration/rollback instructions and artifact hash manifest; do not push, tag or upload as a side effect of planning or a local smoke.
- [ ] Commit `docs: document and prepare the context pack release train` with linked actual verification evidence. Keep public promotion as the final separately authorized action.

## Backward-compatibility and migration matrix

| Surface | Must remain unchanged | Opt-in change / owning tasks |
| --- | --- | --- |
| Core Markdown, resources, on-disk prose | No new kind, execution or parser requirement | None |
| Runtime.run()/default prepare_turn | Payload, roles, default metadata, v1/v2 identity and compaction behavior | V3 only for explicit new profile/variants/private facts; 3–5 |
| Guards and rules | Default shared registration material and legacy fingerprints | Nondefault access sealed and audited; 3, 6 |
| ContextSelection/ContextAssemblyReport v1 | Closed fields and counting kinds | Separate InputVariantSelection; notCounted lives only in pack reports; 4–5 |
| Pack-free Workflow/Factory/Bundle | Existing declarations, argument/proof bytes, fingerprints | Named context fields/new bindings only when enabled; 6–7, 13 |
| Pack-enabled run's pack-free nodes | Existing node payload/tool behavior | Safe feedback and new run/receipt wrapper apply to the opted-in run; 8–9, 13 |
| Conversation records | Session/receipt v1/v2 load byte-compatibly | Session and all its receipt wrappers v3 when opted in; inner interpreter/pack-free turn encodings may stay legacy; 9, 14 |
| Workflow records | Checkpoint v2, invocation receipt v1 and proof v1 continue loading | Checkpoint v3, receipt v2, guarded pack proof v2; 9, 13 |
| Local storage | Old initialization/readiness never auto-upgrades | Explicit initialize opt-in/migration; workflow contract 2, session contract 3; 10 |
| PostgreSQL | Owner/CAS/fencing/grants; original rows/receipts retained | Explicit schema-owner migrations; no runtime-role DDL; 11 |
| Recorder/billing | Existing actual provider usage and original recorder schema | No private guard data in billing/provider payloads; 3, 15 |

Before migration: back up owned data, stop/drain every writer for the affected schema/namespace, resolve operational prerequisites, run the migration-owner API/CLI, verify readiness under runtime role, then enable new bindings. Rollback means disabling new admission and continuing with compatible new readers to resolve existing v3 operations; do not point old writers at the upgraded namespace or downgrade version markers over v3 data. Use a separately admitted fresh legacy namespace only when a genuine old-writer deployment is required; never delete unresolved evidence to make that possible.

## Spec/review coverage map

| Requirement or finding | Owning tasks |
| --- | --- |
| Spec acceptance 1–3: pure bounded contracts/projection | 1–2, 6–7 |
| Acceptance 4, CP-05/09: exact fitting and shared work | 4–5 |
| Acceptance 5, CP-07/12: compatibility, versions, capabilities | 0, 3–6, 9–11, 15 |
| Acceptance 6: replay and idempotency | 9, 14 |
| Acceptance 7, CP-03/11: authoritative validation/recovery | 3, 7–9, 13 |
| Acceptance 8, CP-10: reader isolation/encoded limits | 8, 12 |
| Acceptance 9–10: fault recovery/quotas/migrations | 9–11, 13–15 |
| Acceptance 11–14: separate guard facts/proofs/disclosure | 3–5, 9, 13 |
| Acceptance 15, CP-01/14: historical use and retained reads | 8, 14 |
| Acceptance 16, CP-02: validator/event feedback secrecy | 8, 13 |
| Acceptance 17, CP-04/08: independent provenance/stable ranks | 1–2, 7 |
| Acceptance 18, CP-06/13/15: frozen message/restoration/hash mapping | 2, 4–5, 7, 12–14 |
| Acceptance 19: old/new record pairings | 9–11, 15 |
| Acceptance 20–22: declared-only per-node/file/record authoring | 6–7, 13, 15–16 |
| Default-capacity witness and installed adoption | 9, 15–16 |

## Completion and handoff gates

- [ ] Self-review the entire plan against the spec and CP-01–CP-15: every requirement has a task, test owner, exact interface and observable success criterion.
- [ ] At each code task, watch the targeted behavior fail before implementation, make it pass, run adjacent legacy witnesses, review the diff, and commit only that task's changes.
- [ ] Before integration, run each repository's complete required source suite. Build and test installed wheels, including pure public API ownership and the cross-version matrix. No source-only green result substitutes for a required installed/storage gate.
- [ ] Run the full existing release platform matrix and PostgreSQL cells; record exact candidate/final hashes and no-skip required results. No historical evidence is rewritten.
- [ ] Perform a whole-change review of authorization, disclosure, both view/proof bindings, storage/recovery and public authoring. Resolve actual findings before calling implementation complete.
- [ ] Hand over the code, tests, docs, migration instructions, compatibility report and immutable qualification manifest. Report unresolved infrastructure/live-model work explicitly; do not mark it passed from this plan.

This plan was self-reviewed at authoring time; execution checkboxes remain unchecked. The recommended execution approach is native sequential implementation with an independent whole-change review, because the Runtime/Harness interfaces and record migrations are tightly coupled. Subagent-per-task execution remains available if the user prefers the additional review/context cost.
