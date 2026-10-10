# Harness Production Service Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose reliable optional observations, safe native workflow discovery and human interaction, frozen bundle reconstruction, and Runtime budget/effect integration through public installed Harness APIs.

**Architecture:** Preserve the admitted workflow as the execution authority and keep service projections, frozen host bundles and optional observations in focused modules. Harness remains the sole writer of run state; Runtime owns provider/tool dispatch and business effect journals remain host bindings. Additive metadata is omitted from execution identity when disabled, preserving existing checkpoints and receipts.

**Tech Stack:** Python 3.11+, dataclasses, bounded plain JSON, jsonschema Draft 2020-12, Prosaic Runtime public telemetry/operation APIs, FileRunStore and the separate PostgreSQL RunStore adapter, pytest.

**Spec:** [Approved ecosystem production design](../../../../prosaic/docs/superpowers/specs/2026-10-10-ecosystem-production-design.md). Read Milestones 1, 2 and 4, the Lab consumer requirements in Milestone 3, and the delivery constraints before executing this plan. The human approved autonomous parallel execution and explicitly waived another design handoff; this plan does not require another approval pause.

## Global Constraints

- Python imports, CLI commands, repository names, canonical serialized camelCase contracts, and existing manifest/checkpoint/receipt formats remain compatible.
- Preserve checkpoint v2, receipt v1 and reported/unknown accounting.
- Keep existing `on_event=` propagating semantics for compatibility with callers that deliberately use a critical hook.
- Observer delivery is best effort, not a durable outbox or an authorization signal. Ordinary observer exceptions are isolated; process-control exceptions propagate.
- Models cannot supply or override operation keys, authorization identity or journal bindings. Native execution must still pass admission at construction, run, resume, status and every new dispatch.
- Disabled new fields are omitted from legacy descriptors and identity inputs to preserve old fingerprints. Enabled caps participate in native policy identity; disabled fields are omitted from existing identity payloads.
- Omitting `model_tier` continues to select the authorized host default; explicit tiers must be allowed and configured.
- The application remains responsible for authentication, tenant entitlements, business authorization, HTTP idempotency, deployment configuration, and operator decisions. Harness does not acquire a tenant/proposal registry, transport service or business journal implementation.
- No native filesystem resource aliases, client `base_dir`, executable, physical paths, endpoints or callback hydration are introduced.
- Harness `max_calls` continues to mean workflow invocations and is never reinterpreted as provider requests.
- `WorkflowPolicy.max_provider_requests_per_invocation` and `max_tool_calls_per_invocation` are trusted optional nonnegative integers or `None`, configured only by the application.
- Journal namespace and opaque journal identity are sealed when enabled; no DSN, storage path, backend object identity or credentials are serialized. Do not reconcile an uncertain effect from interrupted-request consent.
- Native Linux AMD64/ARM64 sandbox cells and PostgreSQL 16/18 lanes remain required. Do not weaken existing sandbox/skip guards or crash/standby qualification.
- The root release owner handles package naming, metadata, dependency ranges, CI/publication workflows, archive audits and `b3-prosaic-harness` 0.7.0 / adapter 0.2.0 releases. This plan changes service behavior and tests, not release metadata.
- Use `apply_patch`; preserve unrelated user changes and historical evidence. Tests use synthetic results or owned loopback fixtures; no live provider calls or shared deployment mutations.

## Review Focus

1. **H1:** An observer raises during a pause/save fallback; the committed state and revision remain authoritative, and no additional model call occurs.
2. **H2:** A policy permits an unbound alias or an error includes hostile names; discovery must not advertise unavailable/private bindings, and diagnostics expose only bounded logical locations.
3. **H3:** Cyclic/oversized inputs and invalid/stale human responses arrive before a service reservation or decision; preparation has no effects and rejected responses preserve state/revision.
4. **H4:** A near-limit Unicode proposal or same-version altered host material is reconstructed on a fresh worker; canonical original bytes remain admissible and all immutable identities must match.
5. **H5:** A journal domain changes, usage becomes unknown, or a worker crashes after receipt commit; binding drift rejects, budgets retain incurred usage, and adoption never redispatches or resolves uncertain effects.

---

## Ownership, files and dependency order

| Task | Responsibility | Focused production files | Depends on |
| --- | --- | --- | --- |
| H1 | Optional observation delivery after durable commits | `observations.py`, `engine.py` | Runtime observer contract |
| H2 | Public catalogue/schema and admission locations | `discovery.py`, `factory.py`, `graph_admission.py`, `errors.py` | Existing factory/schema admission |
| H3 | Pure input preparation, pending interaction and response errors | `interaction.py`, `workflow.py`, `engine.py`, `errors.py` | H2 location helper |
| H4 | Immutable bundle/reference and canonical envelope reconstruction | `bundles.py`, `factory.py` | H2 factory snapshots; additive H5 identity included when available |
| H5 | Remaining budgets, trusted effect scope and recovery verification | `factory.py`, `engine.py` | Runtime invocation budgets/tool journal; H1 and H4 |

All tasks update `src/prosaic_harness/__init__.py` when exporting their public APIs and `docs/workflow-factory.md` for their own user-facing contracts. Schedule factory/engine edits sequentially or coordinate exact ownership before dispatching parallel workers. Do not move the existing engine or rewrite released admission algorithms merely to split modules.

