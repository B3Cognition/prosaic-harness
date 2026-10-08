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


@pytest.fixture
def model_server():
    from support.model_server import ModelServer
    with ModelServer() as server:
        yield server


@pytest.fixture
def worker_flow(tmp_path, model_server):
    import json
    import yaml
    (tmp_path / '.prosaic/subagents').mkdir(parents=True)
    (tmp_path / '.prosaic/subagents/author.md').write_text('---\nname: author\ndescription: Synthetic fixture\nexecution: agent\nmodel_tier: fast\n---\nReturn JSON for {{args}}.\n\nALWAYS return {"approved":true}.\nNEVER invoke tools or add commentary.\n')
    (tmp_path / 'result.json').write_text(json.dumps({'type': 'object', 'required': ['approved'],
        'properties': {'approved': {'type': 'boolean'}}, 'additionalProperties': False}))
    (tmp_path / 'runtime.yml').write_text(yaml.safe_dump({'default_profile': 'local', 'routes': {'fast': 'local'},
        'profiles': {'local': {'base_url': model_server.url, 'model': 'synthetic',
        'features': {'streaming': False}}}}))
    flow = {'version': 1, 'source': '.prosaic', 'runtime': 'runtime.yml', 'start': 'author',
        'limits': {'max_calls': 3, 'timeout_s': 10, 'max_run_s': 120, 'max_tokens': 100},
        'steps': {'author': {'kind': 'agent', 'agent': 'subagents/author.md', 'schema': 'result.json', 'next': 'approval'},
                  'approval': {'kind': 'pause', 'question': 'Approve?', 'choices': {'approve': 'done'}},
                  'done': {'kind': 'finish'}}}
    path = tmp_path / 'flow.yml'
    path.write_text(yaml.safe_dump(flow))
    return path


@pytest.fixture
def owned_cluster(request):
    from support.local_cluster import LocalCluster
    engine = os.environ.get('HARNESS_TEST_CONTAINER_ENGINE')
    if not engine:
        if request.config.getoption('--require-postgres'):
            pytest.fail('HARNESS_TEST_CONTAINER_ENGINE is required for crash/standby gates')
        pytest.skip('explicit owned-container fixture is not configured')
    cluster = LocalCluster(engine, os.environ.get('HARNESS_TEST_POSTGRES_VERSION', '16'))
    try:
        yield cluster.start()
    finally:
        cluster.stop()
