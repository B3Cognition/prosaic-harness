import json

import pytest
import yaml

from prosaic_harness import Harness, Workflow, Validator
from test_harness import setup, FakeRuntime


def human_flow(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch, pause=True)
    raw = yaml.safe_load(flow.path.read_text())
    raw['steps']['approval'].update(response_schema='response.json', validators=['membership'])
    raw['steps']['approval']['choices']['refine'] = 'author'
    (tmp_path / 'response.json').write_text(json.dumps({
        'type': 'object', 'properties': {'id': {'type': 'string', 'maxLength': 100}},
        'required': ['id'], 'additionalProperties': False,
    }))
    flow.path.write_text(yaml.safe_dump(raw))
    return Workflow.load(flow.path)


def test_response_is_validated_before_advancing_and_survives_restart(tmp_path, monkeypatch):
    flow = human_flow(tmp_path, monkeypatch)
    seen = []
    checks = {'membership': Validator('v1', lambda value, context:
        seen.append(context.human_responses) or
        ([] if value['response']['id'] in context.request['ids'] else ['unknown option']))}
    runtime = FakeRuntime(['{"approved":true}', '{"approved":true}'])
    h = Harness(flow, tmp_path / 'run', runtime=runtime, validators=checks)
    assert h.run({'ids': ['known']})['status'] == 'waiting'
    before = h.file.read_bytes()
    for response in ({'id': 7}, {'id': 'unknown'}, {'id': 'known', 'extra': True}):
        with pytest.raises(ValueError):
            h.resume(choice='refine', response=response)
        assert h.file.read_bytes() == before
    h = Harness(flow, tmp_path / 'run', runtime=runtime, validators=checks)
    assert h.resume(choice='refine', response={'id': 'known'})['status'] == 'waiting'
    assert runtime.calls[-1][1]['human_responses']['approval'] == {
        'choice': 'refine', 'response': {'id': 'known'},
    }
    assert h.resume(choice='approve', response={'id': 'known'})['status'] == 'completed'
    assert seen[-1] == {'approval': {'choice': 'refine', 'response': {'id': 'known'}}}
    with pytest.raises(ValueError, match='completed'):
        h.resume(choice='approve', response={'id': 'known'})


def test_untyped_pause_rejects_payload(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch, pause=True)
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']))
    assert h.run({})['status'] == 'waiting'
    with pytest.raises(ValueError, match='schema'):
        h.resume(choice='approve', response={'id': 'invented'})
    assert h.resume(choice='approve')['status'] == 'completed'
