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


def assert_session_store_contract(store, *, scope, state, receipt):
    """Caller owns provisioning/cleanup and supplies a pending allocated attempt."""
    from .session_contracts import mark_dispatch, seal as session_seal
    from .conversation_errors import SessionAlreadyExists
    sid,aid=state['sessionId'],receipt['invocationId']
    with store.lease(sid,scope=scope) as lease:
        revision=store.create_session(sid,state,lease,scope=scope)
        loaded=store.load_session(sid,scope=scope)
        assert loaded.state==state and loaded.revision==revision
        loaded.state['turns'].append({'forged':True})
        assert store.load_session(sid,scope=scope).state==state
        _raises(SessionAlreadyExists,lambda:store.create_session(sid,state,lease,scope=scope))
        running=mark_dispatch(state,aid)
        newer=store.save_session(sid,running,revision,lease,scope=scope)
        assert newer!=revision
        _raises(RevisionConflict,lambda:store.save_session(sid,running,revision,lease,scope=scope))
        store.save_receipt(sid,aid,receipt,lease,scope=scope)
        store.save_receipt(sid,aid,deepcopy(receipt),lease,scope=scope)
        assert store.load_receipt(sid,aid,scope=scope)==receipt
        changed=session_seal(receipt|{'result':receipt['result']|{'answer':'changed'}})
        _raises(ReceiptConflict,lambda:store.save_receipt(sid,aid,changed,lease,scope=scope))