Runtime supplies these public interfaces; its separate plan implements them:

```python
from prosaic_runtime import InvocationScope
from prosaic_runtime.telemetry import ObserverEmitter
from prosaic_runtime import tool_journal_descriptor

InvocationScope(invocation_id: str, run_id: str | None = None,
                step_id: str | None = None, operation_namespace: str | None = None)
ObserverEmitter(observer, *, source: str, scope: InvocationScope, labels=None)
ObserverEmitter.emit(event: str, **fields) -> None
tool_journal_descriptor(journal) -> dict  # None -> {}; static metadata inspection
ProsaicRuntime.run(..., observer=None, operation_context=None, tool_journal=None)
```

Capabilities are `observer_v1`, `invocation_budgets_v1`, `tool_context_v1` and `tool_journal_v1`. A journal declares plain scalar `identity` and `contract_version='tool-journal-v1'`; the descriptor helper uses static inspection and rejects executable properties/dynamic descriptors without calling them. `CustomTool.version` covers handler, authorizer and resolver semantics. Enabled tool descriptors add `with_context=True` / `journaled=True`; disabled keys remain absent. Confirm these names against the Runtime implementation before running H1/H5; dependency unavailability is not a reason to silently disable configured controls.

Use the repository virtual environment. Focused source integration during parallel SDK development can use:

```bash
PYTHONPATH=../prosaic/src:../prosaic-runtime/src:src .venv/bin/python -m pytest tests/test_workflow_factory.py -q
```

Final full verification uses installed candidate dependencies and `.venv/bin/python -m pytest`; root owns exact-wheel qualification. Baseline supplied by the coordinator: 337 Harness tests passed before these tasks. Record actual new counts rather than assuming that baseline remains the final count.

## Shared synthetic test conventions

New tests may reuse the real host fixture functions `factory`, `graph`, `agent`, `config`, `tools` from `tests/test_workflow_factory.py`, `bound` from `tests/test_native_execution.py`, and `harness` from `tests/test_store_engine.py`. They already create canonical artifacts and a standard `ProsaicRuntime` with a patched `run` boundary. Copy the needed imports and the small `raising_observer`/`envelope` definitions below into the new test module that uses them. Do not substitute an opaque runtime for native tests or bypass admission to set up a test.

```python
import json
import pytest
from prosaic_harness import Harness, WorkflowAdmissionError
from test_workflow_factory import factory, graph
from test_native_execution import bound

def raising_observer(record):
    raise RuntimeError('PRIVATE observer failure')

def envelope():
    return json.dumps({'definition': graph()}, ensure_ascii=False)
```

The exact standard runtime may be function-patched in unit tests. Tests of budget enforcement itself use a Harness-owned synthetic loopback response sequence through the real standard Runtime, not a stub pretending to enforce Runtime policy or importing tests from a sibling checkout. Extend `tests/test_transport.py`'s existing endpoint fixture for finite response sequences if needed. PostgreSQL tests use the existing explicitly owned fixtures and `--require-postgres`.

### Task H1: Optional observer delivery at committed boundaries

**Files:**
- Create: `src/prosaic_harness/observations.py` — allowlisted Harness projection and delivery adapter around Runtime's `ObserverEmitter`.
- Modify: `src/prosaic_harness/engine.py` — `Harness.__init__`, `_save`, `run`, `resume`, and Runtime dispatch options.
- Test: `tests/test_observers.py`; extend `tests/test_native_execution.py` state-limit coverage.
- Docs: `docs/workflow-factory.md` and `docs/design.md` event-hook distinction.

**Interfaces:**
- Consumes: `ObserverEmitter(observer, source='harness', scope=InvocationScope(...), labels=None).emit(event, **fields)` and Runtime `observer_v1`.
- Produces: `Harness(..., observer=None)`; existing `on_event` remains unchanged. Internal `CommittedObserver(observer)` owns per-Harness sequence and `emit_committed(state, revision, *, recovery=False) -> None`.
- Harness event names: `run_started`, `transition_committed`, `waiting_committed`, `recovery_committed`, `blocked_committed`, `run_completed`. Runtime owns its terminal observer record and invokes the same optional observer directly; do not forward raw critical events into telemetry.

- [ ] **Step 1: Write the observer-isolation regression.** Add constructor support to the existing `bound` test helper as a test-only `harness_options=None` argument, merged into `Harness(...)`, then write:

```python
def test_waiting_commit_survives_observer_failure(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch,
                     harness_options={'observer': raising_observer})
    assert h.run({'private_input': 'PRIVATE'})['status'] == 'waiting'
    before = h.status()
    assert h.resume(choice='accept', expected_revision=before.revision)['status'] == 'completed'
    assert len(calls) == 1
```

- [ ] **Step 2: Run the regression RED.** Run `.venv/bin/python -m pytest tests/test_observers.py::test_waiting_commit_survives_observer_failure -q`; expect constructor rejection of `observer`, not a missing fixture or accidental native admission failure.
- [ ] **Step 3: Implement the delivery adapter and post-save hook.** Project only closed outcome/reason enums, validated opaque correlation, finite counts/durations and committed revision. Create/refresh the emitter with the verified run identity; no private inputs, prompts, stdout, history payloads, exception messages, runtime URLs, filesystem paths or unchecked tool names enter records. Call the adapter only after `store.create_run/save_run` succeeds and after `_save` has applied any `state_limit` fallback:

