# Validated In-Memory Workflow Factory Implementation Plan

> **For agentic workers:** Use the implementation skills with tests first, scoped independent repository tasks and one complete final review. Track all steps in the execution ledger.

**Goal:** Deliver the revised production MVP factory and enforce its admission and recovery guarantees.
**Architecture:** Pure Prosaic/Runtime validators feed bounded Harness resolution and graph admission. A native Workflow subtype owns a sealed admission record; Harness verifies it at execution boundaries and persists bounded failure outcomes.
**Tech stack:** Python 3.11+, existing Prosaic/Runtime/Harness, jsonschema 4.23+, referencing, pytest and build.
**Spec:** ../specs/2026-10-09-workflow-mvp-design.md

## Global constraints

- Python production code only; core canonical/on-disk camelCase contracts remain compatible.
- Preserve legacy YAML fingerprints/default omissions, checkpoint v2, receipt v1, explicit interrupted retry and sole Harness state writer.
- Client data supplies no paths/endpoints/executable bindings, base_dir or validation bypass.
- Omitted model_tier authorizes the host default; explicit tiers require route and policy.
- Hostapproved catalogue schemas only; inline-agent/composition permissions separate; native-only dynamic grants.
- No live providers/product effects, remote publishing, broad cleanup or unrelated user changes.
- apply_patch for edits. Full .venv/bin/python -m pytest suites; core immutable migration oracle; builds and installed wheel checks.
- Exact defaults and limits are the normative spec table; no duplicated incompatible magic values.
- Feature branches codex/validated-workflow-factory in three repositories. Native worktree creation failed ENOSPC; preserve roots and do not implement on main.

## Review focus

- Aliased Python DAGs must fail without exponential copying or hashing.
- Missing provenance/correct recomputed hashes must not downgrade factory admission.
- Unicode/events/metadata must not prevent durable completion after returned inference.
- Registry collisions and evaluator changes must not alter acceptance under the same native seal.
- Old deep/recursive YAML human decisions and acquisition inheritance must still resume.

### Task 1: Prosaic canonical definition API

Files: src/prosaic/core.py, src/prosaic/__init__.py, tests/test_public_validation.py, README.md.
Produces: validate_artifact_definition(kind, frontmatter)->dict using existing ok/field/reason/frontmatter contract.

- [x] Add failing public behavior tests:
```python
def test_explicit_kind_conflict():
    from prosaic import validate_artifact_definition
    assert not validate_artifact_definition("subagent", {"type": "rule", "name": "n", "description": "d"})["ok"]
def test_absent_declared_type_keeps_content():
    from prosaic import validate_artifact_definition
    fm = {"name": "n", "description": "d", "vendor": {"mode": "x"}}
    admitted = validate_artifact_definition("subagent", fm)
    assert admitted["ok"] and "type" not in admitted["frontmatter"] and "type" not in fm
```
- [x] Verify RED against the missing export; implement additive kind/type agreement followed by existing validate_frontmatter, retaining existing helper/discovery behavior.
- [x] Cover all supported kinds, bad kinds/types, required fields and permissive executable extensions.
- [x] Run focused tests, full suite and scripts/verify_migration.py with existing immutable oracle. Review the diff; commit local API change only after green.

### Task 2: Runtime pure execution and registry APIs

Files: src/prosaic_runtime/artifacts.py or new admission.py, runtime.py, __init__.py, tests/test_artifact_admission.py; provider check helper if shared with anthropic.py.
Produces: validate_execution_artifact(artifact, config, *, acquisition=None)->None, validate_custom_tools(mapping)->dict, custom_descriptors(mapping)->dict.
Consumes: existing structural inspection, RuntimeConfig, requested_tools; does not require new core semantics inside Runtime.

- [x] Add failing tests exercising public helper before Runtime construction, including a config with missing tool_directories.
```python
def test_acquisition_uses_final_provider():
    config = mixed_provider_config(default="anthropic", route="openai")
    final = artifact(model_tier="fast", effort="low", tools=["read_file"])
    acquisition = artifact(effort="low", tools=["read_file"])
    validate_execution_artifact(final, config, acquisition=acquisition)
```
- [x] Verify RED; implement structural/tool-syntax/effort checks, final context resolution and provider restrictions with effective features; acquisitions validate consistency under final context.
- [x] Reuse helper in Runtime._run and export pure registry helpers without discovery/constructor effects.
- [x] Test malformed effort/routes/tools, known provider features, matching/conflicting inheritance, raw artifact/config unchanged, and local HTTP behavior.
- [x] Run full Runtime suite. Review/commit local changes and prerequisite dependency pin after core commit.

### Task 3: Harness bounded JSON and schema profile

Files: new errors.py, admission_data.py, schema_validation.py; tests/test_admission_data.py, tests/test_schema_profile.py.
Produces:
```python
snapshot_json(value, *, maximum_bytes, maximum_depth=64, maximum_nodes=65536)
parse_bounded_json(text, *, maximum_bytes, maximum_depth=64, maximum_nodes=65536)
admit_schema(schema, *, profile)  # pure local resolution/ambiguity/cycle admission
evaluate_schema(schema, instance, *, profile=None, max_errors=5)  # bounded safe issue strings
```
SchemaEvaluationError distinguishes evaluation failure from invalid instance; profile=None preserves legacy instance acceptance.

