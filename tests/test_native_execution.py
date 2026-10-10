"""Admission and durable bounds at every public execution boundary."""
from dataclasses import replace
import json
from pathlib import Path

import pytest
from prosaic_runtime import ProsaicRuntime, Result
from prosaic_harness import Harness, Workflow
from test_workflow_factory import api, factory, graph, agent, config, tools


def bound(tmp_path, monkeypatch, *, proposal=None, reply=None, **caps):
    workflow = factory(**caps).build(proposal or graph())
    runtime = ProsaicRuntime(workflow.config, custom_tools=tools())
    calls = []
    def run(artifact, arguments, **kwargs):
        calls.append((arguments, kwargs))
        assert Path(kwargs['cwd']).is_dir()
        assert list(Path(kwargs['cwd']).iterdir()) == []
        kwargs['on_event']({'event': 'tool_completed', 'name': 'lookup_entity',
                            'status': 'ok', 'tool_version': 'v1'})
        if callable(reply):
            return reply(kwargs)
        return reply or Result(0, '{"found":true}', '', token_usage=3)
    monkeypatch.setattr(runtime, 'run', run)
    return Harness(workflow, tmp_path / 'run', runtime=runtime), calls


def test_native_run_pause_resume_private_cwd_and_cleanup(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch)
    assert h.run({'query': 'synthetic'})['status'] == 'waiting'
    directory = Path(calls[0][1]['cwd'])
    assert not directory.exists()
    assert h.resume(choice='accept')['status'] == 'completed'
    assert len(calls) == 1
    assert h.status().state['status'] == 'completed'
    assert str(directory) not in json.dumps(h.status().state)


def test_pathless_raw_workflow_cannot_execute(tmp_path):
    admitted = factory().build(graph())
    raw = Workflow(None, admitted.definition, admitted.config, admitted.artifacts,
                   admitted.schemas, admitted.fingerprint)
    with pytest.raises(ValueError):
        Harness(raw, tmp_path / 'run')
    assert not (tmp_path / 'run').exists()


@pytest.mark.parametrize('boundary', ['run', 'resume', 'status'])
def test_mutation_and_rehashed_definition_cannot_bypass_admission(tmp_path, monkeypatch, boundary):
    h, calls = bound(tmp_path, monkeypatch)
    if boundary != 'run':
        h.run({})
    h.workflow.definition['steps']['find']['tools'] = []
    with pytest.raises(ValueError):
        h.workflow.fingerprint = h.workflow.current_fingerprint()
        getattr(h, boundary)({}) if boundary == 'run' else getattr(h, boundary)()