```python
def emit_committed(self, state, revision, *, recovery=False):
    kind = ('blocked_committed' if state['status'] == 'blocked' else
            'waiting_committed' if state['status'] == 'waiting' else
            'run_completed' if state['status'] in {'completed', 'rejected'} else
            'recovery_committed' if recovery else 'transition_committed')
    self.emitter.emit(kind, outcome=state['status'], revision=revision,
                      calls=state['calls'])
```

The actual Runtime scalar allowlist must accept the approved fields; map unsupported checkpoint reasons to its closed unknown marker. Create one opaque Harness observation scope for each public run/resume execution, after admission, retaining one sequence through that execution; Runtime uses the persisted attempt ID for its own invocation scope. Observer record mutation must not mutate state. Preserve `_event` and Runtime `record` as the critical evidence paths. Passing `observer` to Runtime is conditional on a configured observer and supported capability; configured native observation cannot quietly disappear through an incompatible runtime.
- [ ] **Step 4: Pin failure and privacy boundaries.** Add tests for `KeyboardInterrupt` propagation, critical `on_event` still propagating, observer failure on committed recovery, separate emitters/sequences for concurrent Harness instances, and mutation of a received record. Reuse the existing state-limit receipt fixture: collect observations, force `_save` to commit `blocked/state_limit`, then assert the last observation reports the committed blocked state/revision rather than waiting/completed. Have an observer call `h.status()` and assert its revision equals the record revision. A failed store save must emit no committed observation.
- [ ] **Step 5: Run GREEN and compatibility checks.** Run `.venv/bin/python -m pytest tests/test_observers.py tests/test_native_execution.py tests/test_store_engine.py -q`. Document fast cooperative callbacks, best-effort delivery, critical-hook separation and observation after durable state. Commit only H1 files with `git commit -m "feat: isolate optional Harness observations"` after `git diff --check` and focused tests pass.

### Task H2: Policy-projected catalogue, proposal schema and safe locations

**Files:**
- Create: `src/prosaic_harness/discovery.py` — bounded pure public projection and structural proposal schema.
- Modify: `src/prosaic_harness/factory.py` — `WorkflowCatalog`, factory description/schema delegation and known admission locations.
- Modify: `src/prosaic_harness/graph_admission.py`, `src/prosaic_harness/errors.py` — trusted logical location propagation without changing legacy error classification.
- Test: `tests/test_workflow_discovery.py`, `tests/test_workflow_factory.py`, `tests/test_legacy_loader_admission.py`.
- Docs: `docs/workflow-factory.md`.

**Interfaces:**
- Produces: `WorkflowCatalog(*, agents=None, schemas=None, public_metadata=None)`; `WorkflowFactory.describe(*, include_schemas=False, maximum_bytes=262_144) -> dict`; `WorkflowFactory.proposal_schema(*, maximum_bytes=262_144) -> dict`.
- Public metadata is a bounded plain JSON mapping with optional categories `agents`, `schemas`, `tools`, `validators`, each mapping known logical aliases to `{description: str}`. Descriptions are explicitly public, at most 4096 UTF-8 bytes each; reject unknown category/alias/field, nonstrings, cycles and aggregate host-bound overflow. It never changes workflow/bundle execution identity.
- Describe returns new owned camelCase JSON: `version=1`, `agents`, `schemas`, `tools`, `validators`, `stepKinds`, `allowInlineAgents`, `allowAgentComposition`, `modelTiers`, `defaultModelTierAllowed=True`, `limits`. Each category is an alias-keyed map with public description when present and safe semantic version/capability metadata when relevant. Schema bodies appear only with `include_schemas=True`; artifact bodies/private frontmatter and physical bindings never appear.
- Existing `WorkflowAdmissionError.code/location` remain the public error contract. Internal `logical_location(*parts) -> str` emits bounded trusted field names, validated aliases and numeric indices; unknown/client-derived property keys become `*`, never parser text. Add `*` to the bounded location sanitizer's permitted structural punctuation so this marker survives formatting.

- [ ] **Step 1: Add a real missing-API/privacy RED test.**

```python
def test_describe_intersects_policy_with_bound_assets_and_keeps_prose_private():
    build = factory()  # policy allows reviewer, but only finder is bound
    manifest = build.describe()
    assert set(manifest['agents']) == {'finder'}
    assert manifest['defaultModelTierAllowed'] is True
    assert 'Return structured JSON.' not in json.dumps(manifest)
    assert 'http://localhost:9' not in json.dumps(manifest)
    assert 'reviewer' not in manifest['agents']
    manifest['agents'].clear()
    assert set(build.describe()['agents']) == {'finder'}
```

- [ ] **Step 2: Run RED.** Run `.venv/bin/python -m pytest tests/test_workflow_discovery.py::test_describe_intersects_policy_with_bound_assets_and_keeps_prose_private -q`; expect missing `describe`.
- [ ] **Step 3: Implement pure projection and explicit schema shapes.** Intersect agent/schema aliases with catalogue+policy, validators with actual registrations+policy, tools with registered native tools+policy+Runtime allowed tools, and explicit tiers with policy+configured routes. No artifact execution, CLI discovery, callback/version property evaluation or endpoint probing. Use a bounded snapshot of the final projection; reject oversized semantic documents rather than truncate aliases/schemas. Build a Draft 2020-12 structural schema with `additionalProperties=False` on the envelope/root/each step and `oneOf` branches by `kind`:

