"""Reusable backend assertions; fixtures/cleanup belong to the caller."""
from copy import deepcopy
from .contracts import seal
from .run_store import RunAlreadyExists, RevisionConflict, ReceiptConflict


def _raises(error, operation):
    try:
        operation()
    except error:
        return
    raise AssertionError(f'expected {error.__name__}')


def assert_run_store_contract(store, *, state, receipt):
    run_id = state['run_id']
    with store.lease(run_id) as lease:
        revision = store.create_run(run_id, state, lease)
        snapshot = store.load_run(run_id)
        assert snapshot.state == state and snapshot.revision == revision
        snapshot.state['inputs'] = {'mutated': True}
        assert store.load_run(run_id).state['inputs'] == state['inputs']
        _raises(RunAlreadyExists, lambda: store.create_run(run_id, state, lease))
        newer = seal(deepcopy(state) | {'inputs': {'new': True}})
        next_revision = store.save_run(run_id, newer, revision, lease)
        assert next_revision != revision
        _raises(RevisionConflict, lambda: store.save_run(run_id, state, revision, lease))
        store.save_receipt(run_id, receipt['id'], receipt, lease)
        store.save_receipt(run_id, receipt['id'], deepcopy(receipt), lease)
        assert store.load_receipt(run_id, receipt['id']) == receipt
        changed = seal(receipt | {'events': [{'event': 'different'}]})
        _raises(ReceiptConflict, lambda: store.save_receipt(run_id, receipt['id'], changed, lease))
