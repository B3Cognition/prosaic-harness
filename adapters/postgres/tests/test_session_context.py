"""Owner-only explicit v1->v2 migration; real PostgreSQL transactional evidence."""
import pytest
import psycopg
from prosaic_harness import StoreIncompatible, ConversationScope
from prosaic_harness.session_contracts import new_session
import prosaic_harness_postgres as pg
from prosaic_harness_postgres import session_schema
from test_session_schema import grant_conversations
from support.session_documents import bindings
from dataclasses import replace


def legacy_storage(db_admin_dsn):
    with pg.PostgresSessionStore(db_admin_dsn, namespace='context-test') as owner:
        owner.initialize()
    # Table/role contract is identical in v1; only explicit contract metadata changes.
    with psycopg.connect(db_admin_dsn) as connection:
        connection.execute('UPDATE prosaic_harness_conversations.schema_version '
            'SET schema_version=1,storage_contract_version=1')


def test_owner_migration_is_explicit_repeatable_and_keeps_v1_records(db_admin_dsn):
    scope = ConversationScope('context-test', 'sandbox', 'app', 'tenant', 'actor')
    state = new_session('a'*32, scope, bindings())
    with pg.PostgresSessionStore(db_admin_dsn, namespace='context-test') as owner:
        owner.initialize()
        with owner.lease('a'*32, scope=scope) as lease:
            owner.create_session('a'*32, state, lease, scope=scope)
        before = owner.load_session('a'*32, scope=scope)
    with psycopg.connect(db_admin_dsn) as connection:
        connection.execute('UPDATE prosaic_harness_conversations.schema_version '
            'SET schema_version=1,storage_contract_version=1')
    with pg.PostgresSessionStore(db_admin_dsn, namespace='context-test') as owner:
        with pytest.raises(StoreIncompatible): owner.check_ready()
        with pytest.raises(StoreIncompatible): owner.initialize()
        owner.migrate_context_storage()
        owner.migrate_context_storage()
        assert 'context_assembly_v1' in owner.capabilities
        assert owner.load_session('a'*32, scope=scope) == before
        with pytest.raises(StoreIncompatible):
            owner._transport.call(lambda connection:
                session_schema.ready_on_connection(connection, expected_versions=(1, 1)))


def test_runtime_role_cannot_migrate_or_gain_owner_privileges(db_admin_dsn, runtime_dsn):
    legacy_storage(db_admin_dsn)
    grant_conversations(db_admin_dsn, runtime_dsn)
    with pg.PostgresSessionStore(runtime_dsn, namespace='context-test') as runtime:
        with pytest.raises(StoreIncompatible): runtime.migrate_context_storage()
    with psycopg.connect(db_admin_dsn) as connection:
        assert connection.execute('SELECT schema_version,storage_contract_version '
            'FROM prosaic_harness_conversations.schema_version').fetchone() == (1, 1)
    with pg.PostgresSessionStore(db_admin_dsn, namespace='context-test') as owner:
        owner.migrate_context_storage()
    with pg.PostgresSessionStore(runtime_dsn, namespace='context-test') as runtime:
        assert 'context_assembly_v1' in runtime.capabilities


def test_v2_checkpoint_is_fenced_and_owner_filtered(db_admin_dsn, runtime_dsn):
    from prosaic_runtime import ContextWorkState
    from prosaic_harness import LeaseLost, SessionNotFound
    from prosaic_harness.session_context import checkpoint_context_work
    from support.session_documents import context_document
    scope = ConversationScope('context-test', 'sandbox', 'app', 'tenant', 'actor')
    with pg.PostgresSessionStore(db_admin_dsn, namespace='context-test') as owner:
        owner.initialize()
    grant_conversations(db_admin_dsn, runtime_dsn)
    state, prepared = context_document(scope)
    with pg.PostgresSessionStore(runtime_dsn, namespace='context-test') as first, \
            pg.PostgresSessionStore(runtime_dsn, namespace='context-test') as replica:
        with first.lease('a'*32, scope=scope) as lease:
            revision = first.create_session('a'*32, state, lease, scope=scope)
            before = prepared.context_work.to_dict()
            work = ContextWorkState.from_dict({**before, 'checkpointSequence': 1,
                'reservedActiveMicros': 2_000_000 - before['activeAssemblyMicros']})
            changed = checkpoint_context_work(state, 'b'*32, work)
            current = first.save_session('a'*32, changed, revision, lease, scope=scope)
            assert replica.load_session('a'*32, scope=scope).state == changed
            with pytest.raises(SessionNotFound):
                replica.load_session('a'*32, scope=replace(scope, actor='foreign'))
            with psycopg.connect(db_admin_dsn) as admin:
                admin.execute('UPDATE prosaic_harness_conversations.leases '
                    'SET generation=generation+1 WHERE namespace=%s AND session_id=%s',
                    ('context-test', 'a'*32))
            with pytest.raises(LeaseLost):
                first.save_session('a'*32, changed, current, lease, scope=scope)
def test_failed_postupdate_validation_rolls_back_metadata(db_admin_dsn, monkeypatch):
    legacy_storage(db_admin_dsn)
    original = session_schema.ready_on_connection
    async def reject_v2(connection, **kwargs):
        row = await (await connection.execute('SELECT schema_version FROM '
            'prosaic_harness_conversations.schema_version')).fetchone()
        if row == (2,): raise StoreIncompatible('synthetic postupdate validation failure')
        return await original(connection, **kwargs)
    monkeypatch.setattr(session_schema, 'ready_on_connection', reject_v2)
    with pg.PostgresSessionStore(db_admin_dsn, namespace='context-test') as owner:
        with pytest.raises(StoreIncompatible): owner.migrate_context_storage()
    with psycopg.connect(db_admin_dsn) as connection:
        assert connection.execute('SELECT schema_version,storage_contract_version '
            'FROM prosaic_harness_conversations.schema_version').fetchone() == (1, 1)


def test_operator_cli_migrates_without_exposing_connection_details(db_admin_dsn, monkeypatch, capsys):
    import json
    from prosaic_harness_postgres.cli import main
    legacy_storage(db_admin_dsn)
    monkeypatch.setenv('CONTEXT_TEST_DSN', db_admin_dsn)
    assert main(['migrate-conversations', '--dsn-env', 'CONTEXT_TEST_DSN']) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == {'migrated': True, 'conversation_storage_contract': 2}
    assert output.err == ''
    assert db_admin_dsn not in output.out