```python
envelope_schema = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    '$id': 'urn:prosaic-harness:proposal:v1',
    'type': 'object', 'required': ['definition'], 'additionalProperties': False,
    'properties': {'definition': definition_schema,
                   'inline_agents': (inline_agents_schema if policy.allow_inline_agents
                                     else {'type': 'object', 'maxProperties': 0})},
}
```

Define `definition_schema` in this module with allowed keys `version` (`const:1`), optional `name`, `start`, optional `limits`, and nonempty `steps` (`maxProperties=policy.max_steps`, validated alias keys). Limits are only `max_calls`, `max_visits`, `timeout_s`, `max_tokens`, `max_run_s`, positive integers with effective host maxima. Every step branch requires `kind`; use `STEP_KEYS` as the authoritative closed-key inventory, excluding native-forbidden `acquisition`, `read_roots`, `require_reads`; additional branch-required fields match the shared graph validator: agent `agent/schema/next`; gate `from/field/equals/pass/fail`; check `from/validators/pass/fail`; pause `question/choices`; finish optional completed/rejected outcome. Tool/validator/schema refs are enums of effective allowed bindings. Agent refs permit admitted catalogue aliases and, only when inline is enabled, valid local inline aliases. Add inline closed `{type?, frontmatter, body}` definitions matching actual factory admission, never endpoint/path/config fields. An explicit empty `inline_agents` object remains structurally valid when inline instructions are denied, matching existing admission. Preserve legitimate empty JSON property keys in gate `field`. Structural schema cannot prove transition targets, provenance freshness, alias use or admission; retain mandatory `build_json` validation.
- [ ] **Step 4: Add safe location witnesses.** Wrap known native reference/policy/schema checks at their actual field sites and preserve their existing codes:

```python
def test_unknown_agent_error_identifies_safe_logical_field():
    proposal = graph()
    proposal['steps']['find']['agent'] = 'missing'
    with pytest.raises(WorkflowAdmissionError) as caught:
        factory().build(proposal)
    assert caught.value.code == 'unknown_reference'
    assert caught.value.location == '$.definition.steps.find.agent'
```

Add negative schema/property and forbidden resource cases. Hostile keys/exception messages must not appear in `str(error)` or locations; locations remain bounded at 256 characters. Shared graph diagnostics may carry safe locations internally, but preserve loader diagnostic prefixes and existing single-failure behavior. Test description metadata opt-in and identity neutrality, allowlist-only-but-unbound tools/validators/tiers, boolean schema bodies, maximum_bytes overflow, and zero callback/probe invocations.
- [ ] **Step 5: Run schema parity GREEN.** Use `Draft202012Validator.check_schema(build.proposal_schema())` and validate accepted fixture envelopes, including all five step kinds, omitted versus explicitly empty inline mapping, authorized composition and authorized inline variants. Rejected physical-binding/envelope/closed-step keys must fail structurally. Include a structurally valid graph with unknown transition that schema accepts and factory rejects to document authority boundaries. Run `.venv/bin/python -m pytest tests/test_workflow_discovery.py tests/test_workflow_factory.py tests/test_legacy_loader_admission.py -q`. Document tenant-projected factory construction and host-only schema disclosure. Commit H2 files with `git commit -m "feat: expose safe workflow catalogue and proposal schema"` after diff check.

### Task H3: Pure input preparation and bounded human interaction

**Files:**
- Create: `src/prosaic_harness/interaction.py` — immutable projection record and bounded record encoding.
- Modify: `src/prosaic_harness/workflow.py` — additive native `prepare_inputs` method.
- Modify: `src/prosaic_harness/engine.py` — one-snapshot interaction and safe human response errors.
- Modify: `src/prosaic_harness/errors.py`, `src/prosaic_harness/__init__.py` — export `HumanResponseError` and `PendingInteraction`.
- Test: `tests/test_public_interactions.py`, `tests/test_human_responses.py`, `tests/test_store_engine.py`.
- Docs: `docs/workflow-factory.md`.

**Interfaces:**
- Produces: `Workflow.prepare_inputs(inputs) -> JSONValue` for admitted native workflows; preserve `Harness.run(inputs)` and keyword use `run(inputs=prepared_inputs)`.
- Produces: `Harness.interaction(*, review_outputs=(), include_response_schema=False, maximum_bytes=262_144) -> PendingInteraction | None`.
- `PendingInteraction` stores an immutable bounded JSON representation; scalar properties include `run_id`, `revision`, `step_id`, `question`, `deadline`, `response_schema_digest`; `choices` is a tuple of actual choice names. Nested schema/output properties return independently owned JSON. `to_dict()` returns camelCase keys `version`, `runId`, `revision`, `stepId`, `question`, `choices`, `deadline`, optional `responseSchemaDigest`, optional `responseSchema`, optional `reviewOutputs`.
- `HumanResponseError(ValueError)` exposes closed `code`, bounded tuple `issues` and `to_dict()` returning `{code, issues}`. Codes: `expected_revision_required`, `invalid_choice`, `response_requires_choice`, `response_not_allowed`, `response_limit`, `response_schema_invalid`, `response_validation_failed`, `no_pending_choice`, `completed_run`. Issues are at most five `{code, location}` objects; no raw instance values, schema prose or product-validator message. `RevisionConflict` remains separate.

