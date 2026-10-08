"""Backend invariants: immutable evidence, CAS and live ownership."""
import copy
import json
from pathlib import Path

import pytest
import prosaic_harness as api
from prosaic_harness.contracts import seal
from test_harness import setup, FakeRuntime


@pytest.fixture
def documents(tmp_path, monkeypatch):
    seed = tmp_path / 'seed'
    seed.mkdir()
    flow = setup(seed, monkeypatch, pause=True)
    state = api.Harness(flow, seed / 'run', runtime=FakeRuntime(['{"approved":true}'])).run({'task': 'draft'})
    receipt = json.loads(next((seed / 'run/attempts').glob('*.json')).read_text())
    return state, receipt


def store(tmp_path, namespace='tenant-a'):
    assert hasattr(api, 'FileRunStore'), 'public FileRunStore is missing'
    return api.FileRunStore(tmp_path / 'storage', namespace=namespace)


def test_snapshot_independence_and_cas(tmp_path, documents):
    backend = store(tmp_path)
    state, _ = documents
    run_id = state['run_id']
    with backend.lease(run_id) as lease:
        first = backend.create_run(run_id, state, lease)
        loaded = backend.load_run(run_id)
        loaded.state['inputs']['task'] = 'mutated'
        assert backend.load_run(run_id).state['inputs'] == {'task': 'draft'}
        newer = seal(state | {'inputs': {'task': 'updated'}})
        second = backend.save_run(run_id, newer, first, lease)
        assert second != first
        with pytest.raises(api.RevisionConflict):
            backend.save_run(run_id, state, first, lease)
        with pytest.raises(api.RunAlreadyExists):
            backend.create_run(run_id, state, lease)


def test_foreign_and_released_lease_are_rejected(tmp_path, documents):
    a, b = store(tmp_path), store(tmp_path, 'tenant-b')
    state, _ = documents
    with a.lease(state['run_id']) as lease:
        with pytest.raises(api.LeaseLost):
            b.create_run(state['run_id'], state, lease)
        with pytest.raises(api.StoreBusy):
            a.close()
    with pytest.raises(api.LeaseLost):
        a.create_run(state['run_id'], state, lease)


def test_receipts_are_immutable_and_namespace_scoped(tmp_path, documents):
    a, b = store(tmp_path), store(tmp_path, 'tenant-b')
    state, receipt = documents
    run_id, invocation_id = state['run_id'], receipt['id']
    with a.lease(run_id) as lease:
        a.create_run(run_id, state, lease)
        a.save_receipt(run_id, invocation_id, receipt, lease)
        a.save_receipt(run_id, invocation_id, copy.deepcopy(receipt), lease)
        changed = seal(receipt | {'events': [{'event': 'different'}]})
        with pytest.raises(api.ReceiptConflict):
            a.save_receipt(run_id, invocation_id, changed, lease)
    assert a.load_receipt(run_id, invocation_id)['result']['stdout'] == '{"approved":true}'
    assert b.load_receipt(run_id, invocation_id) is None
    with pytest.raises(api.RunNotFound):
        b.load_run(run_id)


def test_same_run_is_exclusive(tmp_path, documents):
    a, b = store(tmp_path), store(tmp_path)
    run_id = documents[0]['run_id']
    with a.lease(run_id):
        with pytest.raises(api.RunBusy):
            with b.lease(run_id):
                pytest.fail('second owner admitted')


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf'), 'é' * (4 * 1024 * 1024)],
                         ids=['nan', 'infinity', 'negative-infinity', 'oversized-utf8'])
def test_invalid_payload_cannot_create_state(tmp_path, documents, value):
    a = store(tmp_path)
    state, _ = documents
    # Non-finite/over-limit inputs must fail without creating a checkpoint.
    changed = state | {'inputs': {'value': value}}
    with a.lease(state['run_id']) as lease:
        with pytest.raises((api.StoreCorrupt, ValueError)):
            a.create_run(state['run_id'], changed, lease)
    with pytest.raises(api.RunNotFound):
        a.load_run(state['run_id'])


