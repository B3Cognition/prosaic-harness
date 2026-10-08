import uuid
import asyncio
import threading
import time
import psycopg
import pytest
from prosaic_harness import StoreUnavailable, LeaseLost, StoreIncompatible
from prosaic_harness.contracts import seal
from support.tcp_proxy import TcpProxy


def test_lost_commit_acknowledgement_is_not_retried(db_admin_dsn):
    from prosaic_harness_postgres import PostgresRunStore
    state = seal({'run_id': uuid.uuid4().hex, 'inputs': {}})
    receipt = seal({'run_id': state['run_id'], 'id': uuid.uuid4().hex, 'events': []})
    with TcpProxy(db_admin_dsn) as proxy:
        with PostgresRunStore(proxy.dsn, namespace='fault', operation_timeout_s=1) as store:
            store.initialize()
            with pytest.raises(StoreUnavailable):
                with store.lease(state['run_id']) as lease:
                    store.create_run(state['run_id'], state, lease)
                    proxy.block_next_commit_reply()
                    with pytest.raises(StoreUnavailable) as error:
                        store.save_receipt(state['run_id'], receipt['id'], receipt, lease)
                    assert error.value.outcome_unknown
                    assert proxy.commit_sent.is_set()
                    with psycopg.connect(db_admin_dsn) as admin:
                        assert admin.execute('SELECT count(*) FROM prosaic_harness.receipts').fetchone()[0] == 1
                    with pytest.raises(LeaseLost):
                        lease.check_valid()
    with PostgresRunStore(db_admin_dsn, namespace='fault') as fresh:
        assert fresh.load_receipt(state['run_id'], receipt['id']) == receipt


def test_readiness_is_checked_on_each_reused_connection(db_admin_dsn):
    from prosaic_harness_postgres.transport import PostgresTransport
    with PostgresTransport(db_admin_dsn, pool_size=1) as transport:
        transport.call(lambda conn: conn.execute("SET synchronous_commit=off"))
        with pytest.raises(StoreIncompatible):
            transport.call(lambda conn: conn.execute('SELECT 1'))


def test_renewal_has_reserved_capacity_and_spans_original_expiry(db_admin_dsn):
    from prosaic_harness_postgres import PostgresRunStore
    with PostgresRunStore(db_admin_dsn, namespace='renewal', lease_s=15, renew_s=1,
                          operation_timeout_s=2, pool_size=1) as store:
        store.initialize()
        with store.lease(uuid.uuid4().hex) as lease:
            original = lease._deadline
            entered, release = threading.Event(), threading.Event()
            async def hold(conn):
                entered.set()
                while not release.is_set():
                    await asyncio.sleep(.01)
            outcome = []
            thread = threading.Thread(target=lambda: outcome.append(store._transport.call(hold, timeout_s=4)))
            thread.start()
            assert entered.wait(2)
            try:
                end = time.monotonic() + 1.4
                while time.monotonic() < end and lease._deadline == original:
                    time.sleep(.02)
                assert lease._deadline > original
            finally:
                release.set()
                thread.join(3)
            assert outcome == [None]
            while time.monotonic() <= original + .1:
                time.sleep(.1)
            lease.check_valid()
            assert lease._deadline > time.monotonic()


def test_network_lost_renewal_is_sticky(db_admin_dsn):
    from prosaic_harness_postgres import PostgresRunStore
    from prosaic_harness_postgres.transport import PostgresTransport
    with TcpProxy(db_admin_dsn) as proxy:
        with PostgresRunStore(proxy.dsn, namespace='renewal', lease_s=15, renew_s=1,
                              operation_timeout_s=1) as store:
            store.initialize()
            session = store.lease(uuid.uuid4().hex)
            lease = session.__enter__()
            try:
                proxy.block_server_replies()
                end = time.monotonic() + 3
                while not lease._lost and time.monotonic() < end:
                    time.sleep(.02)
                with pytest.raises(LeaseLost):
                    lease.check_valid()
                proxy.blocked.clear()
                # A fresh healthy connection still cannot revive sticky loss.
                with PostgresTransport(db_admin_dsn) as recovered:
                    with pytest.raises(LeaseLost):
                        recovered.call(lambda conn: store._renew(conn, lease), renewal=True)
            finally:
                try:
                    session.__exit__(None, None, None)
                except StoreUnavailable:
                    # Unknown release is explicitly allowed after this outage;
                    # the fixture-owned database is dropped by the test owner.
                    pass