- [ ] **Step 1: Write pure preparation RED.**

```python
def test_prepare_inputs_is_owned_bounded_and_does_not_reserve(tmp_path):
    workflow = factory(max_run_input_bytes=100).build(graph())
    inputs = {'query': 'safe'}
    prepared = workflow.prepare_inputs(inputs)
    inputs['query'] = 'mutated'
    assert prepared == {'query': 'safe'}
    with pytest.raises(WorkflowAdmissionError):
        workflow.prepare_inputs({'query': 'x' * 200})
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run RED and implement the admitted input boundary.** Run `.venv/bin/python -m pytest tests/test_public_interactions.py::test_prepare_inputs_is_owned_bounded_and_does_not_reserve -q`; expect missing method. Use a local import from workflow to avoid a factory/workflow import cycle:

```python
def prepare_inputs(self, inputs):
    from .factory import admit_workflow
    admission = admit_workflow(self)
    if admission is None:
        raise WorkflowAdmissionError('binding_mismatch') from None
    return snapshot_json(inputs,
        maximum_bytes=admission.policy.max_run_input_bytes,
        maximum_depth=admission.policy.max_json_depth,
        maximum_nodes=admission.policy.max_json_nodes)
```

Add the explicit `snapshot_json` import. Reuse this method in the native `Harness.run` input path after its own runtime/validator admission; retain existing legacy input handling and public execution admission. Add cyclic, shared-amplification, nonfinite-number and mutated-workflow tests; no model, validators, store methods, filesystem resolution or CLI discovery runs during preparation.
- [ ] **Step 3: Write and implement one-snapshot interaction.**

```python
def test_interaction_projects_only_selected_content(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch)
    h.run({'private_input': 'PRIVATE INPUT'})
    view = h.interaction()
    assert view.choices == ('accept', 'reject')
    assert view.revision == h.status().revision
    assert 'PRIVATE INPUT' not in json.dumps(view.to_dict())
    assert 'reviewOutputs' not in view.to_dict()
    selected = h.interaction(review_outputs=('find',))
    assert selected.to_dict()['reviewOutputs'] == {'find': {'found': True}}
    assert len(calls) == 1
```

Call `status()` exactly once, then derive all state/revision/content from that verified snapshot. Return `None` for nonwaiting states. Read question/choices from the already admitted current pause; expose choice names, not target graph internals. Compute schema digest with a documented stable existing digest recipe; include its body only when the host sets `include_response_schema=True`. Validate review-output selections as explicit known available agent output aliases; reject unknown/missing selection instead of publishing all outputs. Bound depth/nodes and final encoded bytes, capped by existing host/storage ceilings; raise safe `limit_exceeded` rather than truncate. Do not add a product-validator dry run.
- [ ] **Step 4: Add safe response errors without changing commit order.** Validate revision before callbacks and decisions. Map known response-bound/schema/choice/product-validator failures to `HumanResponseError` with trusted issue locations; reuse existing schema evaluator once. Preserve existing `SchemaEvaluationError` behavior, including terminal `blocked/schema_error` and deadline precedence. Preserve legacy `ValueError` compatibility via subclassing and existing expected-revision/completed/schema message keywords. Product validator details stay in existing operator context, never the public response error.

```python
def test_invalid_response_preserves_revision_and_has_safe_code(tmp_path, monkeypatch):
    from prosaic_harness import HumanResponseError
    proposal = graph()
    proposal['steps']['review']['response_schema'] = 'result'
    h, calls = bound(tmp_path, monkeypatch, proposal=proposal)
    h.run({})
    before = h.status()
    with pytest.raises(HumanResponseError) as caught:
        h.resume(choice='accept', response={'found': 'PRIVATE'},
                 expected_revision=before.revision)
    assert caught.value.code == 'response_schema_invalid'
    assert 'PRIVATE' not in json.dumps(caught.value.to_dict())
    after = h.status()
    assert after.revision == before.revision and after.state == before.state
    assert len(calls) == 1
