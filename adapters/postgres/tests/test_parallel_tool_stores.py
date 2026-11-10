import pytest
from prosaic_harness import StoreIncompatible,StoreBusy,ConversationScope
from prosaic_harness_postgres import PostgresRunStore,PostgresSessionStore
from test_cli import grant_runtime
from test_session_schema import grant_conversations


@pytest.mark.parametrize('kind',['workflows','conversations'])
def test_parallel_migration_requires_owner_and_drained_writers(db_admin_dsn,runtime_dsn,kind):
    cls=PostgresRunStore if kind=='workflows' else PostgresSessionStore
    with cls(db_admin_dsn,namespace='test') as owner:
        owner.initialize(tool_contracts=True)
        assert 'parallel_tool_calls_v1' not in owner.capabilities
        with pytest.raises(StoreIncompatible):owner.initialize(parallel_tools=True)
    (grant_runtime if kind=='workflows' else grant_conversations)(db_admin_dsn,runtime_dsn)
    with cls(runtime_dsn,namespace='test') as worker,cls(db_admin_dsn,namespace='test') as owner:
        with pytest.raises(StoreIncompatible):worker.initialize(parallel_tools=True)
        with pytest.raises(StoreIncompatible):worker.migrate_parallel_tool_storage()
        kwargs={'scope':ConversationScope('test','sandbox','app','tenant','actor')} if kind=='conversations' else {}
        with worker.lease('a'*32,**kwargs):
            with pytest.raises(StoreBusy):owner.migrate_parallel_tool_storage()
        owner.migrate_parallel_tool_storage()
        assert {'context_packs_v1','tool_contracts_v1','parallel_tool_calls_v1'}<=worker.capabilities
        owner.migrate_tool_contract_storage();owner.migrate_context_pack_storage()
        assert 'parallel_tool_calls_v1' in worker.capabilities


def test_parallel_lease_takeover_drains_and_prevents_redispatch(db_admin_dsn,parallel_endpoint):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier,Event
    from prosaic_harness import Harness,LeaseLost
    from support.parallel_tools import queue_batch
    from test_parallel_tool_workflow import factory,proposal
    import psycopg
    cfg,requests,replies=parallel_endpoint;gate=Barrier(3);release=Event();seen=[]
    def read(a,c):seen.append(c.call_index);gate.wait(timeout=4);assert release.wait(5);return {'ok':True}
    workflow=factory(cfg,handler=read).build(proposal())
    with PostgresRunStore(db_admin_dsn,namespace='test') as store,PostgresRunStore(db_admin_dsn,namespace='test') as fresh:
        store.initialize(parallel_tools=True);ctl=Harness(workflow,store=store,run_id='a'*32);queue_batch(replies,n=3)
        with ThreadPoolExecutor(1) as pool:
            future=pool.submit(ctl.run,{})
            try:
                gate.wait(timeout=5)
                with psycopg.connect(db_admin_dsn) as conn:conn.execute("UPDATE prosaic_harness.leases SET expires_at=clock_timestamp()-interval '1 second' WHERE run_id=%s",('a'*32,))
                with fresh.lease('a'*32):
                    with pytest.raises(LeaseLost):store._transport.call(lambda conn:store._renew(conn,ctl._lease),renewal=True)
                    assert not future.done();release.set()
                    with pytest.raises(LeaseLost):future.result(timeout=5)
            finally:release.set()
        state=Harness(workflow,store=fresh,run_id='a'*32).resume()
        assert state['reason']=='interrupted_call' and sorted(seen)==[0,1] and len(requests)==1
from support.parallel_tools import parallel_endpoint
