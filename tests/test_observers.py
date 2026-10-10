"""Optional observation cannot change durable workflow evidence."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from prosaic_harness import Harness, StoreUnavailable
from prosaic_runtime import InvocationScope
from test_native_execution import bound
from test_custom_tools import blueprint, call, tools
from test_transport import endpoint, text
from prosaic_harness import Workflow


def raising_observer(record):
    raise RuntimeError('PRIVATE observer failure')


def test_waiting_commit_survives_observer_failure(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch,
                     harness_options={'observer': raising_observer})
    assert h.run({'private_input': 'PRIVATE'})['status'] == 'waiting'
    before = h.status()
    assert h.resume(choice='accept', expected_revision=before.revision)['status'] == 'completed'
    assert len(calls) == 1


def test_observer_reads_the_committed_revision_and_private_data_stays_private(tmp_path, monkeypatch):
    records = []
    revisions = []
    statuses = []
    def observe(record):
        snapshot = h.status()
        revisions.append(snapshot.revision)
        statuses.append(snapshot.state['status'])
        records.append(record)
    h, calls = bound(tmp_path, monkeypatch, harness_options={'observer': observe})
    state = h.run({'private_input': 'PRIVATE'})
    before = h.status()
    assert state['status'] == 'waiting'
    assert h.resume(choice='accept', expected_revision=before.revision)['status'] == 'completed'
    assert [r['revision'] for r in records] == revisions
    assert [r['outcome'] for r in records] == statuses
    assert records[0]['event'] == 'run_started'
    assert records[0]['calls'] == 0
    assert records[-1]['event'] == 'run_completed'
    assert records[-1]['calls'] == 1
    waiting = next(r for r in records if r['event'] == 'waiting_committed')
    assert waiting['revision'] == before.revision
    assert waiting['outcome'] == 'waiting'
    assert all(r['source'] == 'harness' and r['version'] == 1 for r in records)
    assert len({r['invocation_id'] for r in records}) == 2
    for invocation in {r['invocation_id'] for r in records}:
        assert [r['sequence'] for r in records if r['invocation_id'] == invocation] == list(
            range(1, 1 + sum(r['invocation_id'] == invocation for r in records)))
    assert {r['run_id'] for r in records} == {before.state['run_id']}
    encoded = json.dumps(records)
    assert 'PRIVATE' not in encoded and str(tmp_path) not in encoded
    assert 'lookup_entity' not in encoded and 'found' not in encoded
    allowed = {'version', 'sequence', 'source', 'event', 'invocation_id', 'run_id',
               'revision', 'outcome', 'reason', 'calls'}
    assert all(set(r) <= allowed and len(json.dumps(r).encode()) <= 4096 for r in records)
    options = calls[0][1]
    assert options['observer'] is observe
    assert type(options['operation_context']) is InvocationScope
    assert options['operation_context'].invocation_id == before.state['invocations'][0]['id']
    assert options['operation_context'].run_id == before.state['run_id']
    assert options['operation_context'].step_id == 'find'


def test_observer_mutation_cannot_change_state_or_later_records(tmp_path, monkeypatch):
    received = []
    def mutate(record):
        received.append(dict(record))
        record.clear()
        record['inputs'] = {'injected': True}
    h, calls = bound(tmp_path, monkeypatch, harness_options={'observer': mutate})
    assert h.run({'private_input': 'PRIVATE'})['status'] == 'waiting'
    before = h.status()
    assert before.state['inputs'] == {'private_input': 'PRIVATE'}
    assert before.state['invocations'][0]['status'] == 'complete'
    assert received[-1]['event'] == 'waiting_committed'
    assert all(r['run_id'] == before.state['run_id'] for r in received)
    assert h.resume(choice='accept')['status'] == 'completed'
    assert received[-1]['event'] == 'run_completed' and len(calls) == 1


@pytest.mark.parametrize('exception', [KeyboardInterrupt, SystemExit])
def test_process_control_observer_exception_propagates_after_commit(tmp_path, monkeypatch, exception):
    def observe(record):
        raise exception()
    h, calls = bound(tmp_path, monkeypatch, harness_options={'observer': observe})
    with pytest.raises(exception):
        h.run({})
    assert h.status().state['status'] == 'running'
    assert h.status().state['calls'] == 0 and calls == []


def test_critical_runtime_evidence_hook_still_propagates(tmp_path, monkeypatch):
    def critical(event):
        if event['event'] == 'tool_completed':
            raise RuntimeError('critical evidence failed')
    h, calls = bound(tmp_path, monkeypatch,
                     harness_options={'observer': raising_observer, 'on_event': critical})
    with pytest.raises(RuntimeError, match='critical evidence failed'):
        h.run({})
    assert h.status().state['pending'] is not None
    assert h.resume()['reason'] == 'interrupted_call' and len(calls) == 1


def test_observer_failure_on_receipt_recovery_does_not_redispatch(tmp_path, monkeypatch):
    records = []
    recovered_revisions = []
    def observe(record):
        records.append(record)
        if record['event'] == 'recovery_committed':
            recovered_revisions.append(h.status().revision)
            raise RuntimeError('PRIVATE recovery monitor failure')
    h, calls = bound(tmp_path, monkeypatch, harness_options={'observer': observe})
    accept = h._accept
    def crash(*args, **kwargs):
        raise OSError('crash after receipt')
    monkeypatch.setattr(h, '_accept', crash)
    with pytest.raises(OSError, match='crash after receipt'):
        h.run({})
    assert h.status().state['pending'] is not None
    records.clear()
    monkeypatch.setattr(h, '_accept', accept)
    assert h.resume()['status'] == 'waiting' and len(calls) == 1
    assert records[0]['event'] == 'recovery_committed'
    assert records[0]['calls'] == 1
    assert recovered_revisions == [records[0]['revision']]
    assert records[-1]['event'] == 'waiting_committed'
    assert h.status().state['invocations'][0]['status'] == 'complete'


@pytest.mark.parametrize('boundary', ['create_run', 'save_run'])
def test_failed_store_commit_emits_no_observation(tmp_path, monkeypatch, boundary):
    records = []
    h, calls = bound(tmp_path, monkeypatch, harness_options={'observer': records.append})
    def fail(*args):
        raise StoreUnavailable()
    monkeypatch.setattr(h.store, boundary, fail)
    with pytest.raises(StoreUnavailable):
        h.run({})
    assert len(records) == (0 if boundary == 'create_run' else 1)
    assert calls == []
    if records:
        assert records[0]['event'] == 'run_started'
        assert h.status().revision == records[0]['revision']


def test_concurrent_harness_instances_have_separate_sequences_and_scopes(tmp_path, monkeypatch):
    first, second = [], []
    a, _ = bound(tmp_path / 'a', monkeypatch, harness_options={'observer': first.append})
    b, _ = bound(tmp_path / 'b', monkeypatch, harness_options={'observer': second.append})
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(h.run, {}) for h in (a, b)]
        assert [future.result()['status'] for future in futures] == ['waiting', 'waiting']
    assert len({r['invocation_id'] for r in first + second}) == 2
    assert {r['run_id'] for r in first}.isdisjoint({r['run_id'] for r in second})
    assert [r['sequence'] for r in first] == list(range(1, len(first) + 1))
    assert [r['sequence'] for r in second] == list(range(1, len(second) + 1))


def test_configured_observer_requires_runtime_capability_before_storage(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch)
    h.runtime.capabilities = h.runtime.capabilities - {'observer_v1'}
    with pytest.raises(ValueError, match='observer_v1'):
        Harness(h.workflow, tmp_path / 'observed', runtime=h.runtime, observer=raising_observer)
    assert not (tmp_path / 'observed').exists() and calls == []


def test_removed_runtime_observation_capability_cannot_silently_drop_observer(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch, harness_options={'observer': raising_observer})
    h.runtime.capabilities = h.runtime.capabilities - {'observer_v1'}
    with pytest.raises(ValueError, match='observer_v1'):
        h.run({})
    assert not (tmp_path / 'run').exists() and calls == []


def test_unconfigured_observer_preserves_legacy_runtime_options(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch)
    assert h.run({})['status'] == 'waiting'
    assert 'observer' not in calls[0][1] and 'operation_context' not in calls[0][1]


def test_critical_waiting_hook_still_propagates_before_commit(tmp_path, monkeypatch):
    records = []
    def critical(event):
        if event['event'] == 'waiting':
            raise RuntimeError('critical pause failed')
    h, calls = bound(tmp_path, monkeypatch,
                     harness_options={'observer': records.append, 'on_event': critical})
    with pytest.raises(RuntimeError, match='critical pause failed'):
        h.run({})
    assert h.status().state['status'] == 'running'
    assert not any(r['event'] == 'waiting_committed' for r in records)
    assert len(calls) == 1


def test_real_runtime_observations_share_persisted_attempt_scope_and_keep_receipts(endpoint, tmp_path):
    url, requests, replies = endpoint
    replies.extend([call(), text({'found': True})])
    records = []
    def observe(record):
        records.append(record)
        raise RuntimeError('PRIVATE optional monitor failed')
    workflow = Workflow.load(blueprint(tmp_path, url), custom_tools=tools())
    h = Harness(workflow, tmp_path / 'run', observer=observe)
    assert h.run({'private_input': 'PRIVATE'})['status'] == 'waiting'
    before = h.status()
    attempt = before.state['invocations'][0]['id']
    runtime_records = [r for r in records if r['source'] == 'runtime']
    assert runtime_records[0]['event'] == 'invocation_started'
    assert runtime_records[-1]['event'] == 'invocation_completed'
    assert runtime_records[-1]['outcome'] == 'completed'
    assert sum(r['event'] == 'invocation_completed' for r in runtime_records) == 1
    assert {r['invocation_id'] for r in runtime_records} == {attempt}
    assert {r['run_id'] for r in runtime_records} == {before.state['run_id']}
    assert all('step_id' not in r for r in runtime_records)  # Legacy step names are private.
    assert h.resume(choice='reject')['status'] == 'rejected' and len(requests) == 2
    receipt = json.loads(next((tmp_path / 'run/attempts').glob('*.json')).read_text())
    assert any(e.get('tool_version') == 'v1' and e.get('status') == 'ok' for e in receipt['events'])
    encoded = json.dumps(records)
    assert 'PRIVATE' not in encoded and url not in encoded and str(tmp_path) not in encoded
