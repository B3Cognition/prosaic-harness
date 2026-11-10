import json
import pytest
from prosaic_harness import Harness
from test_workflow_rules_execution import rule_endpoint
from test_tool_contract_workflow import flow, controller, queue_answer, yaml_flow


@pytest.mark.parametrize('pack', [False, True])
def test_saved_workflow_receipt_adopts_without_new_execution(rule_endpoint, tmp_path, monkeypatch, pack):
    cfg, requests, replies = rule_endpoint
    calls, checks, events = [], [], []
    workflow = flow(cfg, calls=calls, checks=checks, pack=pack)
    queue_answer(replies, pack=pack)
    harness = controller(workflow, tmp_path, on_event=events.append)
    monkeypatch.setattr(harness, '_accept', lambda *args: (_ for _ in ()).throw(OSError('crash after receipt')))
    with pytest.raises(OSError): harness.run({'task': 'Review', 'private': 'PRIVATE-FACT'})
    before = (len(requests), len(calls), len(checks))
    assert before == (2, 1, 1)
    state = Harness(workflow, store=harness.store, run_id='a' * 32).resume()
    assert state['status'] == 'completed' and (len(requests), len(calls), len(checks)) == before
    receipt = harness.store.load_receipt(state['run_id'], state['invocations'][0]['id'])
    assert receipt['version'] == 3 and receipt['toolContractV1']['citations']['markers']
    if pack:
        assert 'PRIVATE-FACT' not in json.dumps(requests)
    tool_events = [event for event in events if event['event'] in {'tool_started', 'tool_completed'}]
    assert len(tool_events) == 2 and tool_events[0]['call_id'] == tool_events[1]['call_id']
    assert all(event['step'] == 'review' and event['attempt_id'] == receipt['id'] for event in tool_events)


def test_unknown_delivery_cannot_be_recovered_from_events(rule_endpoint, tmp_path, monkeypatch):
    cfg, requests, replies = rule_endpoint
    calls = []
    workflow = flow(cfg, calls=calls)
    queue_answer(replies)
    harness = controller(workflow, tmp_path)
    save = harness.store.save_receipt
    monkeypatch.setattr(harness.store, 'save_receipt', lambda *args: (_ for _ in ()).throw(OSError('lost receipt')))
    with pytest.raises(OSError): harness.run({'task': 'Review'})
    monkeypatch.setattr(harness.store, 'save_receipt', save)
    before = len(requests), len(calls)
    state = Harness(workflow, store=harness.store, run_id='a' * 32).resume()
    assert state['reason'] == 'interrupted_call' and (len(requests), len(calls)) == before == (2, 1)


def test_corrupt_sidecar_blocks_adoption(rule_endpoint, tmp_path, monkeypatch):
    from prosaic_harness.contracts import seal
    cfg, requests, replies = rule_endpoint
    workflow = flow(cfg)
    queue_answer(replies)
    harness = controller(workflow, tmp_path)
    monkeypatch.setattr(harness, '_accept', lambda *args: (_ for _ in ()).throw(OSError('crash')))
    with pytest.raises(OSError): harness.run({'task': 'Review'})
    load = harness.store.load_receipt
    def corrupt(*args):
        receipt = load(*args)
        receipt['toolContractV1']['citations']['answerSha256'] = '0' * 64
        return seal(receipt)
    monkeypatch.setattr(harness.store, 'load_receipt', corrupt)
    with pytest.raises(ValueError): Harness(workflow, store=harness.store, run_id='a' * 32).resume()
    assert len(requests) == 2


@pytest.mark.parametrize('pack', [False, True])
def test_prepared_undispatched_input_resumes_without_reassembly(rule_endpoint, tmp_path, monkeypatch, pack):
    cfg, requests, replies = rule_endpoint
    calls = []
    workflow = flow(cfg, calls=calls, pack=pack)
    queue_answer(replies, pack=pack)
    harness = controller(workflow, tmp_path)
    monkeypatch.setattr(harness.runtime, 'turn', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('crash before admission')))
    with pytest.raises(OSError): harness.run({'task': 'Review'})
    assert not requests and not calls
    restored = Harness(workflow, store=harness.store, run_id='a' * 32).resume()
    assert restored['status'] == 'completed' and restored['calls'] == 1 and len(requests) == 2 and calls == [1]


def test_acknowledged_pack_retry_rebinds_scope_without_source_capture(rule_endpoint, tmp_path, monkeypatch):
    from prosaic_harness import ContextPacker
    cfg, requests, replies = rule_endpoint
    calls = []
    workflow = yaml_flow(cfg,tmp_path,calls=calls)
    queue_answer(replies, pack=True)
    harness = controller(workflow, tmp_path)
    save = harness.store.save_receipt
    monkeypatch.setattr(harness.store, 'save_receipt', lambda *args: (_ for _ in ()).throw(OSError('lost acknowledgment')))
    with pytest.raises(OSError): harness.run({'task': 'Review', 'private': 'PRIVATE-FACT'})
    monkeypatch.setattr(harness.store, 'save_receipt', save)
    fresh = Harness(workflow, store=harness.store, run_id='a' * 32)
    pending = fresh.resume()
    assert pending['reason'] == 'interrupted_call' and len(requests) == 2
    old_id = pending['pending']['id']
    monkeypatch.setattr(ContextPacker, 'compose', lambda *args, **kwargs: pytest.fail('recaptured source'))
    queue_answer(replies, pack=True)
    state = fresh.resume(retry_interrupted=True, expected_revision=fresh.status().revision)
    assert state['status'] == 'completed' and len(requests) == 4 and len(calls) == 2, (state['reason'], state['calls'], len(requests))
    new_id = state['invocations'][-1]['id']
    old = state['contextPacks']['attempts'][old_id]
    current = state['contextPacks']['attempts'][new_id]
    assert old_id != new_id and current['executionEpoch'] == old['executionEpoch'] + 1
    assert old['selectedPackReference'] == current['selectedPackReference']
    assert old['frozenInput']['contextIdentity'] != current['frozenInput']['contextIdentity']
