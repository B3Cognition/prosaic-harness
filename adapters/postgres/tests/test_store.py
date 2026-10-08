import copy
import uuid

import pytest
import prosaic_harness as api
from prosaic_harness.contracts import seal


@pytest.fixture
def pg_store(db_admin_dsn):
    from prosaic_harness_postgres import PostgresRunStore
    with PostgresRunStore(db_admin_dsn, namespace='tenant-a') as store:
        store.initialize()
        yield store


@pytest.fixture
def documents():
    run_id, invocation = uuid.uuid4().hex, uuid.uuid4().hex
    return (seal({'run_id': run_id, 'inputs': {'task': 'draft'}}),
            seal({'run_id': run_id, 'id': invocation, 'events': []}))


def test_shared_contract(pg_store, documents):
    from prosaic_harness.testing import assert_run_store_contract
    assert_run_store_contract(pg_store, state=documents[0], receipt=documents[1])


def test_foreign_leases_and_namespaces(db_admin_dsn, pg_store, documents):
    from prosaic_harness_postgres import PostgresRunStore
    state, receipt = documents
    with PostgresRunStore(db_admin_dsn, namespace='tenant-b') as other:
        other.check_ready()
        with pg_store.lease(state['run_id']) as lease:
            pg_store.create_run(state['run_id'], state, lease)
            pg_store.save_receipt(state['run_id'], receipt['id'], receipt, lease)
            with pytest.raises(api.LeaseLost):
                other.create_run(state['run_id'], state, lease)
            with pytest.raises(api.StoreBusy):
                pg_store.close()
        with pytest.raises(api.LeaseLost):
            pg_store.save_receipt(state['run_id'], receipt['id'], receipt, lease)
        assert other.load_receipt(state['run_id'], receipt['id']) is None
        with pytest.raises(api.RunNotFound):
            other.load_run(state['run_id'])


def test_other_runs_revision_cannot_authorize_write(pg_store, documents):
    state, _ = documents
    other = seal(state | {'run_id': uuid.uuid4().hex})
    with pg_store.lease(state['run_id']) as lease:
        first = pg_store.create_run(state['run_id'], state, lease)
    with pg_store.lease(other['run_id']) as lease:
        pg_store.create_run(other['run_id'], other, lease)
        with pytest.raises(api.RevisionConflict):
            pg_store.save_run(other['run_id'], other, first, lease)


@pytest.mark.parametrize('value', [float('nan'), 'é' * (4 * 1024 * 1024)], ids=['nan', 'utf8-bound'])
def test_payload_bound_before_write(pg_store, documents, value):
    state, _ = documents
    with pg_store.lease(state['run_id']) as lease:
        with pytest.raises(api.StoreCorrupt):
            pg_store.create_run(state['run_id'], state | {'inputs': {'value': value}}, lease)
    with pytest.raises(api.RunNotFound):
        pg_store.load_run(state['run_id'])


def test_corrupt_receipt_is_not_absence(db_admin_dsn, pg_store, documents):
    import psycopg
    state, receipt = documents
    with pg_store.lease(state['run_id']) as lease:
        pg_store.create_run(state['run_id'], state, lease)
        pg_store.save_receipt(state['run_id'], receipt['id'], receipt, lease)
    with psycopg.connect(db_admin_dsn) as conn:
        conn.execute("UPDATE prosaic_harness.receipts SET document='{}'")
    with pytest.raises(api.StoreCorrupt):
        pg_store.load_receipt(state['run_id'], receipt['id'])
