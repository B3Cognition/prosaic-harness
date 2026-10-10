"""The YAML resolver feeds shared admission without adopting native limits."""
import json

import pytest
import yaml

from prosaic_harness import Workflow
from prosaic_harness.schema_validation import evaluate_schema
from prosaic_runtime import ProsaicArtifact, CustomTool


def blueprint(tmp_path, monkeypatch, *, schema=None, artifact=None, pause=False):
    (tmp_path / '.prosaic').mkdir()
    (tmp_path / 'runtime.yml').write_text(
        'default_profile: local\nroutes: {fast: local}\nprofiles:\n'
        '  local:\n    base_url: http://localhost:9/v1\n    model: fake\n')
    (tmp_path / 'schema.json').write_text(json.dumps(True if schema is None else schema))
    raw = {'version': 1, 'start': 'author', 'runtime': 'runtime.yml', 'source': '.prosaic',
           'steps': {'author': {'kind': 'agent', 'agent': 'subagents/author.md',
                                'schema': 'schema.json', 'next': 'done'},
                     'done': {'kind': 'finish'}}}
    if pause:
        raw['steps']['author']['next'] = 'review'
        raw['steps']['review'] = {'kind': 'pause', 'question': 'Approve?',
                                  'choices': {'yes': 'done'}, 'response_schema': 'schema.json'}
    path = tmp_path / 'workflow.yml'
    path.write_text(yaml.safe_dump(raw))
    inspected = artifact or ProsaicArtifact('subagents/author.md', 'subagent',
        {'name': 'author', 'description': 'Author', 'model_tier': 'fast'}, 'Return JSON.')
    monkeypatch.setattr('prosaic_harness.workflow.inspect_artifact', lambda *args, **kwargs: inspected)
    return path


@pytest.mark.parametrize('frontmatter', [
    {'name': 1, 'description': 'Author'},
    {'name': 'author', 'description': 'Author', 'type': 'rule'},
    {'name': 'author', 'description': 'Author', 'effort': 'unsupported'},
])
def test_yaml_loader_applies_shared_canonical_and_execution_checks(tmp_path, monkeypatch, frontmatter):
    path = blueprint(tmp_path, monkeypatch, artifact=ProsaicArtifact(
        'subagents/author.md', 'subagent', frontmatter, 'Return JSON.'))
    with pytest.raises(ValueError):
        Workflow.load(path)


def test_legacy_recursive_schemas_and_deep_decisions_stay_admitted(tmp_path, monkeypatch):
    schema = {'type': 'object', 'properties': {'child': {'$ref': '#'}}}
    workflow = Workflow.load(blueprint(tmp_path, monkeypatch, schema=schema, pause=True))
    value = {}
    for _ in range(70):
        value = {'child': value}
    assert evaluate_schema(workflow.schemas['author'], value) == []
    assert evaluate_schema(workflow.schemas['review'], value) == []
    assert workflow.definition['limits'] == {'max_calls': 12, 'max_visits': 4, 'timeout_s': 180}
    assert 'max_tokens' not in workflow.definition['limits']


def test_legacy_loader_preserves_nested_dialect_and_large_schema(tmp_path, monkeypatch):
    schema = {'type': 'object', 'description': 'host content' * 6000, 'properties': {
        'child': {'$schema': 'http://json-schema.org/draft-07/schema#',
                  'type': 'object', 'unevaluatedProperties': False}}}
    workflow = Workflow.load(blueprint(tmp_path, monkeypatch, schema=schema))
    assert evaluate_schema(workflow.schemas['author'], {'child': {'extra': 1}}) == []
    assert len(workflow.schemas['author']['description']) > 65536


def test_legacy_loader_admits_schema_tree_beyond_native_depth(tmp_path, monkeypatch):
    schema, value = True, 1
    for _ in range(70):
        schema = {'type': 'array', 'items': schema}
        value = [value]
    workflow = Workflow.load(blueprint(tmp_path, monkeypatch, schema=schema, pause=True))
    assert evaluate_schema(workflow.schemas['author'], value) == []
    assert evaluate_schema(workflow.schemas['review'], value) == []


@pytest.mark.parametrize('schema', [
    {'$ref': 'https://external.test/schema'}, {'const': {'$dynamicRef': 'external'}},
])
def test_legacy_external_reference_diagnostic_is_compatible(tmp_path, monkeypatch, schema):
    with pytest.raises(ValueError, match='internal'):
        Workflow.load(blueprint(tmp_path, monkeypatch, schema=schema))


def test_legacy_invalid_schema_diagnostic_is_compatible(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='definition'):
        Workflow.load(blueprint(tmp_path, monkeypatch, schema={'type': 'wrong'}))


def test_legacy_identity_is_fixed_across_shared_admission(tmp_path, monkeypatch):
    workflow = Workflow.load(blueprint(tmp_path, monkeypatch))
    # Fixed released payload: no temporary paths, model inference or native profile.
    assert workflow.fingerprint == '88777fa42b190129c4d28f599ccf35f61f84206630e7eb71315670437c15875e'
    assert workflow.current_fingerprint() == workflow.fingerprint


def test_unused_native_registration_does_not_change_legacy_identity(tmp_path, monkeypatch):
    path = blueprint(tmp_path, monkeypatch)
    baseline = Workflow.load(path)
    tool = CustomTool('unused', 'Unused host tool',
                      {'type': 'object', 'additionalProperties': False}, lambda args: args, 'v1')
    registered = Workflow.load(path, custom_tools={'unused': tool})
    assert registered.fingerprint == baseline.fingerprint
    assert registered.tool_descriptors == {}
    descriptor_snapshot = registered._registered_descriptors
    assert descriptor_snapshot == {'unused': tool.descriptor}
    descriptor_snapshot['unused']['version'] = 'forged'
    assert registered._registered_descriptors['unused']['version'] == 'v1'


def test_empty_legacy_read_root_and_gate_property_keys_remain_valid(tmp_path, monkeypatch):
    artifact = ProsaicArtifact('subagents/author.md', 'subagent',
        {'name': 'author', 'description': 'Author', 'tools': ['read_file']}, 'Return JSON.')
    path = blueprint(tmp_path, monkeypatch, artifact=artifact)
    raw = yaml.safe_load(path.read_text())
    raw['steps']['author'].update(tools=['read_file'], read_roots=[''], next='gate')
    raw['steps']['gate'] = {'kind': 'gate', 'from': 'author', 'field': [''],
                           'equals': 1, 'pass': 'done', 'fail': 'done'}
    path.write_text(yaml.safe_dump(raw))
    config = yaml.safe_load((tmp_path / 'runtime.yml').read_text())
    config['allowed_tools'] = ['read_file']
    (tmp_path / 'runtime.yml').write_text(yaml.safe_dump(config))
    workflow = Workflow.load(path)
    assert workflow.definition['steps']['gate']['field'] == ['']
    assert workflow.definition['steps']['author']['read_roots'] == ['']
