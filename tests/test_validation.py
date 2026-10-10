import json
import subprocess
import sys

import pytest
from prosaic_harness import Harness, Workflow
from prosaic_harness.store import locked
from test_harness import setup, FakeRuntime


@pytest.mark.parametrize('boundary', ['resume', 'status'])
def test_live_validator_version_cannot_change_after_construction(tmp_path, monkeypatch, boundary):
    from prosaic_harness import Validator
    setup(tmp_path, monkeypatch, pause=True)
    path = edit_flow(tmp_path, lambda d: d['steps']['author'].update(validators=['guard']))
    h = Harness(Workflow.load(path), tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']),
                validators={'guard': Validator('v1', lambda output, context: [])})
    assert h.run({})['status'] == 'waiting'
    h.validators['guard'] = Validator('v2', lambda output, context: [])
    with pytest.raises(ValueError):
        h.resume(choice='approve') if boundary == 'resume' else h.status()


def edit_flow(tmp_path, change):
    import yaml
    path = tmp_path / 'flow.yml'
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data))
    return path


def test_concurrent_writer_is_rejected(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    with locked(tmp_path / 'run'):
        with pytest.raises(ValueError, match='locked'):
            Harness(flow, tmp_path / 'run', runtime=FakeRuntime([])).run({})


@pytest.mark.parametrize('change,match', [
    (lambda d: d['steps']['author'].update(next='unknown'), 'target'),
    (lambda d: d['steps']['author'].update(tools=['write_file'], read_roots=['.']), 'read tools'),
    (lambda d: d.update(runtime='../outside.yml'), 'escapes'),
    (lambda d: d['limits'].update(max_calls=0), 'positive'),
])
def test_invalid_definition_rejected_before_execution(tmp_path, monkeypatch, change, match):
    setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match=match):
        Workflow.load(edit_flow(tmp_path, change))


def test_remote_schema_reference_is_rejected(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    (tmp_path / 'result.json').write_text('{"$ref":"https://example.com/schema"}')
    with pytest.raises(ValueError, match='internal'):
        Workflow.load(tmp_path / 'flow.yml')


def test_duplicate_yaml_keys_are_rejected(tmp_path):
    path = tmp_path / 'flow.yml'
    path.write_text('version: 1\nversion: 2\n')
    with pytest.raises(ValueError, match='duplicate'):
        Workflow.load(path)


def test_attempt_limit_does_not_resume_with_extra_calls(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    runtime = FakeRuntime(['bad JSON', 'bad JSON'])
    h = Harness(flow, tmp_path / 'run', runtime=runtime)
    assert h.run({})['reason'] == 'attempt_limit'
    assert h.resume()['reason'] == 'attempt_limit' and len(runtime.calls) == 2


def test_only_declared_artifacts_are_passed_to_agent(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    def change(d):
        d['steps']['author']['next'] = 'second'
        d['steps']['second'] = {'kind': 'agent', 'agent': 'subagents/second.md', 'schema': 'result.json', 'next': 'done'}
    flow = Workflow.load(edit_flow(tmp_path, change))
    runtime = FakeRuntime(['{"approved":true}', '{"approved":true}'])
    Harness(flow, tmp_path / 'run', runtime=runtime).run({'task': 'shared'})
    assert runtime.calls[1][1]['artifacts'] == {}
    assert runtime.calls[1][1]['request'] == {'task': 'shared'}


def test_nonfinite_json_is_invalid(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    runtime = FakeRuntime(['{"approved": NaN}', '{"approved":true}'])
    assert Harness(flow, tmp_path / 'run', runtime=runtime).run({})['status'] == 'completed'
    assert runtime.calls[1][1]['validation_feedback']


def test_fenced_json_is_accepted(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    state = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['```json\n{"approved":true}\n```'])).run({})
    assert state['status'] == 'completed'


def test_cli_status_needs_no_prosaic_or_credentials(tmp_path):
    (tmp_path / 'run.json').write_text(json.dumps({'status': 'waiting', 'current': 'human', 'calls': 1,
        'reason': None, 'outputs': {}, 'question': 'Approve?', 'choices': ['yes']}))
    p = subprocess.run([sys.executable, '-m', 'prosaic_harness.cli', 'status', '--run-dir', str(tmp_path), '--json'],
                       capture_output=True, text=True)
    assert p.returncode == 0 and json.loads(p.stdout)['status'] == 'waiting'


def test_missing_fields_and_invalid_schema_report_configuration_error(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    path = edit_flow(tmp_path, lambda d: d['steps']['author'].pop('schema'))
    with pytest.raises(ValueError, match='definition'):
        Workflow.load(path)
    edit_flow(tmp_path, lambda d: d['steps']['author'].update(schema='result.json'))
    (tmp_path / 'result.json').write_text('{"type": "wrong"}')
    with pytest.raises(ValueError, match='definition'):
        Workflow.load(tmp_path / 'flow.yml')
