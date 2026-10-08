import threading
import time
import uuid

import psycopg
import pytest
import prosaic_harness as api
from prosaic_harness.contracts import seal
from test_store import pg_store, documents


def expire(dsn, run_id):
    with psycopg.connect(dsn) as conn:
        conn.execute("UPDATE prosaic_harness.leases SET expires_at=clock_timestamp()-interval '1 second' WHERE run_id=%s", (run_id,))


def test_expired_owner_cannot_renew_without_takeover(db_admin_dsn, pg_store):
    run_id = uuid.uuid4().hex
    with pg_store.lease(run_id) as lease:
        expire(db_admin_dsn, run_id)
        with pytest.raises(api.LeaseLost):
            pg_store._transport.call(lambda conn: pg_store._renew(conn, lease), renewal=True)
        with pytest.raises(api.LeaseLost):
            lease.check_valid()


def test_old_owner_writes_and_release_cannot_affect_takeover(db_admin_dsn, pg_store, documents):
    from prosaic_harness_postgres import PostgresRunStore
    state, receipt = documents
    run_id = state['run_id']
    with PostgresRunStore(db_admin_dsn, namespace=pg_store.namespace) as other:
        with pg_store.lease(run_id) as old:
            revision = pg_store.create_run(run_id, state, old)
            with pytest.raises(api.RunBusy):
                with other.lease(run_id):
                    pass
            expire(db_admin_dsn, run_id)
            with other.lease(run_id) as new:
                for operation in [lambda: pg_store.create_run(run_id, state, old),
                                  lambda: pg_store.save_run(run_id, state, revision, old),
                                  lambda: pg_store.save_receipt(run_id, receipt['id'], receipt, old)]:
                    with pytest.raises(api.LeaseLost):
                        operation()
                pg_store._transport.call(lambda conn: pg_store._release(conn, old), renewal=True)
                assert other.save_run(run_id, state, revision, new) != revision
        with psycopg.connect(db_admin_dsn) as conn:
            assert conn.execute('SELECT generation,owner FROM prosaic_harness.leases WHERE run_id=%s', (run_id,)).fetchone() == (2, None)
        with other.lease(run_id):
            with psycopg.connect(db_admin_dsn) as conn:
                assert conn.execute('SELECT generation FROM prosaic_harness.leases WHERE run_id=%s', (run_id,)).fetchone()[0] == 3


def test_writer_uses_time_after_row_lock(db_admin_dsn, pg_store, documents):
    state, _ = documents
    run_id = state['run_id']
    with pg_store.lease(run_id) as lease:
        rev = pg_store.create_run(run_id, state, lease)
        with psycopg.connect(db_admin_dsn) as locker:
            locker.execute('SELECT * FROM prosaic_harness.leases WHERE run_id=%s FOR UPDATE', (run_id,))
            outcome = []
            def write():
                try:
                    pg_store.save_run(run_id, state, rev, lease)
                except Exception as exc:
                    outcome.append(exc)
            thread = threading.Thread(target=write)
            thread.start()
            time.sleep(.15)
            locker.execute("UPDATE prosaic_harness.leases SET expires_at=clock_timestamp()-interval '1 second' WHERE run_id=%s", (run_id,))
            locker.commit()
            thread.join(3)
        assert not thread.is_alive() and isinstance(outcome[0], api.LeaseLost)
        assert pg_store.load_run(run_id).revision == rev


def test_renewal_progresses_and_reserved_pool_works(db_admin_dsn):
    from prosaic_harness_postgres import PostgresRunStore
    with PostgresRunStore(db_admin_dsn, namespace='tenant-a', lease_s=15, renew_s=1,
                          operation_timeout_s=2, pool_size=1) as store:
        store.initialize()
        with store.lease(uuid.uuid4().hex) as lease:
            deadline = lease._deadline
            started = time.monotonic()
            while lease._deadline == deadline and time.monotonic() - started < 3:
                time.sleep(.02)
            lease.check_valid()
            assert lease._deadline > deadline
        assert not store._sessions


@pytest.mark.parametrize('kwargs', [{'lease_s': 14}, {'renew_s': 0}, {'renew_s': 21},
                                  {'operation_timeout_s': 45}, {'lease_s': float('inf')}])
def test_invalid_lease_configuration(kwargs):
    from prosaic_harness_postgres import PostgresRunStore
    with pytest.raises(ValueError):
        PostgresRunStore('unused', namespace='test', **kwargs)
