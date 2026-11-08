"""Context-pack storage is an explicit namespace capability."""
import pytest
from prosaic_harness import StoreIncompatible,StoreBusy
from prosaic_harness.session_contracts import new_session
from prosaic_harness.context_packs.records import upgrade_pack_session
from support.conversations import binding_factory,scope
from support.context_pack_cases import scope_case


@pytest.fixture(params=['memory','file'])
def backend(request,tmp_path):
    from prosaic_harness import MemorySessionStore,FileSessionStore
    store=(MemorySessionStore(namespace='test') if request.param=='memory'
        else FileSessionStore(tmp_path/'private',namespace='test'))
    yield store
    store.close()


def pack_state(scope,binding_factory):
    return upgrade_pack_session(new_session('a'*32,scope,binding_factory()),scope_case(),'f'*64)


def test_legacy_initialization_refuses_pack_records(backend,scope,binding_factory):
    backend.initialize()
    assert 'context_packs_v1' not in backend.capabilities
    with backend.lease('a'*32,scope=scope) as lease:
        with pytest.raises(StoreIncompatible): backend.create_session('a'*32,pack_state(scope,binding_factory),lease,scope=scope)


def test_fresh_pack_namespace_requires_explicit_opt_in(backend,scope,binding_factory):
    backend.initialize(context_packs=True)
    assert 'context_packs_v1' in backend.capabilities
    state=pack_state(scope,binding_factory)
    with backend.lease('a'*32,scope=scope) as lease:
        backend.create_session('a'*32,state,lease,scope=scope)
    assert backend.load_session('a'*32,scope=scope).state==state


def test_initialize_does_not_upgrade_existing_namespace(backend):
    backend.initialize()
    with pytest.raises(StoreIncompatible): backend.initialize(context_packs=True)
    assert 'context_packs_v1' not in backend.capabilities
    backend.migrate_context_pack_storage()
    backend.migrate_context_pack_storage()
    assert 'context_packs_v1' in backend.capabilities


def test_active_lease_blocks_migration(backend,scope):
    backend.initialize()
    with backend.lease('a'*32,scope=scope):
        with pytest.raises(StoreBusy): backend.migrate_context_pack_storage()
