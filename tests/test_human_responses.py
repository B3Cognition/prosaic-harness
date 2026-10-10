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


@pytest.mark.parametrize('action,code', [
    ({'choice': 'PRIVATE'}, 'invalid_choice'),
    ({'choice': []}, 'invalid_choice'),
    ({'response': {'private': True}}, 'response_requires_choice'),
    ({'choice': 'approve', 'response': {'private': True}}, 'response_not_allowed'),
])
def test_public_response_error_is_safe_and_keeps_waiting_checkpoint(tmp_path, monkeypatch, action, code):
    from prosaic_harness import HumanResponseError
    flow = setup(tmp_path, monkeypatch, pause=True)
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']))
    h.run({})
    before = h.status()
    with pytest.raises(HumanResponseError) as caught:
        h.resume(**action)
    assert caught.value.code == code and isinstance(caught.value, ValueError)
    assert 'PRIVATE' not in json.dumps(caught.value.to_dict()) + str(caught.value)
    assert h.status() == before


def test_product_validator_runs_once_for_actual_response_and_message_stays_private(tmp_path, monkeypatch):
    from prosaic_harness import HumanResponseError
    flow = human_flow(tmp_path, monkeypatch)
    checked = []
    def check(value, context):
        checked.append(value)
        return [] if value['response']['id'] == 'known' else ['PRIVATE validator detail']
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']),
                validators={'membership': Validator('v1', check)})
    h.run({'ids': ['known']})
    before = h.status()
    assert h.interaction(include_response_schema=True) is not None and checked == []
    with pytest.raises(HumanResponseError) as caught:
        h.resume(choice='approve', response={'id': 'unknown'})
    assert caught.value.code == 'response_validation_failed'
    assert 'PRIVATE' not in str(caught.value) + json.dumps(caught.value.to_dict())
    assert h.status() == before
    assert h.resume(choice='approve', response={'id': 'known'})['status'] == 'completed'
    assert checked == [{'choice': 'approve', 'response': {'id': 'unknown'}},
                       {'choice': 'approve', 'response': {'id': 'known'}}]
    with pytest.raises(HumanResponseError) as completed:
        h.resume(choice='approve', response={'id': 'known'})
    assert completed.value.code == 'completed_run'


def test_validator_exception_becomes_safe_response_error_without_decision(tmp_path, monkeypatch):
    from prosaic_harness import HumanResponseError
    flow = human_flow(tmp_path, monkeypatch)
    def failed(value, context):
        raise RuntimeError('PRIVATE callback exception')
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']),
                validators={'membership': Validator('v1', failed)})
    h.run({})
    before = h.status()
    with pytest.raises(HumanResponseError) as caught:
        h.resume(choice='approve', response={'id': 'known'})
    assert caught.value.code == 'response_validation_failed'
    assert 'PRIVATE' not in str(caught.value) + json.dumps(caught.value.to_dict())
    assert h.status() == before
