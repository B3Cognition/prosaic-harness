import pytest

import prosaic_harness as h


@pytest.mark.parametrize('kind', ['memory', 'file', 'workflow'])
def test_delegation_storage_upgrade_is_explicit_and_monotone(kind, tmp_path):
    if kind == 'workflow':
        store = h.FileRunStore(tmp_path, namespace='delegate')
    elif kind == 'file':
        store = h.FileSessionStore(tmp_path, namespace='delegate')
    else:
        store = h.MemorySessionStore(namespace='delegate')
    store.initialize(parallel_tools=True)
    assert 'sub_agents_v1' not in store.capabilities
    with pytest.raises(h.StoreIncompatible):
        store.initialize(sub_agents=True)
    store.migrate_sub_agent_storage()
    assert {'sub_agents_v1', 'parallel_tool_calls_v1', 'context_packs_v1'} <= store.capabilities
    store.migrate_parallel_tool_storage()
    assert 'sub_agents_v1' in store.capabilities
