"""Owner-only pack migrations use real disposable PostgreSQL transactions."""
import pytest
import psycopg
from prosaic_harness import StoreIncompatible,StoreBusy,ConversationScope
from prosaic_harness_postgres import PostgresRunStore,PostgresSessionStore
from prosaic_harness_postgres import schema,session_schema
from test_cli import grant_runtime
from test_session_schema import grant_conversations


@pytest.mark.parametrize('kind',['workflows','conversations'])
def test_owner_migration_is_explicit_and_keeps_existing_bytes(db_admin_dsn,kind):
    cls=PostgresRunStore if kind=='workflows' else PostgresSessionStore
    table='prosaic_harness' if kind=='workflows' else 'prosaic_harness_conversations'
    with cls(db_admin_dsn,namespace='pack-test') as store:
        store.initialize()
        assert 'context_packs_v1' not in store.capabilities
        with pytest.raises(StoreIncompatible): store.initialize(context_packs=True)
        with psycopg.connect(db_admin_dsn) as conn:
            before=conn.execute('SELECT schema_version,storage_contract_version FROM '+table+'.schema_version').fetchall()
        store.check_ready()
        with psycopg.connect(db_admin_dsn) as conn:
            assert conn.execute('SELECT schema_version,storage_contract_version FROM '+table+'.schema_version').fetchall()==before
        store.migrate_context_pack_storage();store.migrate_context_pack_storage()
        assert 'context_packs_v1' in store.capabilities
        old=schema if kind=='workflows' else session_schema
        with pytest.raises(StoreIncompatible):
            store._transport.call(lambda conn:old.ready_on_connection(conn,expected_versions=before[0]))


@pytest.mark.parametrize('kind',['workflows','conversations'])
def test_runtime_cannot_migrate_and_active_other_namespace_lease_blocks_owner(db_admin_dsn,runtime_dsn,kind):
    cls=PostgresRunStore if kind=='workflows' else PostgresSessionStore
    with cls(db_admin_dsn,namespace='owner') as owner: owner.initialize()
    (grant_runtime if kind=='workflows' else grant_conversations)(db_admin_dsn,runtime_dsn)
    with cls(runtime_dsn,namespace='other') as runtime,cls(db_admin_dsn,namespace='owner') as owner:
        with pytest.raises(StoreIncompatible): runtime.migrate_context_pack_storage()
        scope=ConversationScope('other','sandbox','app','tenant','actor')
        kwargs={'scope':scope} if kind=='conversations' else {}
        with runtime.lease('a'*32,**kwargs):
            with pytest.raises(StoreBusy): owner.migrate_context_pack_storage()
        owner.migrate_context_pack_storage()
        assert 'context_packs_v1' in runtime.capabilities


@pytest.mark.parametrize('kind',['workflows','conversations'])
def test_fresh_pack_storage_and_cli_require_explicit_store(db_admin_dsn,kind,monkeypatch,capsys):
    import json
    from prosaic_harness_postgres.cli import main
    cls=PostgresRunStore if kind=='workflows' else PostgresSessionStore
    with cls(db_admin_dsn,namespace='pack-test') as owner: owner.initialize(context_packs=True)
    monkeypatch.setenv('PACK_TEST_DATABASE',db_admin_dsn)
    assert main(['migrate-context-packs','--store',kind,'--dsn-env','PACK_TEST_DATABASE'])==0
    assert json.loads(capsys.readouterr().out)=={'migrated':True,'store':kind,'storage_contract':2 if kind=='workflows' else 3}


@pytest.mark.parametrize('kind',['workflows','conversations'])
def test_migration_never_rewrites_pending_records_or_receipts(db_admin_dsn,kind):
    from prosaic_harness.contracts import seal
    from support.session_documents import document,reserve,receipt
    from prosaic_harness.session_contracts import mark_dispatch
    cls=PostgresRunStore if kind=='workflows' else PostgresSessionStore
    namespace='pack-test';sid='a'*32;aid='b'*32
    scope=ConversationScope(namespace,'sandbox','app','tenant','actor')
    with cls(db_admin_dsn,namespace=namespace) as owner:
        owner.initialize()
        if kind=='workflows':
            state=seal({'version':2,'run_id':sid,'historic':'exact ž bytes'})
            saved=seal({'version':1,'run_id':sid,'id':aid,'historic':'exact receipt'})
            with owner.lease(sid) as lease:
                owner.create_run(sid,state,lease);owner.save_receipt(sid,aid,saved,lease)
            table='prosaic_harness';records='runs'
        else:
            state=mark_dispatch(reserve(document(scope)),aid);saved=receipt(state)
            with owner.lease(sid,scope=scope) as lease:
                owner.create_session(sid,state,lease,scope=scope);owner.save_receipt(sid,aid,saved,lease,scope=scope)
            table='prosaic_harness_conversations';records='sessions'
        with psycopg.connect(db_admin_dsn) as conn:
            before=[conn.execute('SELECT document FROM '+table+'.'+name).fetchall() for name in (records,'receipts')]
        owner.migrate_context_pack_storage()
        with psycopg.connect(db_admin_dsn) as conn:
            assert [conn.execute('SELECT document FROM '+table+'.'+name).fetchall() for name in (records,'receipts')]==before


def test_failed_pack_postupdate_validation_rolls_back(db_admin_dsn,monkeypatch):
    with PostgresSessionStore(db_admin_dsn,namespace='pack-test') as owner: owner.initialize()
    original=session_schema.ready_on_connection
    async def reject(connection,**kwargs):
        row=await (await connection.execute('SELECT schema_version FROM prosaic_harness_conversations.schema_version')).fetchone()
        if row==(3,): raise StoreIncompatible('synthetic post-migration rejection')
        return await original(connection,**kwargs)
    monkeypatch.setattr(session_schema,'ready_on_connection',reject)
    with PostgresSessionStore(db_admin_dsn,namespace='pack-test') as owner:
        with pytest.raises(StoreIncompatible): owner.migrate_context_pack_storage()
    with psycopg.connect(db_admin_dsn) as conn:
        assert conn.execute('SELECT schema_version,storage_contract_version FROM prosaic_harness_conversations.schema_version').fetchall()==[(2,2)]
