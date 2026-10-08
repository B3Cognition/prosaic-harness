import uuid
import psycopg
import pytest
from prosaic_harness import StoreIncompatible, StoreUnavailable
from prosaic_harness.contracts import seal


def test_acknowledged_documents_survive_database_crash(owned_cluster):
    from prosaic_harness_postgres import PostgresRunStore
    state = seal({'run_id': uuid.uuid4().hex, 'inputs': {}})
    receipt = seal({'run_id': state['run_id'], 'id': uuid.uuid4().hex, 'events': []})
    with PostgresRunStore(owned_cluster.dsn, namespace='durable') as store:
        store.initialize()
        with store.lease(state['run_id']) as lease:
            revision = store.create_run(state['run_id'], state, lease)
            store.save_receipt(state['run_id'], receipt['id'], receipt, lease)
    owned_cluster.crash_restart()
    with PostgresRunStore(owned_cluster.dsn, namespace='durable') as fresh:
        fresh.check_ready()
        assert fresh.load_run(state['run_id']).revision == revision
        assert fresh.load_receipt(state['run_id'], receipt['id']) == receipt


def test_stale_standby_is_never_authoritative(owned_cluster):
    from prosaic_harness_postgres import PostgresRunStore
    state = seal({'run_id': uuid.uuid4().hex, 'inputs': {}})
    with PostgresRunStore(owned_cluster.dsn, namespace='routing') as store:
        store.initialize()
    standby = owned_cluster.start_standby()
    with psycopg.connect(standby, autocommit=True) as admin:
        admin.execute('SELECT pg_wal_replay_pause()')
    with PostgresRunStore(owned_cluster.dsn, namespace='routing') as store:
        with store.lease(state['run_id']) as lease:
            store.create_run(state['run_id'], state, lease)
    with psycopg.connect(standby, autocommit=True) as admin:
        assert admin.execute('SELECT count(*) FROM prosaic_harness.runs').fetchone()[0] == 0
    with PostgresRunStore(standby, namespace='routing', operation_timeout_s=1) as routed:
        with pytest.raises((StoreIncompatible, StoreUnavailable)):
            routed.load_run(state['run_id'])


@pytest.mark.parametrize('setting', ['fsync', 'full_page_writes'])
def test_unsafe_server_settings_fail_before_run_access(owned_cluster, setting):
    from prosaic_harness_postgres import PostgresRunStore
    owned_cluster.set_setting(setting, 'off')
    with PostgresRunStore(owned_cluster.dsn, namespace='unsafe') as store:
        with pytest.raises(StoreIncompatible):
            store.check_ready()
