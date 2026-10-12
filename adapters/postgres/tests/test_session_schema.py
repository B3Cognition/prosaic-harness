from concurrent.futures import ThreadPoolExecutor
import uuid

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


FORBIDDEN_RUNTIME_GRANTS = [
    ('schema', 'CREATE', None),
    ('schema_version', 'INSERT', None),
    ('schema_version', 'INSERT', 'schema_version'),
    ('schema_version', 'UPDATE', None),
    ('schema_version', 'UPDATE', 'storage_contract_version'),
    ('schema_version', 'DELETE', None),
    ('schema_version', 'TRUNCATE', None),
    ('receipts', 'UPDATE', None),
    ('receipts', 'UPDATE', 'document'),
    ('receipts', 'DELETE', None),
    ('receipts', 'TRUNCATE', None),
    ('sessions', 'DELETE', None),
    ('sessions', 'TRUNCATE', None),
    ('leases', 'DELETE', None),
    ('leases', 'TRUNCATE', None),
]


@pytest.mark.parametrize('table,privilege,column', FORBIDDEN_RUNTIME_GRANTS)
def test_runtime_readiness_rejects_extra_table_or_column_powers(db_admin_dsn, runtime_dsn,
                                                               table, privilege, column):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    with pg.PostgresSessionStore(db_admin_dsn, namespace='test') as owner:
        owner.initialize()
    grant_conversations(db_admin_dsn, runtime_dsn)
    role = sql.Identifier(conninfo_to_dict(runtime_dsn)['user'])
    relation = (sql.SQL('SCHEMA {}').format(sql.Identifier('prosaic_harness_conversations'))
        if table == 'schema' else sql.SQL('{}.{}').format(
            sql.Identifier('prosaic_harness_conversations'), sql.Identifier(table)))
    action = sql.SQL(privilege) if column is None else sql.SQL('{} ({})').format(
        sql.SQL(privilege), sql.Identifier(column))
    with pg.PostgresSessionStore(runtime_dsn, namespace='test') as runtime:
        runtime.check_ready()
        with psycopg.connect(db_admin_dsn) as admin:
            admin.execute(sql.SQL('GRANT {} ON {} TO {}').format(action, relation, role))
        try:
            # PostgreSQL table-level tests miss column-only UPDATE privileges.
            if column is not None:
                with psycopg.connect(runtime_dsn) as conn:
                    assert conn.execute('SELECT has_table_privilege(%s,%s)',
                        ('prosaic_harness_conversations.' + table, privilege)).fetchone() == (False,)
                    assert conn.execute('SELECT has_column_privilege(%s,%s,%s)',
                        ('prosaic_harness_conversations.' + table, column, privilege)).fetchone() == (True,)
            with pytest.raises(StoreIncompatible):
                runtime.check_ready()
        finally:
            with psycopg.connect(db_admin_dsn) as admin:
                admin.execute(sql.SQL('REVOKE {} ON {} FROM {}').format(action, relation, role))
        runtime.check_ready()


@pytest.mark.parametrize('privilege,column', [('UPDATE', None), ('UPDATE', 'document'), ('DELETE', None)])
def test_runtime_readiness_rejects_inherited_receipt_powers(db_admin_dsn, runtime_dsn, privilege, column):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    with pg.PostgresSessionStore(db_admin_dsn, namespace='test') as owner:
        owner.initialize()
    grant_conversations(db_admin_dsn, runtime_dsn)
    role = sql.Identifier(conninfo_to_dict(runtime_dsn)['user'])
    inherited = sql.Identifier('extra_' + uuid.uuid4().hex)
    action = sql.SQL(privilege) if column is None else sql.SQL('{} ({})').format(
        sql.SQL(privilege), sql.Identifier(column))
    with psycopg.connect(db_admin_dsn) as admin:
        admin.execute(sql.SQL('CREATE ROLE {}').format(inherited))
        admin.execute(sql.SQL('GRANT {} ON prosaic_harness_conversations.receipts TO {}').format(action, inherited))
        admin.execute(sql.SQL('GRANT {} TO {}').format(inherited, role))
    try:
        with pg.PostgresSessionStore(runtime_dsn, namespace='test') as runtime:
            with pytest.raises(StoreIncompatible):
                runtime.check_ready()
    finally:
        with psycopg.connect(db_admin_dsn) as admin:
            admin.execute(sql.SQL('REVOKE {} FROM {}').format(inherited, role))
            admin.execute(sql.SQL('DROP OWNED BY {}').format(inherited))
            admin.execute(sql.SQL('DROP ROLE {}').format(inherited))
    with pg.PostgresSessionStore(runtime_dsn, namespace='test') as runtime:
        runtime.check_ready()


def test_explicit_schema_owner_and_inherited_owner_remain_operator_credentials(db_admin_dsn, runtime_dsn):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    with pg.PostgresSessionStore(db_admin_dsn, namespace='test') as owner:
        owner.initialize()
        owner.check_ready()
        owner.initialize()
    role = sql.Identifier(conninfo_to_dict(runtime_dsn)['user'])
    with psycopg.connect(db_admin_dsn) as admin:
        schema_owner = sql.Identifier(admin.execute("SELECT pg_get_userbyid(nspowner) "
            "FROM pg_namespace WHERE nspname='prosaic_harness_conversations'").fetchone()[0])
        admin.execute(sql.SQL('GRANT {} TO {}').format(schema_owner, role))
    try:
        with pg.PostgresSessionStore(runtime_dsn, namespace='test') as member:
            member.check_ready()
            member.initialize()
    finally:
        with psycopg.connect(db_admin_dsn) as admin:
            admin.execute(sql.SQL('REVOKE {} FROM {}').format(schema_owner, role))
