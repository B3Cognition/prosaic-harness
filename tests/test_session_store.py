from dataclasses import replace
import pytest
from prosaic_harness import (MemorySessionStore, SessionNotFound, SessionAlreadyExists,
    SessionBusy, LeaseLost, RevisionConflict, ReceiptConflict, StoreCorrupt)
from prosaic_harness.session_contracts import new_session, seal
from support.conversations import binding_factory, scope
from test_session_contracts import reserve, receipt, mark_dispatch, SID, AID


@pytest.fixture
def memory_store():
    store=MemorySessionStore(namespace='test')
    store.initialize()
    yield store
    store.close()


def test_session_snapshot_is_owned(memory_store,scope,binding_factory):
    with memory_store.lease(SID,scope=scope) as lease:
        revision=memory_store.create_session(SID,new_session(SID,scope,binding_factory()),lease,scope=scope)
    loaded=memory_store.load_session(SID,scope=scope)
    assert loaded.revision==revision and loaded.session_id==SID
    loaded.state['turns'].append({'forged':True})
    assert memory_store.load_session(SID,scope=scope).state['turns']==[]


def test_cas_leases_and_receipts(memory_store,scope,binding_factory):
    with memory_store.lease(SID,scope=scope) as lease:
        original=new_session(SID,scope,binding_factory())
        revision=memory_store.create_session(SID,original,lease,scope=scope)
        with pytest.raises(SessionAlreadyExists):
            memory_store.create_session(SID,original,lease,scope=scope)
        with pytest.raises(SessionBusy):
            with memory_store.lease(SID,scope=scope): pass
        running=mark_dispatch(reserve(original),AID)
        next_revision=memory_store.save_session(SID,running,revision,lease,scope=scope)
        assert next_revision!=revision
        with pytest.raises(RevisionConflict):
            memory_store.save_session(SID,running,revision,lease,scope=scope)
        saved=receipt(running)
        memory_store.save_receipt(SID,AID,saved,lease,scope=scope)
        memory_store.save_receipt(SID,AID,saved,lease,scope=scope)
        assert memory_store.load_receipt(SID,AID,scope=scope)==saved
        changed=seal(saved|{'result':saved['result']|{'answer':'Changed'}})
        with pytest.raises(ReceiptConflict):
            memory_store.save_receipt(SID,AID,changed,lease,scope=scope)
    with pytest.raises(LeaseLost):
        memory_store.save_session(SID,running,next_revision,lease,scope=scope)


def test_foreign_owner_has_no_read_write_or_receipt_visibility(memory_store,scope,binding_factory):
    with memory_store.lease(SID,scope=scope) as lease:
        state=mark_dispatch(reserve(new_session(SID,scope,binding_factory())),AID)
        revision=memory_store.create_session(SID,state,lease,scope=scope)
        memory_store.save_receipt(SID,AID,receipt(state),lease,scope=scope)
    foreign=replace(scope,actor='other')
    with pytest.raises(SessionNotFound): memory_store.load_session(SID,scope=foreign)
    with pytest.raises(SessionNotFound): memory_store.load_receipt(SID,AID,scope=foreign)
    with memory_store.lease(SID,scope=foreign) as lease:
        with pytest.raises(SessionNotFound):
            memory_store.save_session(SID,state,revision,lease,scope=foreign)


def test_lease_cannot_cross_store_or_scope(memory_store,scope,binding_factory):
    other=MemorySessionStore(namespace='test')
    other.initialize()
    with memory_store.lease(SID,scope=scope) as lease:
        state=new_session(SID,scope,binding_factory())
        with pytest.raises(LeaseLost): other.create_session(SID,state,lease,scope=scope)
        with pytest.raises(LeaseLost):
            memory_store.create_session(SID,state,lease,scope=replace(scope,actor='other'))
    other.close()


def test_hash_cannot_admit_bad_state(memory_store,scope,binding_factory):
    with memory_store.lease(SID,scope=scope) as lease:
        state=seal(new_session(SID,scope,binding_factory())|{'turns':[{'forged':True}]})
        with pytest.raises(StoreCorrupt): memory_store.create_session(SID,state,lease,scope=scope)


def test_reusable_store_conformance(memory_store,scope,binding_factory):
    from prosaic_harness.testing import assert_session_store_contract
    state=reserve(new_session(SID,scope,binding_factory()))
    assert_session_store_contract(memory_store,scope=scope,state=state,receipt=receipt(mark_dispatch(state,AID)))


def test_owned_lease_rejects_forked_pid(memory_store,scope,binding_factory):
    with memory_store.lease(SID,scope=scope) as lease:
        lease.pid=-1
        with pytest.raises(LeaseLost):
            memory_store.create_session(SID,new_session(SID,scope,binding_factory()),lease,scope=scope)
