"""RunStore-backed engine must keep the controller's existing admission rules."""
import uuid

import pytest
import yaml
from prosaic_harness import Harness, Workflow, FileRunStore, RevisionConflict, LeaseLost
from test_harness import setup, FakeRuntime


def harness(tmp_path, monkeypatch, *, pause=True, replies=None):
    flow = setup(tmp_path, monkeypatch, pause=pause)
    runtime = FakeRuntime(replies or ['{"approved":true}'])
    store = FileRunStore(tmp_path / 'storage', namespace='app')
    return Harness(flow, store=store, run_id=uuid.uuid4().hex, runtime=runtime), runtime


def test_external_decision_requires_current_revision(tmp_path, monkeypatch):
    h, runtime = harness(tmp_path, monkeypatch)
    assert h.run({'task': 'draft'})['status'] == 'waiting'
    snapshot = h.status()
    with pytest.raises(ValueError, match='expected_revision'):
        h.resume(choice='approve')
    with pytest.raises(RevisionConflict):
        h.resume(choice='approve', expected_revision='stale')
    assert h.status().revision == snapshot.revision
    assert h.resume(choice='approve', expected_revision=snapshot.revision)['status'] == 'completed'
    assert len(runtime.calls) == 1
    assert not (tmp_path / 'run.json').exists()


def test_old_approval_cannot_approve_a_later_pause(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch, pause=True)
    raw = yaml.safe_load(flow.path.read_text())
    raw['steps']['approval']['choices']['approve'] = 'second'
    raw['steps']['second'] = {'kind': 'pause', 'question': 'Another decision?',
                              'choices': {'approve': 'done', 'reject': 'rejected'}}
    flow.path.write_text(yaml.safe_dump(raw))
    runtime = FakeRuntime(['{"approved":true}'])
    h = Harness(Workflow.load(flow.path), store=FileRunStore(tmp_path / 'storage'),
                run_id=uuid.uuid4().hex, runtime=runtime)
    h.run({})
    old = h.status().revision
    assert h.resume(choice='approve', expected_revision=old)['current'] == 'second'
    current = h.status()
    with pytest.raises(RevisionConflict):
        h.resume(choice='approve', expected_revision=old)
    assert h.status().revision == current.revision
    assert h.resume(choice='approve', expected_revision=current.revision)['status'] == 'completed'
    assert len(runtime.calls) == 1


def test_legacy_revision_opt_in_and_status_are_read_only(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch, pause=True)
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']))
    h.run({})
    before = h.file.read_bytes()
    snapshot = h.status()
    assert h.file.read_bytes() == before
    with pytest.raises(RevisionConflict):
        h.resume(choice='approve', expected_revision='stale')
    assert h.resume(choice='approve', expected_revision=snapshot.revision)['status'] == 'completed'


def test_interrupted_external_retry_requires_fresh_consent(tmp_path, monkeypatch):
    h, runtime = harness(tmp_path, monkeypatch, pause=False, replies=[KeyboardInterrupt(), '{"approved":true}'])
    with pytest.raises(KeyboardInterrupt):
        h.run({})
    assert h.resume()['reason'] == 'interrupted_call'
    snapshot = h.status()
    with pytest.raises(ValueError, match='expected_revision'):
        h.resume(retry_interrupted=True)
    with pytest.raises(RevisionConflict):
        h.resume(retry_interrupted=True, expected_revision='stale')
    state = h.resume(retry_interrupted=True, expected_revision=snapshot.revision)
    assert state['status'] == 'completed' and state['calls'] == 2


def test_committed_receipt_is_recovered_without_dispatch(tmp_path, monkeypatch):
    h, runtime = harness(tmp_path, monkeypatch, pause=False)
    accept = h._accept
    monkeypatch.setattr(h, '_accept', lambda *args: (_ for _ in ()).throw(OSError('crash')))
    with pytest.raises(OSError):
        h.run({})
    monkeypatch.setattr(h, '_accept', accept)
    assert h.resume()['status'] == 'completed'
    assert len(runtime.calls) == 1


def test_lost_lease_is_not_model_cancellation_or_blocked_state(tmp_path, monkeypatch):
    h, runtime = harness(tmp_path, monkeypatch, pause=False)
    run = runtime.run
    def lose(*args, **kwargs):
        h._lease.active = False
        assert kwargs['cancelled']() is True
        return run(*args, **kwargs)
    runtime.run = lose
    with pytest.raises(LeaseLost):
        h.run({})
    saved = h.status().state
    assert saved['pending'] is not None and saved['outputs'] == {}
    assert saved['status'] == 'running' and saved['reason'] is None


def test_loss_after_receipt_commit_leaves_receipt_recoverable(tmp_path, monkeypatch):
    h, runtime = harness(tmp_path, monkeypatch, pause=False)
    save = h.store.save_receipt
    def lose(*args):
        save(*args)
        args[-1].active = False
    monkeypatch.setattr(h.store, 'save_receipt', lose)
    with pytest.raises(LeaseLost):
        h.run({})
    monkeypatch.setattr(h.store, 'save_receipt', save)
    assert h.resume()['status'] == 'completed'
    assert len(runtime.calls) == 1


def test_constructor_rejects_ambiguous_storage(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    store = FileRunStore(tmp_path / 'storage')
    with pytest.raises(ValueError):
        Harness(flow, tmp_path / 'run', store=store, run_id=uuid.uuid4().hex)
    with pytest.raises(ValueError):
        Harness(flow, store=store)


def test_status_rejects_identity_and_receipt_corruption(tmp_path, monkeypatch):
    h, _ = harness(tmp_path, monkeypatch)
    h.run({})
    state = h.status().state
    directory = h.store.root / h.store.namespace / state['run_id']
    receipt = next((directory / 'attempts').glob('*.json'))
    receipt.write_text('{"bad":true}')
    with pytest.raises(ValueError):
        h.status()


def test_response_error_requires_revision_and_stale_revision_remains_conflict(tmp_path, monkeypatch):
    from prosaic_harness import HumanResponseError
    h, runtime = harness(tmp_path, monkeypatch)
    h.run({})
    before = h.status()
    with pytest.raises(HumanResponseError) as caught:
        h.resume(choice='approve')
    assert caught.value.code == 'expected_revision_required'
    with pytest.raises(RevisionConflict):
        h.resume(choice='PRIVATE', expected_revision='stale')
    assert h.status() == before and len(runtime.calls) == 1
