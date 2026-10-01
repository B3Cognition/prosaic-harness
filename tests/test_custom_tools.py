from dataclasses import asdict
import json
import shutil
import pytest
import yaml
from prosaic_runtime import CustomTool, ProsaicRuntime
from prosaic_harness import Harness, Workflow
from prosaic_harness.workflow import digest
from test_transport import endpoint, text

SCHEMA = {'type': 'object', 'required': ['sku'], 'properties': {'sku': {'type': 'string'}}, 'additionalProperties': False}


def tools(version='v1', seen=None, unused='unused-v1'):
    return {'lookup_catalog': CustomTool('lookup_catalog', 'Lookup', SCHEMA,
        lambda a: (seen.append(a) if seen is not None else None) or {'found': True}, version),
        'unused_tool': CustomTool('unused_tool', 'Unused', SCHEMA, lambda a: None, unused)}


def blueprint(tmp_path, url, *, grants=True, prose=True, required=True):
    if not shutil.which('prosaic'):
        pytest.skip('install Prosaic CLI for integration tests')
    source = tmp_path / '.prosaic/subagents'; source.mkdir(parents=True, exist_ok=True)
    (source / 'catalog.md').write_text('---\nname: catalog\ndescription: Catalogue lookup\nmodel_tier: fast\ntools: ' +
        ('[lookup_catalog]' if prose else 'none') + '\n---\nLookup SKU-001. Return JSON. {{args}}\n')
    (tmp_path / 'runtime.yml').write_text(yaml.safe_dump({'default_profile': 'local', 'routes': {'fast': 'local'},
        'allowed_tools': ['lookup_catalog'] if grants else [],
        'profiles': {'local': {'base_url': url, 'model': 'test', 'features': {'streaming': False}}}}))
    (tmp_path / 'result.json').write_text(json.dumps({'type': 'object', 'required': ['found'],
        'properties': {'found': {'type': 'boolean'}}, 'additionalProperties': False}))
    data = {'version': 1, 'runtime': 'runtime.yml', 'start': 'lookup', 'steps': {
        'lookup': {'kind': 'agent', 'agent': 'subagents/catalog.md', 'schema': 'result.json',
                   'tools': ['lookup_catalog'], 'require_tools': ['lookup_catalog'] if required else [], 'max_attempts': 1, 'next': 'approval'},
        'approval': {'kind': 'pause', 'question': 'Accept?', 'choices': {'approve': 'done', 'reject': 'rejected'}, 'requires': ['lookup']},
        'done': {'kind': 'finish', 'requires': ['lookup']}, 'rejected': {'kind': 'finish', 'outcome': 'rejected'}}}
    path = tmp_path / 'flow.yml'; path.write_text(yaml.safe_dump(data))
    return path


def call():
    return {'content': '', 'tool_calls': [{'id': 'lookup', 'type': 'function', 'function': {
        'name': 'lookup_catalog', 'arguments': '{"sku":"SKU-001"}'}}]}


def test_native_custom_workflow_pauses_and_rejects_without_inference(endpoint, tmp_path):
    url, requests, replies = endpoint
    seen = []
    registry = tools(seen=seen)
    workflow = Workflow.load(blueprint(tmp_path, url), custom_tools=registry)
    registry.clear()
    replies.extend([call(), text({'found': True})])
    harness = Harness(workflow, tmp_path / 'run')
    assert harness.run({'sku': 'SKU-001'})['status'] == 'waiting'
    assert seen == [{'sku': 'SKU-001'}]
    receipt = json.loads(next((tmp_path / 'run/attempts').glob('*.json')).read_text())
    assert any(e.get('tool_version') == 'v1' and e.get('status') == 'ok' for e in receipt['events'])
    assert harness.resume(choice='reject')['status'] == 'rejected' and len(requests) == 2


