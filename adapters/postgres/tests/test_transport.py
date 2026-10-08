import asyncio
import threading
import time

import pytest
from prosaic_harness import StoreUnavailable, StoreBusy, StoreIncompatible


def transport(dsn, **kwargs):
    from prosaic_harness_postgres.transport import PostgresTransport
    return PostgresTransport(dsn, **kwargs)


def test_real_query_commits_before_return(db_admin_dsn):
    import psycopg
    with transport(db_admin_dsn) as t:
        t.call(lambda conn: conn.execute('CREATE TABLE public.transport_probe(id INTEGER)'))
        with psycopg.connect(db_admin_dsn) as other:
            assert other.execute("SELECT to_regclass('public.transport_probe')").fetchone()[0] is not None


def test_server_wait_has_client_deadline_and_safe_cleanup(db_admin_dsn):
    with transport(db_admin_dsn, operation_timeout_s=1) as t:
        started = time.monotonic()
        with pytest.raises(StoreUnavailable):
            t.call(lambda conn: conn.execute('SELECT pg_sleep(20)'))
        assert time.monotonic() - started < 2
        assert t.pending_operations == 0
        assert t.call(lambda conn: conn.execute('SELECT 1')) is not None


def test_pool_capacity_and_active_close(db_admin_dsn):
    with transport(db_admin_dsn, pool_size=1, pool_timeout_s=0.2) as t:
        entered, release = threading.Event(), threading.Event()
        async def holding(conn):
            entered.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
        outcome = []
        thread = threading.Thread(target=lambda: outcome.append(t.call(holding)))
        thread.start()
        assert entered.wait(5)
        try:
            with pytest.raises(StoreBusy):
                t.close()
            with pytest.raises(StoreUnavailable):
                t.call(lambda conn: conn.execute('SELECT 1'))
        finally:
            release.set()
            thread.join(5)
        assert not thread.is_alive() and outcome == [None]


@pytest.mark.parametrize('options,error', [('-c synchronous_commit=off', StoreIncompatible),
                                           ('-c default_transaction_read_only=on', StoreUnavailable)])
def test_unsafe_session_is_rejected(db_admin_dsn, options, error):
    from psycopg.conninfo import make_conninfo
    with transport(make_conninfo(db_admin_dsn, options=options)) as t:
        with pytest.raises(error):
            t.call(lambda conn: conn.execute('SELECT 1'))


def test_invalid_dsn_never_discloses_credentials():
    from prosaic_harness_postgres.transport import PostgresTransport
    secret = 'SYNTHETIC_SECRET_SENTINEL'
    with pytest.raises((StoreUnavailable, ValueError)) as error:
        PostgresTransport('invalid_dsn_' + secret)
    assert secret not in str(error.value)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 0, -1, True])
def test_invalid_timing_fails_before_io(value):
    from prosaic_harness_postgres.transport import PostgresTransport
    with pytest.raises(ValueError):
        PostgresTransport('unused', operation_timeout_s=value)


def test_network_blackhole_has_client_deadline(db_admin_dsn):
    from support.tcp_proxy import TcpProxy
    with TcpProxy(db_admin_dsn) as proxy:
        with transport(proxy.dsn, operation_timeout_s=1) as t:
            t.call(lambda conn: conn.execute('SELECT 1'))
            proxy.block_server_replies()
            started = time.monotonic()
            with pytest.raises(StoreUnavailable):
                t.call(lambda conn: conn.execute('SELECT 1'))
            assert time.monotonic() - started < 2
            assert t.pending_operations == 0
        assert not asyncio.all_tasks(t._loop), 'owned pool tasks survived store shutdown'


def test_queued_request_prevents_close(db_admin_dsn, monkeypatch):
    t = transport(db_admin_dsn)
    blocked, release, submitted = threading.Event(), threading.Event(), threading.Event()
    def block_loop():
        blocked.set()
        release.wait(2)
    t._loop.call_soon_threadsafe(block_loop)
    assert blocked.wait(2)
    submit = asyncio.run_coroutine_threadsafe
    def submit_and_signal(*args):
        future = submit(*args)
        submitted.set()
        return future
    monkeypatch.setattr(asyncio, 'run_coroutine_threadsafe', submit_and_signal)
    outcome = []
    def run():
        try:
            outcome.append(t.call(lambda conn: conn.execute('SELECT 1')))
        except Exception as exc:
            outcome.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    assert submitted.wait(2)
    try:
        with pytest.raises(StoreBusy):
            t.close()
    finally:
        release.set()
        thread.join(5)
        t.close()
    assert outcome and not isinstance(outcome[0], Exception)


def test_unreachable_database_is_bounded_and_redacted(caplog):
    import socket
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    with transport(f'postgresql://synthetic:SECRET_SENTINEL@127.0.0.1:{port}/none',
                   operation_timeout_s=1) as t:
        started = time.monotonic()
        with pytest.raises(StoreUnavailable) as error:
            t.call(lambda conn: conn.execute('SELECT 1'))
        assert time.monotonic() - started < 2
        assert 'SECRET_SENTINEL' not in str(error.value) + caplog.text
    t.close()


def test_inherited_transport_fails_before_touching_thread(db_admin_dsn):
    import multiprocessing
    ctx = multiprocessing.get_context('fork')
    with transport(db_admin_dsn) as t:
        parent, child = ctx.Pipe()
        def inherited():
            try:
                t.call(lambda conn: conn.execute('SELECT 1'))
            except StoreBusy:
                child.send('rejected')
        worker = ctx.Process(target=inherited)
        worker.start()
        try:
            assert parent.poll(3) and parent.recv() == 'rejected'
            worker.join(3)
            assert worker.exitcode == 0
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join(3)


def test_queued_deadlines_retain_bounded_capacity_until_actual_drain(db_admin_dsn):
    t = transport(db_admin_dsn, pool_size=1, max_active_leases=1, operation_timeout_s=.2)
    blocked, release, executed = threading.Event(), threading.Event(), threading.Event()
    warnings, results = [], []
    t._loop.set_exception_handler(lambda loop, context: warnings.append(context))
    def block_loop():
        blocked.set()
        release.wait(3)
    t._loop.call_soon_threadsafe(block_loop)
    assert blocked.wait(2)
    async def query(conn):
        executed.set()
        return await conn.execute('SELECT 1')
    def request():
        try:
            t.call(query)
        except Exception as exc:
            results.append(exc)
    callers = [threading.Thread(target=request) for _ in range(6)]
    try:
        for caller in callers:
            caller.start()
        for caller in callers:
            caller.join(1)
            assert not caller.is_alive()
        assert sum(isinstance(exc, StoreBusy) for exc in results) == 2
        assert sum(isinstance(exc, StoreUnavailable) for exc in results) == 4
        assert t.pending_operations == 4, 'timed-out submissions retired before loop teardown'
        with pytest.raises(StoreBusy):
            t.close()
    finally:
        release.set()
        end = time.monotonic() + 2
        while t.pending_operations and time.monotonic() < end:
            time.sleep(.01)
        t.close()
    assert not executed.is_set(), 'expired queued request reached SQL callback'
    assert not warnings, 'outer submitted coroutine exceptions were not observed'
