from pathlib import Path
import pytest
import prosaic_harness as api
from prosaic_harness.context_packs.file_namespace import address


@pytest.mark.parametrize('kind',['memory','file'])
def test_session_parallel_enablement_is_explicit_monotone(kind,tmp_path):
    store=api.MemorySessionStore(namespace='test') if kind=='memory' else api.FileSessionStore(tmp_path,namespace='test')
    store.initialize(tool_contracts=True)
    assert 'parallel_tool_calls_v1' not in store.capabilities
    with pytest.raises(api.StoreIncompatible):store.initialize(parallel_tools=True)
    store.migrate_parallel_tool_storage()
    assert {'context_assembly_v1','tool_contracts_v1','parallel_tool_calls_v1'}<=store.capabilities
    store.migrate_tool_contract_storage();store.migrate_context_pack_storage()
    assert 'parallel_tool_calls_v1' in store.capabilities
    if kind=='file':assert store._storage_contract==5
    store.close()


def test_file_run_migration_retains_existing_document_bytes(tmp_path):
    from prosaic_harness.contracts import seal
    store=api.FileRunStore(tmp_path,namespace='test');store.initialize(tool_contracts=True)
    state=seal({'version':2,'run_id':'a'*32,'sentinel':'existing'})
    with store.lease('a'*32) as lease:store.create_run('a'*32,state,lease)
    before=store.load_run('a'*32)
    store.migrate_parallel_tool_storage()
    assert store.load_run('a'*32)==before
    assert {'context_packs_v1','tool_contracts_v1','parallel_tool_calls_v1'}<=store.capabilities
    assert b'"storageContract":4' in address(store).read_bytes()
    store.migrate_tool_contract_storage()
    assert 'parallel_tool_calls_v1' in store.capabilities
    store.close()


@pytest.mark.parametrize('kind',['run','session'])
def test_fresh_parallel_store_includes_parent_contracts(kind,tmp_path):
    store=api.FileRunStore(tmp_path,namespace='test') if kind=='run' else api.FileSessionStore(tmp_path,namespace='test')
    store.initialize(parallel_tools=True)
    assert {'tool_contracts_v1','context_packs_v1','parallel_tool_calls_v1'}<=store.capabilities
    store.close()


@pytest.mark.parametrize('bad',[0,1,None,'yes'])
def test_parallel_store_option_rejects_non_boolean(tmp_path,bad):
    store=api.MemorySessionStore(namespace='test')
    with pytest.raises(ValueError):store.initialize(parallel_tools=bad)