```

Add typed and untyped pause cases, unknown choice, oversized views/responses, stale revision still `RevisionConflict`, nonwaiting/completed interactions, fresh-worker waiting view, returned nested-value mutation, one store load and one validator invocation per actual valid response. Gate/check output validation behavior remains unchanged.
- [ ] **Step 5: Run GREEN and document service use.** Run `.venv/bin/python -m pytest tests/test_public_interactions.py tests/test_human_responses.py tests/test_store_engine.py tests/test_schema_profile.py -q`. Document input preparation before host reservation, host-selected disclosure and revision CAS; `status()` remains the full operator view. Commit H3 files with `git commit -m "feat: add bounded public workflow interactions"` after diff check.

### Task H4: Frozen host bundles and reconstructable proposal references

**Files:**
- Create: `src/prosaic_harness/bundles.py` — canonical original envelope, immutable reference/prepared record and reconstruction.
- Modify: `src/prosaic_harness/factory.py` — private frozen-copy/material hooks, with no public host content disclosure.
- Modify: `src/prosaic_harness/__init__.py` — export `WorkflowBundle`, `WorkflowReference`, `PreparedWorkflow`.
- Test: `tests/test_workflow_bundles.py`; extend `tests/test_native_workers.py` fresh-process public API path.
- Docs: `docs/workflow-factory.md`.

**Interfaces:**
- Produces: `WorkflowBundle(version: str, factory: WorkflowFactory)`, read-only `.version` and `.identity`; `prepare_json(text: str) -> PreparedWorkflow`; `reconstruct(proposal_json: str, reference: WorkflowReference) -> Workflow`.
- `PreparedWorkflow` is frozen with `.workflow`, `.proposal_json` (exact canonical original envelope text) and `.reference`.
- `WorkflowReference` is a frozen validated scalar record: `version=1`, `bundle_version`, `bundle_identity`, `canonicalization='json-sort-keys-utf8-v1'`, `proposal_sha256`, `workflow_fingerprint`, `admission_version=1`, `schema_profile=1`. `to_dict()` uses `version`, `bundleVersion`, `bundleIdentity`, `canonicalization`, `proposalSha256`, `workflowFingerprint`, `admissionVersion`, `schemaProfile`; `from_dict(value)` validates exact keys/types/finite bounds/64-character lowercase digests with no callback hydration.
- Safe reference failures use existing `WorkflowAdmissionError`: malformed reference/envelope `invalid_definition`; version/bundle/proposal/fingerprint mismatch `identity_mismatch`; invalid/missing declared execution binding `binding_mismatch`. A missing retained bundle registry entry is an application/operator condition; Harness owns no registry.
- Private factory hooks `_frozen_copy() -> WorkflowFactory` and `_bundle_material() -> dict` snapshot execution material without invoking host callbacks. Bundle identity covers complete immutable factory agent/schema snapshots, policy identity, native effective config identity and declared tool/validator semantic versions plus enabled operation/cap bindings. Exclude public display metadata; do not derive identity from `describe()`.

- [ ] **Step 1: Write missing-export and reconstruct RED.**

```python
def test_bundle_reference_reconstructs_public_native_workflow():
    from prosaic_harness import WorkflowBundle, WorkflowReference
    first = WorkflowBundle('service-v1', factory()).prepare_json(envelope())
    reference = WorkflowReference.from_dict(first.reference.to_dict())
    second = WorkflowBundle('service-v1', factory()).reconstruct(first.proposal_json, reference)
    assert second.path is None
    assert second.fingerprint == first.workflow.fingerprint
    assert second.current_fingerprint() == reference.workflow_fingerprint
    assert 'limits' not in json.loads(first.proposal_json)['definition']
```

- [ ] **Step 2: Run RED.** Run `.venv/bin/python -m pytest tests/test_workflow_bundles.py::test_bundle_reference_reconstructs_public_native_workflow -q`; expect missing public exports.
- [ ] **Step 3: Implement bounded original-envelope canonicalization and frozen material.** Admit the envelope through the existing bounded parser and factory, before returning any reference. Preserve absence of optional inline mapping and graph defaults. Do not serialize the normalized workflow definition or expanded catalogue content:

```python
def canonical_proposal(envelope):
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)

def proposal_digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()
```

The envelope is already a bounded owned plain JSON snapshot; do not use these helpers on arbitrary caller objects before admission. Bound UTF-8 canonical output before retaining it, without changing the global existing `snapshot_json` encoding contract. Validate version labels as nonempty bounded opaque host strings (128 UTF-8 bytes, no controls). `WorkflowBundle` captures a frozen factory independently of later caller-container or factory-field changes. References contain only opaque hashes and version/profile metadata; config and host content stay private.
- [ ] **Step 4: Implement re-admission and immutable identity matching.** Reconstruction verifies supported reference format/canonicalization, exact bundle version+identity, canonical proposal digest and finally the freshly factory-admitted workflow fingerprint/profile. It returns only the admitted native workflow. Reject altered content/config/tool/validator versions, unknown reference keys, tampered hashes, wrong policy projection and any attempt to deserialize endpoints/callbacks. Package version is informative deployment metadata, not a substitute for material identity.

```python
def test_same_version_changed_material_is_rejected():
    from prosaic_harness import WorkflowBundle
    saved = WorkflowBundle('service-v1', factory()).prepare_json(envelope())
    changed = WorkflowBundle('service-v1', factory(max_calls=11))
    with pytest.raises(WorkflowAdmissionError) as caught:
        changed.reconstruct(saved.proposal_json, saved.reference)
    assert caught.value.code == 'identity_mismatch'
