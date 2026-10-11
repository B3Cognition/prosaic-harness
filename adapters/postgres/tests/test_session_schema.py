from concurrent.futures import ThreadPoolExecutor

import pytest
from prosaic_harness import StoreUninitialized, StoreIncompatible
import prosaic_harness_postgres as pg


def test_conversation_readiness_never_initializes(db_admin_dsn):
    with pg.PostgresSessionStore(db_admin_dsn, namespace='test') as store:
        with pytest.raises(StoreUninitialized):
            store.check_ready()


def test_conversation_initialization_is_parallel_and_repeatable(db_admin_dsn):
    def initialize():
        with pg.PostgresSessionStore(db_admin_dsn, namespace='test') as store:
            store.initialize()
            store.initialize()
            store.check_ready()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: initialize(), range(2)))


def grant_conversations(admin_dsn, runtime_dsn):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    role = sql.Identifier(conninfo_to_dict(runtime_dsn)['user'])
    with psycopg.connect(admin_dsn) as admin:
        admin.execute(sql.SQL('GRANT USAGE ON SCHEMA prosaic_harness_conversations TO {}').format(role))
        admin.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA prosaic_harness_conversations TO {}').format(role))
        admin.execute(sql.SQL('GRANT INSERT, UPDATE ON prosaic_harness_conversations.sessions, '
            'prosaic_harness_conversations.leases TO {}').format(role))
        admin.execute(sql.SQL('GRANT INSERT ON prosaic_harness_conversations.receipts TO {}').format(role))


def test_new_runtime_grants_are_sufficient_and_least_privilege(db_admin_dsn, runtime_dsn):
    import psycopg
    with pg.PostgresSessionStore(db_admin_dsn, namespace='test') as owner:
        owner.initialize()
    with pg.PostgresSessionStore(runtime_dsn, namespace='test') as runtime:
        with pytest.raises(StoreIncompatible):
            runtime.check_ready()
        grant_conversations(db_admin_dsn, runtime_dsn)
        runtime.check_ready()
        with psycopg.connect(runtime_dsn) as conn:
            for relation, privilege in [
                ('prosaic_harness_conversations.schema_version', 'UPDATE'),
                ('prosaic_harness_conversations.receipts', 'UPDATE'),
                ('prosaic_harness_conversations.receipts', 'DELETE'),
                ('prosaic_harness_conversations.sessions', 'DELETE'),
                ('prosaic_harness_conversations.leases', 'DELETE')]:
                assert conn.execute('SELECT has_table_privilege(%s,%s)',
                                    (relation, privilege)).fetchone() == (False,)
            assert conn.execute("SELECT has_schema_privilege('prosaic_harness_conversations','CREATE')").fetchone() == (False,)


def test_old_runstore_role_and_schema_need_no_conversation_changes(db_admin_dsn, runtime_dsn):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    with pg.PostgresRunStore(db_admin_dsn, namespace='legacy') as old:
        old.initialize()
    role = sql.Identifier(conninfo_to_dict(runtime_dsn)['user'])
    with psycopg.connect(db_admin_dsn) as admin:
        admin.execute(sql.SQL('GRANT USAGE ON SCHEMA prosaic_harness TO {}').format(role))
        admin.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA prosaic_harness TO {}').format(role))
        admin.execute(sql.SQL('GRANT INSERT, UPDATE ON prosaic_harness.runs,prosaic_harness.leases TO {}').format(role))
        admin.execute(sql.SQL('GRANT INSERT ON prosaic_harness.receipts TO {}').format(role))
    with pg.PostgresRunStore(runtime_dsn, namespace='legacy') as old:
        old.check_ready()
    with pg.PostgresSessionStore(runtime_dsn, namespace='legacy') as chat:
        with pytest.raises(StoreUninitialized):
            chat.check_ready()
    with pg.PostgresSessionStore(db_admin_dsn, namespace='test') as chat:
        chat.initialize()
    with pg.PostgresRunStore(runtime_dsn, namespace='legacy') as old:
        old.check_ready()
    with pg.PostgresSessionStore(runtime_dsn, namespace='legacy') as chat:
        with pytest.raises(StoreIncompatible):
            chat.check_ready()


@pytest.mark.parametrize('statement', [
    'UPDATE prosaic_harness_conversations.schema_version SET schema_version=99',
    'ALTER TABLE prosaic_harness_conversations.receipts SET UNLOGGED',
    'ALTER TABLE prosaic_harness_conversations.sessions ALTER COLUMN document DROP NOT NULL',
    'ALTER TABLE prosaic_harness_conversations.sessions DROP CONSTRAINT sessions_namespace_session_id_scope_identity_fkey',
    'ALTER TABLE prosaic_harness_conversations.leases DROP CONSTRAINT leases_scope_identity_check',
])
def test_damaged_conversation_schema_is_refused(db_admin_dsn, statement):
    import psycopg
    with pg.PostgresSessionStore(db_admin_dsn, namespace='test') as store:
        store.initialize()
        with psycopg.connect(db_admin_dsn) as admin:
            admin.execute(statement)
        with pytest.raises(StoreIncompatible):
            store.check_ready()
        with pytest.raises(StoreIncompatible):
            store.initialize()


def test_missing_grant_is_not_repaired(db_admin_dsn, runtime_dsn):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    with pg.PostgresSessionStore(db_admin_dsn, namespace='test') as owner:
        owner.initialize()
    grant_conversations(db_admin_dsn, runtime_dsn)
    with psycopg.connect(db_admin_dsn) as admin:
        admin.execute(sql.SQL('REVOKE INSERT ON prosaic_harness_conversations.receipts FROM {}').format(
            sql.Identifier(conninfo_to_dict(runtime_dsn)['user'])))
    with pg.PostgresSessionStore(runtime_dsn, namespace='test') as runtime:
        with pytest.raises(StoreIncompatible):
            runtime.check_ready()


def test_foreign_schema_owner_cannot_initialize(db_admin_dsn, runtime_dsn):
    import psycopg
    with psycopg.connect(db_admin_dsn) as admin:
        admin.execute('CREATE SCHEMA prosaic_harness_conversations')
    with pg.PostgresSessionStore(runtime_dsn, namespace='test') as runtime:
        with pytest.raises(StoreIncompatible):
            runtime.initialize()
