"""Recomputed checksums do not replace structural and causal admission."""
import json
import pytest
from prosaic_harness import Harness, Validator
from prosaic_harness.contracts import seal
from prosaic_harness.store import write_json
from test_harness import setup, FakeRuntime
from test_validation import edit_flow
from prosaic_harness import Workflow


@pytest.mark.parametrize('damage', ['status', 'attempt', 'history', 'binding', 'receipt'])
def test_resealed_inconsistent_state_cannot_resume(tmp_path, monkeypatch, damage):
    flow = setup(tmp_path, monkeypatch, pause=True)
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']))
    state = h.run({})
    if damage == 'status':
        state['status'] = 'completed'  # Current step is still the human pause.
    elif damage == 'attempt':
        state['attempt'] = 1000
    elif damage == 'history':
        state['history'][0]['sequence'] = 999
    elif damage == 'binding':
        state['bindings']['author']['dependencies'] = {'author': state['bindings']['author'].copy()}
    else:
        path = next((tmp_path / 'run/attempts').glob('*.json'))
        receipt = json.loads(path.read_text())
        receipt['result']['stdout'] = '{"approved":false}'
        write_json(path, seal(receipt))
    write_json(tmp_path / 'run/run.json', seal(state))
    with pytest.raises(ValueError):
        h.resume()


@pytest.mark.parametrize('edge', ['pending', 'receipt', 'transition', 'finish'])
def test_each_durable_edge_can_recover_without_silent_extra_call(tmp_path, monkeypatch, edge):
    flow = setup(tmp_path, monkeypatch)
    runtime = FakeRuntime(['{"approved":true}'])
    h = Harness(flow, tmp_path / 'run', runtime=runtime)
    original = h._save
    def crash_after_save(state):
        original(state)
        target = {'pending': state['pending'] is not None,
                  'receipt': bool(state['invocations']) and state['invocations'][-1]['status'] == 'complete',
                  'transition': state['current'] == 'review', 'finish': state['status'] == 'completed'}[edge]
        if target:
            raise OSError('injected process death')
    monkeypatch.setattr(h, '_save', crash_after_save)
    with pytest.raises(OSError):
        h.run({})
    monkeypatch.setattr(h, '_save', original)
    recovered = h.resume()
    assert recovered['status'] == ('blocked' if edge == 'pending' else 'completed')
    assert recovered['calls'] == 1
    if edge == 'pending':
        assert recovered['reason'] == 'interrupted_call' and not recovered['outputs']
    else:
        assert recovered['outputs'] == {'author': {'approved': True}}


def test_changed_validator_version_cannot_resume(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, pause=True)
    flow = Workflow.load(edit_flow(tmp_path, lambda d: d['steps']['author'].update(validators=['guard'])))
    Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']),
            validators={'guard': Validator('v1', lambda o, c: [])}).run({})
    with pytest.raises(ValueError, match='changed'):
        Harness(flow, tmp_path / 'run', validators={'guard': Validator('v2', lambda o, c: [])}).resume()


def test_validator_crash_is_not_a_pass_or_model_retry(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    flow = Workflow.load(edit_flow(tmp_path, lambda d: d['steps']['author'].update(validators=['guard'])))
    def broken(output, context):
        raise RuntimeError('bug in trusted policy')
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']), validators={'guard': Validator('v1', broken)})
    state = h.run({})
    assert state['reason'] == 'validator_error' and not state['outputs']
    assert h.resume()['calls'] == 1