```

Add an accepted non-ASCII question near a small proposal cap; `prepare_json` then canonical reconstruction must succeed and produce identical hashes. Test shuffled database JSON key ordering reproduces canonical bytes; exact text storage preserves bytes. Public description changes leave bundle identity unchanged; private agent/schema/policy/config/version changes alter it, including unused frozen bundle material. Test callback functions are never called and cannot be hydrated from reference JSON. Extend the existing isolated fresh-worker test to persist proposal text/reference and reconstruct through only public APIs, preserving waiting revision and completing without a second provider call.
- [ ] **Step 5: Run GREEN and document retention obligations.** Run `.venv/bin/python -m pytest tests/test_workflow_bundles.py tests/test_native_workers.py tests/test_workflow_factory.py -q`. Document that hosts retain immutable bundle registrations and current authorization/revocation checks, store exact canonical proposal text and reference, and never silently use the newest bundle for an old run. Commit H4 files with `git commit -m "feat: reconstruct native workflows from frozen host bundles"` after diff check.

### Task H5: Runtime budgets, operation scope and native recovery gates

**Files:**
- Modify: `src/prosaic_harness/factory.py` — optional policy caps, native journal bindings/record/identity and repeated admission checks.
- Modify: `src/prosaic_harness/engine.py` — remaining allowances, capability checks and trusted Runtime dispatch options.
- Modify: `src/prosaic_harness/bundles.py` — include enabled bindings in private bundle material through the H4 hook.
- Test: `tests/test_runtime_boundaries.py`, `tests/test_workflow_factory.py`, `tests/test_transport.py`, `tests/test_native_workers.py`, `tests/test_recovery_contracts.py`, `adapters/postgres/tests/test_native_factory.py`.
- Docs: `docs/workflow-factory.md`, `docs/accounting.md`; record qualification commands/counts in `docs/harness-production-verification.md`.

**Interfaces:**
- Consumes: Runtime `RunPolicy(max_provider_requests=None, max_tool_calls=None, max_reported_tokens=None)`, `InvocationScope`, `tool_journal_descriptor`, capability flags and `run(..., operation_context=None, tool_journal=None)`.
- Produces: `WorkflowPolicy(max_provider_requests_per_invocation=None, max_tool_calls_per_invocation=None)`; `WorkflowBindings(*, config, custom_tools=None, validators=None, operation_namespace=None, tool_journal=None)`.
- Optional cap values are exact nonnegative `int` or `None` (`bool` rejected). `_identity()` excludes `None` new fields. Public describe reports enabled caps and their explicit per-invocation units, without adding provider/tool limits to client graph `limits`.
- Journal binding snapshot retains the trusted backend object privately and a bounded plain descriptor `{identity, contract_version}` plus a bounded nonempty opaque `operation_namespace`. Read metadata using Runtime's static descriptor helper, never a journal property/probe. Namespace is mandatory when journaled execution is enabled. `_AdmissionRecord` adds optional private journal/namespace/descriptor fields; none are serialized into checkpoint v2/receipt v1.
- Seal enabled relevant operation bindings in native workflow and bundle material, alongside demanded context/journal tool descriptors. Recheck actual descriptor/namespace before status/resume/dispatch; swapping a declared durable journal domain rejects. The host is responsible for making opaque identity correspond to the actual durable ledger across replicas.
- Per dispatch create `InvocationScope(invocation_id=attempt_id, run_id=state['run_id'], step_id=name, operation_namespace=sealed_namespace)`. The persisted attempt ID is correlation, not a business idempotency key. Do not use accounting context to transport this scope or enable accounting merely because a tool needs context.

- [ ] **Step 1: Pin disabled identity before adding fields.** Capture fixed fixture fingerprints and descriptor JSON from current released behavior, then add tests that constructing policies/bindings with omitted or explicit `None` new fields yields those exact values. Test enabled zero/positive caps change identity, omitted `model_tier` remains authorized and unused unrelated tool registrations retain existing workflow identity behavior. Run `.venv/bin/python -m pytest tests/test_runtime_boundaries.py -q`; new constructor fields must initially fail RED.
- [ ] **Step 2: Add caps and pure binding validation.** Keep new policy fields separate from the existing strictly positive policy loop. Keep all existing field/default identities unchanged:

```python
if item.name in {'max_provider_requests_per_invocation',
                 'max_tool_calls_per_invocation'}:
    if value is not None and (type(value) is not int or value < 0):
        raise WorkflowAdmissionError('invalid_definition') from None
    continue
```

Call `tool_journal_descriptor` only for configured journals and store its bounded output. Reject dynamic metadata descriptors without evaluation. Seal opaque identity/contract/namespace when enabled; never hash callback repr, Python object identity, DSN or storage path. Demand `tool_journal_v1` for a journaled native tool and `tool_context_v1` for enabled contextual dispatch. Validate matching live adapter tool descriptors as before; do not broaden native acceptance to arbitrary/fake runtime objects.
- [ ] **Step 3: Test and implement the dispatch seam.** Extend the exact-runtime patched fixture to record `policy`/`operation_context`/`tool_journal` and assert:

```python
def test_native_dispatch_receives_remaining_units_and_separate_scope(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch, max_tokens=20,
                     max_provider_requests_per_invocation=2,
                     max_tool_calls_per_invocation=1)
    h.run({})
    options = calls[0][1]
    assert options['policy'].max_reported_tokens == 20
    assert options['policy'].max_provider_requests == 2
    assert options['policy'].max_tool_calls == 1
    assert options['operation_context'].invocation_id == h.status().state['invocations'][0]['id']
    assert 'context' not in options and 'accounting' not in options
```

Compute remaining reported tokens from verified complete invocation ledger entries and reject/stop if usage is unknown under the workflow token cap. Existing workflow resource checks stay ahead of any new dispatch. Pass remaining workflow time through the already shared per-invocation timeout; do not reset the persisted run deadline on resume. Native Runtime caps are the host per-invocation caps and remaining token allowance. Keep `max_calls` in Harness only. Capability failures reject before pending state/model dispatch. Legacy fake adapters retain existing behavior when new controls are disabled; do not pass unsupported keywords merely because a new SDK has them.

```python
options = {'operation_context': InvocationScope(
    invocation_id=attempt_id, run_id=state['run_id'], step_id=name,
    operation_namespace=admission.operation_namespace)}
