"""Guard receipts are required for adoption, not authority to retry a lost call."""
import json
import pytest
from prosaic_harness import Harness
from prosaic_harness.contracts import seal
from prosaic_harness.store import write_json
from test_workflow_rules_admission import factory, definition, guard
from test_workflow_rules_execution import rule_endpoint, strict


@pytest.mark.parametrize('accepted', [True, False])
def test_saved_guard_receipt_recovers_without_dispatch(rule_endpoint, tmp_path, monkeypatch, accepted):
    cfg, requests, replies = rule_endpoint
    replies.extend([json.dumps({'ok': accepted})] * 2)
    flow = factory(cfg=cfg, registered=[guard(check=strict)]).build(definition())
    h = Harness(flow, tmp_path / 'run')
    def crash(*args): raise OSError('after durable receipt')
    monkeypatch.setattr(h, '_accept', crash)
    with pytest.raises(OSError): h.run({})
    count = len(requests)
    evidence = Harness(flow, tmp_path / 'run').recovery_evidence()
    assert evidence['recoveryStatus'] == 'receiptAvailable'
    state = Harness(flow, tmp_path / 'run').resume()
    assert state['status'] == ('completed' if accepted else 'blocked')
    assert state['pending'] is None and state['calls'] == 1 and len(requests) == count
    if not accepted: assert state['reason'] == 'rule_violation'


@pytest.mark.parametrize('damage', ['missing', 'facts', 'context', 'fingerprint', 'coverage', 'extra', 'outcome'])
def test_resealed_invalid_guard_proof_cannot_advance(rule_endpoint, tmp_path, monkeypatch, damage):
    cfg, requests, replies = rule_endpoint; replies.append('{"ok":true}')
    flow = factory(cfg=cfg, registered=[guard(check=strict)]).build(definition())
    h = Harness(flow, tmp_path / 'run')
    def crash(*args): raise OSError('after durable receipt')
    monkeypatch.setattr(h, '_accept', crash)
    with pytest.raises(OSError): h.run({})
    path = next((tmp_path / 'run/attempts').glob('*.json'))
    receipt = json.loads(path.read_text()); metadata = receipt['result']['metadata']
    proof = metadata['workflow_rules_v1']
    if damage == 'missing': del metadata['workflow_rules_v1']
    elif damage == 'facts': proof['facts_sha256'] = '0' * 64
    elif damage == 'context': proof['context_identity'] = True
    elif damage == 'fingerprint': proof['rules']['fingerprint'] = '0' * 64
    elif damage == 'coverage': proof['rules']['evaluated'] = []
    elif damage == 'extra': proof['extra'] = 'forged'
    else: proof['rules']['violated'] = ['not-evaluated']
    write_json(path, seal(receipt))
    with pytest.raises(ValueError): Harness(flow, tmp_path / 'run').resume()
    assert len(requests) == 1


def test_lost_guard_receipt_requires_explicit_interrupted_retry(rule_endpoint, tmp_path, monkeypatch):
    cfg, requests, replies = rule_endpoint; replies.extend(['{"ok":true}'] * 2)
    flow = factory(cfg=cfg, registered=[guard(check=strict)]).build(definition())
    h = Harness(flow, tmp_path / 'run')
    def crash(*args): raise OSError('provider completed, receipt not saved')
    monkeypatch.setattr(h.store, 'save_receipt', crash)
    with pytest.raises(OSError): h.run({})
    fresh = Harness(flow, tmp_path / 'run')
    state = fresh.resume()
    assert state['reason'] == 'interrupted_call' and state['calls'] == 1 and len(requests) == 1
    # Consent does not manufacture missing usage under the native token cap.
    assert fresh.resume(retry_interrupted=True)['reason'] == 'usage_unknown' and len(requests) == 1


def test_guard_metadata_survives_bounded_event_failure(rule_endpoint, tmp_path, monkeypatch):
    cfg, requests, replies = rule_endpoint; replies.append('{"ok":true}')
    flow = factory(cfg=cfg, registered=[guard(check=strict)]).build(definition())
    h = Harness(flow, tmp_path / 'run'); original = h._receipt
    def oversized(state, aid, name, arguments, result, events, failure):
        return original(state, aid, name, arguments, result, events, 'event_limit')
    monkeypatch.setattr(h, '_receipt', oversized)
    state = h.run({})
    assert state['reason'] == 'event_limit' and state['pending'] is None
    receipt = h.store.load_receipt('legacy', state['invocations'][0]['id'])
    assert receipt['result']['metadata']['workflow_rules_v1']['rules']['evaluated']
    assert receipt['result']['token_usage'] == 5 and len(requests) == 1