def test_opaque_runtime_and_changed_live_config_rejected(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        Harness(h.workflow, tmp_path / 'other', runtime=object())
    h.runtime.config.profiles['local'] = replace(h.runtime.config.profiles['local'], model='changed')
    with pytest.raises(ValueError):
        h.run({})
    assert calls == []


def test_input_limit_before_storage_and_no_phantom_preparation_call(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch, max_run_input_bytes=100, max_invocation_bytes=200)
    with pytest.raises(ValueError):
        h.run({'query': 'x' * 200})
    assert not (tmp_path / 'run').exists()
    state = h.run({'query': 'x' * 70})
    assert state['status'] == 'blocked' and state['reason'] == 'invocation_limit'
    assert state['calls'] == 0 and state['pending'] is None and calls == []
    assert h.status().state['reason'] == 'invocation_limit'


@pytest.mark.parametrize('part,reason', [('stdout', 'output_limit'), ('metadata', 'metadata_limit'), ('event', 'event_limit')])
def test_oversize_result_has_failure_receipt_and_complete_ledger(tmp_path, monkeypatch, part, reason):
    def reply(options):
        if part == 'event':
            options['on_event']({'event': 'tool_completed', 'payload': 'x' * 2000})
        return Result(0, 'x' * 2000 if part == 'stdout' else '{"found":true}', '', token_usage=3,
                      metadata={'payload': 'x' * 2000} if part == 'metadata' else {})
    h, calls = bound(tmp_path, monkeypatch, reply=reply, max_output_bytes=1000,
                     max_metadata_bytes=1000, max_event_bytes=1000)
    state = h.run({})
    assert state['reason'] == reason and state['pending'] is None
    assert state['invocations'][0]['status'] == 'complete'
    assert state['invocations'][0]['token_usage'] == 3
    assert h.resume()['reason'] == reason and len(calls) == 1
    assert h.status().state['reason'] == reason


def test_failure_receipt_is_adopted_without_second_inference(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch, reply=Result(0, 'x' * 2000, '', token_usage=3), max_output_bytes=1000)
    accept = h._accept
    monkeypatch.setattr(h, '_accept', lambda *a: (_ for _ in ()).throw(OSError('crash after receipt')))
    with pytest.raises(OSError):
        h.run({})
    monkeypatch.setattr(h, '_accept', accept)
    assert h.resume()['reason'] == 'output_limit' and len(calls) == 1


def test_receipt_limit_normalizes_returned_events_and_metadata(tmp_path, monkeypatch):
    result = Result(0, '{"found":true}', '', token_usage=3, metadata={'details': 'x' * 7000})
    h, calls = bound(tmp_path, monkeypatch, reply=result, max_receipt_bytes=6000)
    state = h.run({})
    assert state['reason'] == 'receipt_limit' and state['pending'] is None
    assert state['invocations'][0]['status'] == 'complete'
    assert h.status().state['reason'] == 'receipt_limit'
    assert h.resume()['reason'] == 'receipt_limit' and len(calls) == 1


@pytest.mark.parametrize('result,reason', [
    (Result(0, '\ud800', '', token_usage=3), 'output_limit'),
    (Result(0, '{"found":true}', '', token_usage=3, cost_usd=float('inf')), 'result_limit'),
    (Result(0, '{"found":true}', '', token_usage=3, cost_usd=10**1000), 'result_limit'),
    (Result(0, '{"found":true}', '', token_usage=3, metadata=None), 'metadata_limit'),
    (Result(0, '{"found":true}', '', token_usage=3, metadata=[]), 'metadata_limit'),
    (Result(0, '{"found":true}', '', token_usage=3, metadata={'accounting_v1': None}), 'result_limit'),
])
def test_malformed_returned_result_is_durable_failure(tmp_path, monkeypatch, result, reason):
    h, calls = bound(tmp_path, monkeypatch, reply=result)
    state = h.run({})
    assert state['pending'] is None and state['reason'] == reason
    assert state['invocations'][0]['status'] == 'complete'
    assert h.resume()['reason'] == reason and len(calls) == 1


def test_schema_evaluator_failure_is_terminal_after_receipt(tmp_path, monkeypatch):
    from prosaic_harness.schema_validation import SchemaEvaluationError
    h, calls = bound(tmp_path, monkeypatch)
    monkeypatch.setattr('prosaic_harness.engine.evaluate_schema', lambda *a, **k: (_ for _ in ()).throw(SchemaEvaluationError()))
    state = h.run({})
    assert state['reason'] == 'schema_error' and state['pending'] is None
    assert state['invocations'][0]['status'] == 'complete' and len(calls) == 1
    assert h.resume()['reason'] == 'schema_error'


def test_native_marker_cannot_be_removed_to_downgrade_admission(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch)
    del h.workflow._admission
    with pytest.raises(ValueError):
        h.run({})
    assert calls == [] and not (tmp_path / 'run').exists()


def test_malformed_mutation_keeps_safe_public_admission_error(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch)
    h.workflow.definition = {'steps': 'private-sentinel'}
    with pytest.raises(api()[-1]) as caught:
        h.run({})
    assert 'private-sentinel' not in str(caught.value) and calls == []


def test_private_workspace_cleanup_on_interruption(tmp_path, monkeypatch):
    def interrupted(options):
        raise KeyboardInterrupt()
    h, calls = bound(tmp_path, monkeypatch, reply=interrupted)
    with pytest.raises(KeyboardInterrupt):
        h.run({})
    assert not Path(calls[0][1]['cwd']).exists()
    assert h.resume()['reason'] == 'interrupted_call' and len(calls) == 1


def test_schema_failure_during_adoption_preserves_deadline_precedence(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch)
    accept = h._accept
    monkeypatch.setattr(h, '_accept', lambda *a: (_ for _ in ()).throw(OSError('crash after receipt')))
    with pytest.raises(OSError):
        h.run({})
    monkeypatch.setattr(h, '_accept', accept)
    h.clock = lambda: 10**15
    assert h.resume()['reason'] == 'run_deadline'
    assert len(calls) == 1 and h.status().state['invocations'][0]['status'] == 'complete'


def test_human_response_limit_does_not_accept_decision(tmp_path, monkeypatch):
    proposal = graph()
    proposal['steps']['review']['response_schema'] = 'result'
    h, calls = bound(tmp_path, monkeypatch, proposal=proposal, max_human_response_bytes=20)
    assert h.run({})['status'] == 'waiting'
    with pytest.raises(ValueError):
        h.resume(choice='accept', response={'found': True, 'payload': 'x' * 30})
    state = h.status().state
    assert state['status'] == 'waiting'
    assert not any(event['event'] == 'human_decision' for event in state['history'])
    assert h.resume(choice='accept', response={'found': True})['status'] == 'completed'


def test_event_callback_cannot_mutate_checkpoint_or_receipt(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch)
    def mutate(event):
        event.clear()
    h.on_event = mutate
    assert h.run({})['status'] == 'waiting'
    assert h.status().state['invocations'][0]['status'] == 'complete'


def test_terminal_state_limit_retains_receipt_accounting(tmp_path, monkeypatch):
    proposal = graph()
    proposal['steps']['find']['require_tools'] = []
    proposal['steps']['find']['next'] = 'done'
    result = Result(0, json.dumps({'found': True, 'payload': 'x' * 6000}), '', token_usage=3)
    h, calls = bound(tmp_path, monkeypatch, proposal=proposal, reply=result,
                     schemas={'result': {'type': 'object'}}, max_state_bytes=7000)
    state = h.run({})
    assert state['reason'] == 'state_limit' and state['pending'] is None
    assert state['invocations'][0]['status'] == 'complete'
    assert state['outputs'] == {} and h.status().state['reason'] == 'state_limit'
    assert (tmp_path / 'run/run.json').stat().st_size <= 7000


def test_terminal_state_reserves_node_capacity_too(tmp_path, monkeypatch):
    result = Result(0, json.dumps({'found': True, 'payload': [0] * 80}), '', token_usage=3)
    h, calls = bound(tmp_path, monkeypatch, reply=result, max_json_nodes=150,
                     schemas={'result': {'type': 'object'}})
    state = h.run({})
    assert state['status'] == 'blocked' and state['reason'] == 'state_limit'
    assert state['pending'] is None and state['invocations'][0]['status'] == 'complete'
    assert h.status().state['reason'] == 'state_limit'
    assert h.resume()['reason'] == 'state_limit' and len(calls) == 1
