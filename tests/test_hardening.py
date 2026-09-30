"""Regression contracts: damaged recovery, stale approvals, evidence and budgets."""
import json
from dataclasses import replace

import pytest
from prosaic_harness import Harness, Workflow
from prosaic_harness.store import write_json
from test_harness import setup, FakeRuntime
from test_validation import edit_flow


@pytest.mark.parametrize('damage', ['calls', 'output', 'pending', 'duplicate'])
def test_damaged_checkpoint_is_rejected_without_dispatch(tmp_path, monkeypatch, damage):
    flow = setup(tmp_path, monkeypatch, pause=True)
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']))
    h.run({})
    path = tmp_path / 'run/run.json'
    data = json.loads(path.read_text())
    if damage == 'calls':
        data['calls'] = -1
    elif damage == 'output':
        data['outputs']['author']['approved'] = False
    elif damage == 'pending':
        data['pending'] = {'id': '../elsewhere', 'arguments_sha256': 'bad'}
    else:
        path.write_text('{"version":1,"version":2}')
    if damage != 'duplicate':
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        h.resume(choice='approve')


def test_modified_receipt_arguments_not_adopted(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']))
    monkeypatch.setattr(h, '_accept', lambda *a: (_ for _ in ()).throw(OSError('crash')))
    with pytest.raises(OSError):
        h.run({'task': 'original'})
    path = next((tmp_path / 'run/attempts').glob('*.json'))
    receipt = json.loads(path.read_text())
    receipt['arguments']['request'] = {'task': 'foreign'}
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        Harness(flow, tmp_path / 'run', runtime=FakeRuntime([])).resume()


def test_symlinked_store_does_not_write_outside_run(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (tmp_path / 'escape').symlink_to(outside, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        write_json(tmp_path / 'escape/run.json', {'bad': True})
    assert not (outside / 'run.json').exists()


def test_changed_evidence_blocks_human_approval(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, pause=True)
    (tmp_path / 'source.md').write_text('S1: Original evidence.')
    flow = Workflow.load(edit_flow(tmp_path, lambda d: d.update(evidence=['source.md'])))
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']))
    assert h.run({})['status'] == 'waiting'
    (tmp_path / 'source.md').write_text('S1: Changed evidence.')
    with pytest.raises(ValueError, match='evidence|changed'):
        h.resume(choice='approve')


def test_token_budget_counts_failed_validation(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    flow = Workflow.load(edit_flow(tmp_path, lambda d: d['limits'].update(max_tokens=5)))
    state = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['bad', '{"approved":true}'])).run({})
    assert state['reason'] == 'token_limit' and state['calls'] == 1


def test_unknown_usage_is_not_zero_with_finite_budget(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    flow = Workflow.load(edit_flow(tmp_path, lambda d: d['limits'].update(max_tokens=100)))
    class Unknown(FakeRuntime):
        def run(self, *args, **kwargs):
            return replace(super().run(*args, **kwargs), token_usage=None)
    state = Harness(flow, tmp_path / 'run', runtime=Unknown(['{"approved":true}'])).run({})
    assert state['status'] == 'blocked' and state['reason'] == 'usage_unknown'


def test_cancel_before_dispatch_is_durable(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime([]), cancelled=lambda: True)
    assert h.run({})['reason'] == 'cancelled'
    assert h.resume()['reason'] == 'cancelled'


def test_ignored_initial_tool_choice_blocks_without_output_or_retry(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    class Refused(FakeRuntime):
        def run(self, *args, **kwargs):
            return replace(super().run(*args, **kwargs), exit_code=1, stdout='',
                           metadata={'failure_reason': 'tool_choice_not_honored'})
    runtime = Refused(['{"approved":true}'])
    harness = Harness(flow, tmp_path / 'run', runtime=runtime)
    state = harness.run({})
    assert state['status'] == 'blocked' and state['reason'] == 'tool_choice_not_honored'
    assert state['outputs'] == {} and state['calls'] == 1
    assert harness.resume()['reason'] == 'tool_choice_not_honored'
    assert len(runtime.calls) == 1


def test_whole_run_deadline_survives_pause(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, pause=True)
    flow = Workflow.load(edit_flow(tmp_path, lambda d: d['limits'].update(max_run_s=10)))
    now = [100.0]
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']), clock=lambda: now[0])
    assert h.run({})['status'] == 'waiting'
    now[0] = 111
    assert h.resume(choice='approve')['reason'] == 'run_deadline'


def test_stale_review_cannot_gate_a_changed_artifact(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    def change(d):
        d['steps']['author']['next'] = 'choose'
        d['steps']['choose'] = {'kind': 'gate', 'from': 'author', 'field': ['approved'],
            'equals': True, 'pass': 'critic', 'fail': 'oldgate'}
        d['steps']['critic'] = {'kind': 'agent', 'agent': 'subagents/critic.md', 'schema': 'result.json',
                                'inputs': ['author'], 'next': 'revision'}
        d['steps']['oldgate'] = {'kind': 'gate', 'from': 'critic', 'field': ['approved'], 'equals': True,
                                'pass': 'done', 'fail': 'rejected'}
        # Revisit author after review, without refreshing the critic.
        d['steps']['revision'] = {'kind': 'gate', 'from': 'author', 'field': ['approved'], 'equals': True,
                                  'pass': 'author', 'fail': 'oldgate'}
    flow = Workflow.load(edit_flow(tmp_path, change))
    state = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}', '{"approved":true}', '{"approved":false}'])).run({})
    assert state['status'] == 'blocked' and state['reason'] == 'stale_artifact'


def test_trusted_validator_retries_semantic_failure(tmp_path, monkeypatch):
    from prosaic_harness import Validator
    setup(tmp_path, monkeypatch)
    flow = Workflow.load(edit_flow(tmp_path, lambda d: d['steps']['author'].update(validators=['policy'])))
    check = Validator('v1', lambda output, context: [] if output['approved'] else ['unsupported claim'])
    state = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":false}', '{"approved":true}']),
                    validators={'policy': check}).run({})
    assert state['status'] == 'completed' and state['calls'] == 2


def test_final_check_rejects_model_approved_bad_output(tmp_path, monkeypatch):
    from prosaic_harness import Validator
    setup(tmp_path, monkeypatch)
    def change(d):
        d['steps']['review']['pass'] = 'fact_check'
        d['steps']['fact_check'] = {'kind': 'check', 'from': 'author', 'validators': ['facts'],
                                   'pass': 'done', 'fail': 'rejected'}
    flow = Workflow.load(edit_flow(tmp_path, change))
    check = Validator('v1', lambda o, c: ['bad denominator'])
    state = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']), validators={'facts': check}).run({})
    assert state['status'] == 'rejected' and state['calls'] == 1