- [x] Add failing behavior tests for alias amplification, cycles/nonfinite data, raw duplicates/depth/Unicode errors:
```python
def test_shared_dag_rejected_before_expansion():
    value = []
    for _ in range(50):
        value = [value, value]
    with pytest.raises(WorkflowAdmissionError):
        snapshot_json(value, maximum_bytes=262144)
```
- [x] Verify RED; implement iterative preflight before copying/hashing, exact finite JSON encoded-size/work bounds and owned snapshots.
- [x] Add RED isolated-registry/duplicate-anchor tests; implement schema-position traversal, no retrieval, resolved targets, duplicate resource/anchor rejection and conservative cycles/dynamic-reference restrictions.
- [x] Test valid local defs/anchors, unused collisions, JSON data containing ref-like keys, dynamic dialect/instance bounds and legacy 70-depth/productive recursion.
- [x] Review focused tests; run affected/full Harness suite when dependency APIs are available.

### Task 4: Shared graph admission and factory

Files: new graph_admission.py, factory.py; workflow.py, __init__.py; tests/test_workflow_factory.py, legacy validation fixtures.
Consumes Tasks 1–3 and existing immutable tools/validators. Produces four public host APIs, native subtype/admission record and shared resolved graph validator.

- [x] Add RED public factory example using inspected/composed agents and native tools; assert native path=None and no effectful assembly:
```python
def test_factory_rejects_unauthorized_tool(factory):
    graph = one_agent_graph(tools=["write_file"])
    with pytest.raises(WorkflowAdmissionError):
        factory.build(graph)
```
- [x] Implement policy validation, owned catalog/config/tool/validator snapshots, native config derivation and strictly bounded build/build_json.
- [x] Extract graph invariants without changing legacy normalization/fingerprints; invoke core/execution helpers and schema profile with adapter-specific privileges.
- [x] Implement immutable original seal and fixed native subtype; compare actual content against it, never infer legacy from removed record.
- [x] Cover aliases/collisions, inline permissions, multi-agent composition, explicit/default tiers, graph loops/references, schema aliases, unused identity, mixed CLI host config and forged raw/native workflows.
- [x] Update incomplete legacy test doubles to valid canonical artifacts rather than weakening canonical admission. Pin exact known YAML identities.

### Task 5: Harness mandatory admission and bounded recovery

Files: engine.py, contracts.py, file_store.py/run_store.py/store.py only as needed for consistent representation; tests/test_native_execution.py, test_native_recovery.py, test_native_limits.py.
Consumes native record, graph/schema helpers and Runtime APIs; preserves store protocol/version/seals.

- [x] Add RED native local HTTP tool/JSON/pause/restart flow in file and database-style store fixtures.
- [x] Validate before construction effects/run/resume/status/dispatch; default native registrations/validators, independent Runtime config and standard matching override checks. Positively admit legacy manual/pathful objects.
- [x] Own temporary cwd for native run/resume, cleanup on all exits, never cwd fallback. Keep legacy root/evidence behavior.
- [x] Add RED over-budget request/prepared prompt tests proving no initial state or phantom pending invocation; enforce before attempts/calls/pending.
- [x] Add RED ASCII/Unicode/event/metadata receipt overflow tests; implement bounded failure receipt with accounting/ledger preservation and exact serializer budgeting.
- [x] Guard state growth before accepting human responses/output bindings; retain bounded valid checkpoints and terminal-limit headroom.
- [x] Centralize all schema evaluation paths, terminal schema_error, saved receipt adoption and existing resource precedence:
```python
def test_saved_failure_receipt_not_retried(recovered_harness, provider):
    state = recovered_harness.resume(retry_interrupted=True)
    assert state["calls"] == 1 and state["status"] == "blocked"
    assert provider.requests == 1
```
- [x] Cover stripped provenance/recomputed hashes, adapter mutations, CLI names, validators, cleanup, expected human revision, crash edges and historical legacy decisions/acquisitions.
- [x] Run full Harness suite and neutral installed integration consumer gates.

### Task 6: Documentation, packaging and final review

Files: public README/API docs, offline in-memory example, wheel smoke script/tests, three pyproject files as immutable dependency pins require.
- [x] Document scope/default-model rule, sealed profile, native binding effects, trusted schema/callback duties and exact limit/recovery semantics.
- [x] Build all wheels in dependency order using existing runtimes/no unnecessary reinstalls.
- [x] Install candidate wheels with dependencies in a clean temporary environment; smoke public imports/core wheel script/native local HTTP example without Node/prosaic CLI. No live models.
- [x] Run supported Python and minimum/current jsonschema compatibility where configured interpreters/dependencies exist; report unavailable matrix cells explicitly.
- [x] Dispatch fresh whole-change review with spec/plan/diffs and test evidence. Resolve important findings with meaningful RED→GREEN tests, rerun only newly affected checks.
- [x] Preserve unrelated changes and historic research; leave reviewed local feature commits and report actual verification plus any unpublished pin/release limitation. Do not push/merge/publish automatically.

## Execution ledger

Task status, completed checks and release limitations live in docs/superpowers/plans/2026-10-09-workflow-factory-progress.md. The user explicitly authorized implementation after the design update. Native worktree creation failed ENOSPC; feature branches provided isolation. Authorized cleanup restored writes, all six implementation tasks and independent review are complete, and unrelated files were preserved.
