"""Integration runs only against an explicitly supplied disposable test cluster."""
import os
import uuid

import pytest


def pytest_addoption(parser):
    parser.addoption('--require-postgres', action='store_true', help='fail instead of skipping database tests')


@pytest.fixture
def db_admin_dsn(request):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    base = os.environ.get('HARNESS_TEST_DATABASE_URL')
    if not base:
        if request.config.getoption('--require-postgres'):
            pytest.fail('HARNESS_TEST_DATABASE_URL is required for the integration lane')
        pytest.skip('explicit disposable PostgreSQL fixture is not configured')
    name = 'harness_test_' + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        yield make_conninfo(base, dbname=name)
    finally:
        # This name was generated and created by this fixture, never caller supplied.
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


@pytest.fixture
def runtime_dsn(db_admin_dsn):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    role = 'harness_role_' + uuid.uuid4().hex
    with psycopg.connect(db_admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(role)))
    try:
        yield make_conninfo(db_admin_dsn, user=role)
    finally:
        with psycopg.connect(db_admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
