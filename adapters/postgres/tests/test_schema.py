from concurrent.futures import ThreadPoolExecutor

import pytest
from prosaic_harness import StoreUninitialized, StoreIncompatible


def initialized(dsn):
    from prosaic_harness_postgres.transport import PostgresTransport
    from prosaic_harness_postgres.schema import initialize
    t = PostgresTransport(dsn)
    try:
        initialize(t)
    except BaseException:
        t.close()
        raise
    return t


def test_readiness_does_not_implicitly_initialize(db_admin_dsn):
    from prosaic_harness_postgres.transport import PostgresTransport
    from prosaic_harness_postgres.schema import check_ready
    with PostgresTransport(db_admin_dsn) as t:
        with pytest.raises(StoreUninitialized):
            check_ready(t)


def test_initialization_is_repeatable_and_parallel(db_admin_dsn):
    from prosaic_harness_postgres.schema import initialize, check_ready
    def run():
        with initialized(db_admin_dsn) as t:
            initialize(t)
            check_ready(t)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: run(), range(2)))


def test_newer_schema_is_rejected(db_admin_dsn):
    import psycopg
    from prosaic_harness_postgres.schema import initialize, check_ready
    with initialized(db_admin_dsn) as t:
        with psycopg.connect(db_admin_dsn) as admin:
            admin.execute('UPDATE prosaic_harness.schema_version SET schema_version=99')
        with pytest.raises(StoreIncompatible):
            check_ready(t)
        with pytest.raises(StoreIncompatible):
            initialize(t)


def test_unlogged_table_is_rejected(db_admin_dsn):
    import psycopg
    from prosaic_harness_postgres.schema import check_ready
    with initialized(db_admin_dsn) as t:
        with psycopg.connect(db_admin_dsn) as admin:
            admin.execute('ALTER TABLE prosaic_harness.receipts SET UNLOGGED')
        with pytest.raises(StoreIncompatible):
            check_ready(t)


def test_runtime_role_needs_explicit_grants(db_admin_dsn, runtime_dsn):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    from prosaic_harness_postgres.transport import PostgresTransport
    from prosaic_harness_postgres.schema import check_ready
    with initialized(db_admin_dsn):
        pass
    role = sql.Identifier(conninfo_to_dict(runtime_dsn)['user'])
    with PostgresTransport(runtime_dsn) as t:
        with pytest.raises(StoreIncompatible):
            check_ready(t)
        with psycopg.connect(db_admin_dsn) as admin:
            admin.execute(sql.SQL('GRANT USAGE ON SCHEMA prosaic_harness TO {}').format(role))
            admin.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA prosaic_harness TO {}').format(role))
            admin.execute(sql.SQL('GRANT INSERT, UPDATE ON prosaic_harness.runs, prosaic_harness.leases TO {}').format(role))
            admin.execute(sql.SQL('GRANT INSERT ON prosaic_harness.receipts TO {}').format(role))
        check_ready(t)


def test_damaged_constraints_are_not_accepted_as_version_one(db_admin_dsn):
    import psycopg
    from prosaic_harness_postgres.schema import check_ready
    with initialized(db_admin_dsn) as t:
        with psycopg.connect(db_admin_dsn) as admin:
            admin.execute('ALTER TABLE prosaic_harness.runs DROP CONSTRAINT runs_namespace_run_id_fkey')
        with pytest.raises(StoreIncompatible):
            check_ready(t)


def test_nullable_document_is_not_accepted(db_admin_dsn):
    import psycopg
    from prosaic_harness_postgres.schema import check_ready
    with initialized(db_admin_dsn) as t:
        with psycopg.connect(db_admin_dsn) as admin:
            admin.execute('ALTER TABLE prosaic_harness.runs ALTER COLUMN document DROP NOT NULL')
        with pytest.raises(StoreIncompatible):
            check_ready(t)