@pytest.mark.parametrize('kind', ['missing_registration', 'config', 'prose'])
def test_preflight_denies_missing_custom_grant(endpoint, tmp_path, kind):
    url, requests, replies = endpoint
    path = blueprint(tmp_path, url, grants=kind != 'config', prose=kind != 'prose')
    with pytest.raises(ValueError):
        Workflow.load(path, custom_tools={} if kind == 'missing_registration' else tools())
    assert requests == []


@pytest.mark.parametrize('mismatch', ['capability', 'descriptor'])
def test_injected_adapter_preflight_identity(endpoint, tmp_path, mismatch):
    url, requests, replies = endpoint
    workflow = Workflow.load(blueprint(tmp_path, url), custom_tools=tools())
    adapter = ProsaicRuntime(workflow.config, custom_tools=tools('wrong' if mismatch == 'descriptor' else 'v1'))
    if mismatch == 'capability':
        adapter.capabilities = frozenset()
    with pytest.raises(ValueError, match='custom'):
        Harness(workflow, tmp_path / 'run', runtime=adapter)
    assert requests == []


@pytest.mark.parametrize('wrong_version', [False, True])
def test_required_execution_rejects_missing_or_wrong_version(endpoint, tmp_path, wrong_version):
    url, requests, replies = endpoint
    workflow = Workflow.load(blueprint(tmp_path, url), custom_tools=tools())
    adapter = ProsaicRuntime(workflow.config, custom_tools=tools())
    if wrong_version:
        native_run = adapter.run
        def run(*args, **kwargs):
            on_event = kwargs.pop('on_event')
            def event(e):
                on_event({**e, 'tool_version': 'wrong'} if e['event'] == 'tool_completed' else e)
            return native_run(*args, on_event=event, **kwargs)
        adapter.run = run
        replies.append(call())
    replies.append(text({'found': True}))
    state = Harness(workflow, tmp_path / 'run', runtime=adapter).run({})
    assert state['status'] == 'blocked' and state['reason'] == 'attempt_limit'
    assert state['outputs'] == {} and 'lookup_catalog' in state['feedback']


def test_required_version_blocks_resume_unused_change_does_not(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = blueprint(tmp_path, url)
    workflow = Workflow.load(path, custom_tools=tools())
    replies.extend([call(), text({'found': True})])
    assert Harness(workflow, tmp_path / 'run').run({})['status'] == 'waiting'
    changed = Workflow.load(path, custom_tools=tools('v2'))
    with pytest.raises(ValueError, match='changed'):
        Harness(changed, tmp_path / 'run').resume(choice='approve')
    unused_changed = Workflow.load(path, custom_tools=tools(unused='unused-v2'))
    assert unused_changed.fingerprint == workflow.fingerprint
    assert Harness(unused_changed, tmp_path / 'run').resume(choice='reject')['status'] == 'rejected'
    assert len(requests) == 2


def test_prose_requested_but_ungranted_descriptor_is_bound(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = blueprint(tmp_path, url, required=False)
    data = yaml.safe_load(path.read_text()); data['steps']['lookup']['tools'] = []
    path.write_text(yaml.safe_dump(data))
    workflow = Workflow.load(path, custom_tools=tools())
    assert set(workflow.tool_descriptors) == {'lookup_catalog'}
    assert Workflow.load(path, custom_tools=tools('v2')).fingerprint != workflow.fingerprint


def test_legacy_fingerprint_unchanged(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = blueprint(tmp_path, url, prose=False, required=False)
    data = yaml.safe_load(path.read_text()); data['steps']['lookup']['tools'] = []
    path.write_text(yaml.safe_dump(data))
    workflow = Workflow.load(path, custom_tools=tools())
    expected = digest({'workflow': workflow.definition, 'runtime': asdict(workflow.config) | {'allowed_tools': sorted(workflow.config.allowed_tools)},
                       'schemas': workflow.schemas, 'prose': {name: a.digest for name, a in workflow.artifacts.items()}})
    assert workflow.fingerprint == expected and workflow.current_fingerprint() == expected
    assert workflow.tool_descriptors == {}