@pytest.mark.parametrize('bad', ['../escape', '', 'A' * 32, 'a' * 33])
def test_identifiers_are_not_paths(tmp_path, bad):
    a = store(tmp_path)
    with pytest.raises(ValueError):
        a.load_run(bad)


def test_symlink_destination_and_corrupt_checkpoint_are_rejected(tmp_path, documents):
    a = store(tmp_path)
    state, _ = documents
    target = tmp_path / 'outside'
    target.mkdir()
    (tmp_path / 'storage').mkdir()
    (tmp_path / 'storage/tenant-a').symlink_to(target, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        with a.lease(state['run_id']):
            pass
    assert list(target.iterdir()) == []


def test_legacy_binding_preserves_layout(tmp_path, documents):
    assert hasattr(api, 'FileRunStore'), 'public FileRunStore is missing'
    a = api.FileRunStore.for_run_dir(tmp_path / 'legacy')
    state, receipt = documents
    with a.lease('legacy') as lease:
        a.create_run('legacy', state, lease)
        a.save_receipt('legacy', receipt['id'], receipt, lease)
    assert (tmp_path / 'legacy/run.json').is_file()
    assert (tmp_path / 'legacy/attempts' / (receipt['id'] + '.json')).is_file()
    path = tmp_path / 'legacy/run.json'
    path.write_text('{"version":2,"version":2}')
    with pytest.raises(api.StoreCorrupt):
        a.load_run('legacy')


def test_shared_conformance(tmp_path, documents):
    backend = store(tmp_path)
    from prosaic_harness.testing import assert_run_store_contract
    assert_run_store_contract(backend, state=documents[0], receipt=documents[1])


def test_other_runs_revision_cannot_authorize_write(tmp_path, monkeypatch, documents):
    backend = store(tmp_path)
    state, _ = documents
    other = tmp_path / 'second-seed'
    other.mkdir()
    flow = setup(other, monkeypatch, pause=True)
    second = api.Harness(flow, other / 'run', runtime=FakeRuntime(['{"approved":true}'])).run({'task': 'draft'})
    with backend.lease(second['run_id']) as lease:
        foreign_revision = backend.create_run(second['run_id'], second, lease)
    with backend.lease(state['run_id']) as lease:
        revision = backend.create_run(state['run_id'], state, lease)
        with pytest.raises(api.RevisionConflict):
            backend.save_run(state['run_id'], state, foreign_revision, lease)
        with pytest.raises(api.LeaseLost):
            backend.create_run(second['run_id'], second, lease)
    assert backend.load_run(state['run_id']).revision == revision


def test_corrupt_seal_and_symlink_receipt_never_read_as_absent(tmp_path, documents):
    backend = store(tmp_path)
    state, receipt = documents
    with backend.lease(state['run_id']) as lease:
        backend.create_run(state['run_id'], state, lease)
        backend.save_receipt(state['run_id'], receipt['id'], receipt, lease)
    directory = tmp_path / 'storage/tenant-a' / state['run_id']
    altered = state | {'inputs': {'task': 'corrupt'}}
    (directory / 'run.json').write_text(json.dumps(altered))
    with pytest.raises(api.StoreCorrupt):
        backend.load_run(state['run_id'])
    path = directory / 'attempts' / (receipt['id'] + '.json')
    target = tmp_path / 'receipt-outside'
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        backend.load_receipt(state['run_id'], receipt['id'])


@pytest.mark.parametrize('namespace', ['../x', '.', '', 'a' * 129, 'é'])
def test_invalid_namespace_does_not_create_directories(tmp_path, namespace):
    assert hasattr(api, 'FileRunStore'), 'public FileRunStore is missing'
    with pytest.raises(ValueError):
        api.FileRunStore(tmp_path / 'storage', namespace=namespace)
    assert not (tmp_path / 'storage').exists()