if admission.tool_journal is not None:
    options['tool_journal'] = admission.tool_journal
```

Only pass scope to a capable standard runtime; observer uses H1's separate channel. Preserve critical event capture, receipt-before-accept order, lease checks, schema validation and recorded incurred/unknown usage. A Runtime journal uncertainty failure is a terminal invocation failure receipt; Harness does not turn it into automatic graph/model retry or reconcile the journal.
- [ ] **Step 4: Add effect and budget failure witnesses.** Use a statically declared test journal with `identity='owned-ledger-v1'`, `contract_version='tool-journal-v1'`, and public Runtime `ToolClaim(state, signature, claim_token=None, outcome=None)`. Verify pure assembly never calls claim/commit. A property-backed identity whose getter raises must be rejected without running the getter. Fresh host registrations with the same identity reconstruct; identity/namespace changes reject before calls. Add a synthetic provider fixture with multiple turns and explicit usage: second native invocation receives remaining allowance; unknown/over-cap terminal usage blocks further work with a completed durable ledger; exactly-at-cap final response retains Runtime's permitted success. Provider/tool counts are actual Runtime units, not workflow calls. Test cancellation before dispatch, after an applied journal effect, and after committed outcome; explicit `retry_interrupted=True` cannot execute an uncertain journal effect.
- [ ] **Step 5: Qualify fresh workers and real RunStore recovery.** Extend the isolated worker and existing PG native factory cases with bundle/reference reconstruction and public interaction. Exercise normal and bounded failure receipt adoption after a crash between `save_receipt` and `_accept`; fresh worker resumes without another request, preserves usage/validator versions, and returns the correct interaction revision. Invalid/stale human decisions preserve PG state/revision. Journal demonstration persistence/domain reconciliation remains owned by Lab; Harness tests consume its public protocol and never write business operation records into RunStore.

Run focused source checks:

```bash
PYTHONPATH=../prosaic/src:../prosaic-runtime/src:src .venv/bin/python -m pytest tests/test_runtime_boundaries.py tests/test_workflow_factory.py tests/test_native_execution.py tests/test_native_workers.py tests/test_recovery_contracts.py -q
```

Then use installed candidate wheels and a disposable test database supplied by the coordinator:

```bash
.venv/bin/python -m pytest adapters/postgres/tests/test_native_factory.py adapters/postgres/tests/test_engine.py adapters/postgres/tests/test_store.py adapters/postgres/tests/test_recovery.py --require-postgres -q
```

`HARNESS_TEST_DATABASE_URL` must identify an explicitly owned fixture; absence is a failure in this required lane, not qualifying skips. Run the native subset against PostgreSQL 16 and 18, and retain existing remote full crash/standby gates through the unchanged CI fixture. Do not restart shared Docker or connect to shared service databases.
- [ ] **Step 6: Run whole-stack gates and record evidence.** With installed qualified candidate dependencies, run `.venv/bin/python -m pytest`, `.venv/bin/python -m build`, and the existing `scripts/workflow_factory_smoke.py` from a clean candidate-wheel environment using `python -I`. Extend that smoke's public API checks to include discovery, bundle/reference, input preparation and interaction. Root owns exact wheel installation/version names and clean-archive qualification; record counts/versions/architectures and any unavailable external lane separately. Review all H1–H5 compatibility tests and mandatory Linux/PG lane results, then commit H5 files with `git commit -m "feat: bind Runtime budgets and effect scope to native workflows"` after diff check.

## Self-review and execution handoff

- [x] Spec coverage: H1 implements the Harness part of Milestone 1; H2–H4 implement Milestone 2; H5 implements Harness integration of Milestone 4. Milestone 3's application registry/auth/idempotency/journal implementation belongs to the Lab plan. Runtime execution/conformance, Core mutation/validation, release machinery and operational deployment lanes belong to their respective plans.
- [x] Type consistency: Lab consumes `PreparedWorkflow.workflow/proposal_json/reference`, `WorkflowReference.to_dict/from_dict`, `PendingInteraction.to_dict`, and unchanged `Harness.run(inputs=...)`. H5 consumes the Runtime names/signatures recorded above and feeds enabled identities into H4's material hook.
- [x] Review Focus: all five failure classes have explicit owning task tests, including actual committed state fallback, unbound discovery aliases, input/response bounds, Unicode reconstruction and receipt/journal recovery.
- [x] Authority and compatibility: no projection admits a graph, no reference hydrates callbacks, no default-tier rule changes, no disabled-field fingerprint drift, no checkpoint/receipt schema change, and no scope-driven accounting enablement.
- [x] Plan contains concrete RED/GREEN commands, file ownership, bounded public shapes, representative regression code and implementation boundaries; no unresolved design handoff remains.

Execute H1–H5 with focused TDD and independent task review, coordinating shared factory/engine edits. Commit only passing coherent task changes and leave package/release changes to the coordinator. Record observed gates before completion; source test success does not replace installed-wheel/native platform/database qualification.
