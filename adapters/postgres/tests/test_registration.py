"""Deterministic registration race against an explicitly owned PostgreSQL DB."""
import asyncio
import os
import sys
import threading
import time
import uuid

import pytest
from prosaic_harness import StoreBusy, StoreUnavailable
from prosaic_harness_postgres import PostgresRunStore


@pytest.fixture
def local_store(monkeypatch):
    """Use real session/renewal lifecycle with only database I/O replaced."""
    store = object.__new__(PostgresRunStore)
    store._pid = os.getpid()
    store._mutex = threading.RLock()
    store._sessions = set()
    store._reservations = set()
    store._max_active_leases = 1
    store.lease_s, store.renew_s = 15, 3
    owners = {}
    class Transport:
        operation_timeout_s = .2
        def __init__(self):
            self._loop = asyncio.new_event_loop()
            self.thread = threading.Thread(target=self._loop.run_forever, daemon=True)
            self.thread.start()
        def _check_process(self): pass
        def call(self, callback, **kwargs):
            return asyncio.run(callback(None))
        def submit(self, coroutine):
            return asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        def close(self):
            self._loop.call_soon_threadsafe(self._loop.stop)
            self.thread.join(3)
            assert not self.thread.is_alive()
            self._loop.close()
    transport = store._transport = Transport()
    async def acquire(conn, session):
        owners[session.run_id] = session.owner
        return 1
    async def release(conn, session):
        assert session._stopped.is_set(), 'release raced renewal teardown'
        owners.pop(session.run_id, None)
    monkeypatch.setattr(store, '_acquire', acquire)
    monkeypatch.setattr(store, '_release', release)
    try:
        yield store, owners
    finally:
        try:
            for session in store._sessions:
                if session._task is not None:
                    session.stop()
        finally:
            if not transport._loop.is_closed():
                transport.close()


@pytest.mark.parametrize('error_type', [RuntimeError, KeyboardInterrupt])
@pytest.mark.parametrize('started', [False, True])
def test_failed_renewal_submission_releases_ownership_and_capacity(
        monkeypatch, local_store, error_type, started):
    store, owners = local_store
    original = store._transport.submit
    primary = error_type('renewal submission interrupted')
    submitted = []
    def fail(coroutine):
        submitted.append(coroutine)
        if started:
            original(coroutine)
            until = time.monotonic() + 2
            while next(iter(store._sessions))._task is None and time.monotonic() < until:
                time.sleep(.005)
            assert next(iter(store._sessions))._task is not None
        raise primary
    monkeypatch.setattr(store._transport, 'submit', fail)
    with pytest.raises(error_type) as caught:
        with store.lease(uuid.uuid4().hex):
            pytest.fail('failed setup must never yield an execution session')
    assert caught.value is primary
    assert owners == {}
    assert submitted[0].cr_frame is None
    monkeypatch.setattr(store._transport, 'submit', original)
    with store.lease(uuid.uuid4().hex):
        pass
    store.close()


def test_failed_session_construction_releases_capacity(monkeypatch, local_store):
    from prosaic_harness_postgres import store as implementation
    store, _ = local_store
    original = implementation.PostgresLease
    def fail(*args):
        raise KeyboardInterrupt('session construction interrupted')
    monkeypatch.setattr(implementation, 'PostgresLease', fail)
    with pytest.raises(KeyboardInterrupt):
        with store.lease(uuid.uuid4().hex):
            pytest.fail('failed construction must not yield')
    monkeypatch.setattr(implementation, 'PostgresLease', original)
    with store.lease(uuid.uuid4().hex):
        pass
    store.close()


@pytest.mark.parametrize('boundary', ['after_reservation', 'after_registration'])
def test_statement_boundary_interrupt_preserves_one_slot_capacity(local_store, boundary):
    store, owners = local_store
    hit = []
    code = PostgresRunStore.lease.__wrapped__.__code__
    previous_trace = sys.gettrace()
    def trace(frame, event, arg):
        if event == 'line' and frame.f_code is code and not hit:
            reservations = store._reservations
            if ((boundary == 'after_reservation'
                    and reservations and not store._sessions)
                    or (boundary == 'after_registration'
                        and store._sessions)):
                hit.append(frame.f_lineno)
                raise KeyboardInterrupt('statement boundary interrupted')
        return trace
    sys.settrace(trace)
    try:
        with pytest.raises(KeyboardInterrupt):
            with store.lease(uuid.uuid4().hex):
                pytest.fail('interrupted setup must not yield')
    finally:
        sys.settrace(previous_trace)
    assert hit, 'interruption boundary was not exercised'
    assert owners == {}
    with store.lease(uuid.uuid4().hex):
        with pytest.raises(StoreBusy):
            with store.lease(uuid.uuid4().hex):
                pytest.fail('one-slot store admitted two simultaneous sessions')
    store.close()


@pytest.mark.parametrize('boundary', ['registration', 'registered', 'renewal_construction'])
def test_interrupted_setup_boundary_releases_ownership(monkeypatch, local_store, boundary):
    from prosaic_harness_postgres.leases import PostgresLease
    store, owners = local_store
    original = PostgresLease.maintain
    class InterruptedRegistration(set):
        interrupted = False
        def add(self, session):
            if self.interrupted:
                return super().add(session)
            self.interrupted = True
            if boundary == 'registered':
                super().add(session)
            raise KeyboardInterrupt('registration interrupted')
    def fail(session):
        raise KeyboardInterrupt('renewal construction interrupted')
    if boundary in {'registration', 'registered'}:
        store._sessions = InterruptedRegistration()
    else:
        monkeypatch.setattr(PostgresLease, 'maintain', fail)
    with pytest.raises(KeyboardInterrupt):
        with store.lease(uuid.uuid4().hex):
            pytest.fail('interrupted setup must not yield')
    assert owners == {}
    monkeypatch.setattr(PostgresLease, 'maintain', original)
    with store.lease(uuid.uuid4().hex):
        pass
    store.close()


@pytest.mark.parametrize('cleanup_type', [RuntimeError, KeyboardInterrupt])
def test_failed_setup_preserves_primary_when_release_fails(
        monkeypatch, local_store, cleanup_type):
    store, owners = local_store
    original = store._transport.submit
    primary = KeyboardInterrupt('primary setup failure')
    def fail(coroutine):
        raise primary
    async def fail_release(conn, session):
        raise cleanup_type('secondary cleanup failure')
    monkeypatch.setattr(store._transport, 'submit', fail)
    monkeypatch.setattr(store, '_release', fail_release)
    with pytest.raises(KeyboardInterrupt) as caught:
        with store.lease(uuid.uuid4().hex):
            pytest.fail('failed setup must not yield')
    assert caught.value is primary
    assert any('cleanup failed' in note for note in getattr(primary, '__notes__', []))
    assert len(owners) == 1  # Failed release does not imply database ownership ended.
    async def release(conn, session):
        owners.pop(session.run_id, None)
    monkeypatch.setattr(store, '_release', release)
    monkeypatch.setattr(store._transport, 'submit', original)
    with store.lease(uuid.uuid4().hex):
        pass
    store.close()


def test_uncertain_acquisition_is_not_retried_or_released(monkeypatch, local_store):
    store, _ = local_store
    primary = StoreUnavailable('commit uncertain', outcome_unknown=True)
    calls = []
    async def uncertain(conn, session):
        calls.append('acquire')
        raise primary
    async def release(conn, session):
        calls.append('release')
    monkeypatch.setattr(store, '_acquire', uncertain)
    monkeypatch.setattr(store, '_release', release)
    with pytest.raises(StoreUnavailable) as caught:
        with store.lease(uuid.uuid4().hex):
            pytest.fail('uncertain acquisition must not yield')
    assert caught.value is primary and caught.value.outcome_unknown
    assert calls == ['acquire']
    store.close()


def test_queued_submission_interruption_drains_before_release(monkeypatch, local_store):
    store, owners = local_store
    entered, release = threading.Event(), threading.Event()
    loop = store._transport._loop
    original_schedule = loop.call_soon_threadsafe
    original_submit = store._transport.submit
    def block():
        entered.set()
        assert release.wait(2)
    original_schedule(block)
    assert entered.wait(2)
    def schedule(callback, *args, **kwargs):
        handle = original_schedule(callback, *args, **kwargs)
        if callback.__name__ == 'cancel':
            release.set()
        return handle
    def fail(coroutine):
        original_submit(coroutine)
        raise KeyboardInterrupt('submitted but not started')
    monkeypatch.setattr(loop, 'call_soon_threadsafe', schedule)
    monkeypatch.setattr(store._transport, 'submit', fail)
    try:
        with pytest.raises(KeyboardInterrupt):
            with store.lease(uuid.uuid4().hex):
                pytest.fail('queued setup failure must not yield')
        assert owners == {}
        monkeypatch.setattr(store._transport, 'submit', original_submit)
        with store.lease(uuid.uuid4().hex):
            pass
        store.close()
    finally:
        release.set()


def test_undrained_setup_keeps_capacity_and_database_ownership(monkeypatch, local_store):
    from prosaic_harness_postgres.leases import PostgresLease
    store, owners = local_store
    original_stop = PostgresLease.stop
    primary = RuntimeError('setup failed')
    def fail(coroutine):
        raise primary
    def cannot_drain(session):
        raise StoreBusy('runner has not drained')
    monkeypatch.setattr(store._transport, 'submit', fail)
    monkeypatch.setattr(PostgresLease, 'stop', cannot_drain)
    with pytest.raises(RuntimeError) as caught:
        with store.lease(uuid.uuid4().hex):
            pytest.fail('undrained setup must not yield')
    assert caught.value is primary
    assert len(owners) == 1
    assert any('cleanup failed' in note for note in getattr(primary, '__notes__', []))
    assert not next(iter(store._sessions))._active
    with pytest.raises(StoreBusy):
        with store.lease(uuid.uuid4().hex):
            pytest.fail('undrained session must retain capacity')
    with pytest.raises(StoreBusy):
        store.close()
    monkeypatch.setattr(PostgresLease, 'stop', original_stop)
    session = next(iter(store._sessions))
    session.stop()


def test_invalid_session_after_acquire_releases_ownership(monkeypatch, local_store):
    from prosaic_harness import LeaseLost
    from prosaic_harness_postgres.leases import PostgresLease
    store, owners = local_store
    original = PostgresLease.check_valid
    def invalid(session):
        raise LeaseLost('setup validity expired')
    monkeypatch.setattr(PostgresLease, 'check_valid', invalid)
    with pytest.raises(LeaseLost):
        with store.lease(uuid.uuid4().hex):
            pytest.fail('invalid acquisition must not yield')
    assert owners == {}
    monkeypatch.setattr(PostgresLease, 'check_valid', original)
    with store.lease(uuid.uuid4().hex):
        pass
    store.close()


@pytest.mark.parametrize('error_type', [RuntimeError, KeyboardInterrupt])
@pytest.mark.parametrize('submitted', [False, True])
def test_native_failed_setup_releases_fenced_owner(monkeypatch, db_admin_dsn,
                                                   error_type, submitted):
    import psycopg
    namespace, run_id = uuid.uuid4().hex, uuid.uuid4().hex
    with PostgresRunStore(db_admin_dsn, namespace=namespace, max_active_leases=1,
                          lease_s=15, renew_s=3, operation_timeout_s=5) as store:
        store.initialize()
        original = store._transport.submit
        def fail(coroutine):
            if submitted:
                original(coroutine)
            raise error_type('native renewal submission failed')
        monkeypatch.setattr(store._transport, 'submit', fail)
        with pytest.raises(error_type):
            with store.lease(run_id):
                pytest.fail('failed native setup must not yield')
        with psycopg.connect(db_admin_dsn) as conn:
            assert conn.execute('SELECT owner,generation,expires_at FROM '
                'prosaic_harness.leases WHERE namespace=%s AND run_id=%s',
                (namespace, run_id)).fetchone() == (None, 1, None)
        monkeypatch.setattr(store._transport, 'submit', original)
        with store.lease(run_id) as session:
            assert session.generation == 2
        with store.lease(uuid.uuid4().hex):
            pass
    assert store._transport._closed


def test_unit_registration_boundary_has_capacity_and_releases_all_counts(monkeypatch):
    from prosaic_harness_postgres import store as implementation
    acquired = []
    fixture = object.__new__(PostgresRunStore)
    fixture._mutex = threading.RLock()
    fixture._sessions = set()
    fixture._reservations = set()
    fixture._max_active_leases = 2
    class Lease:
        def __init__(self,store,run_id,started):
            self.run_id = run_id
            self._stopped = threading.Event()
            self._stopped.set()
        def check_valid(self): pass
        def stop(self): pass
        async def maintain(self): pass
    class Transport:
        nested = False
        def _check_process(self): pass
        def call(self,*args,**kwargs): return 1
        def submit(self,coroutine):
            coroutine.close()
            if not self.nested:
                self.nested = True
                with fixture.lease(uuid.uuid4().hex):
                    acquired.append('second')
    fixture._transport = Transport()
    monkeypatch.setattr(implementation,'PostgresLease',Lease)
    with fixture.lease(uuid.uuid4().hex):
        acquired.append('first')
    assert acquired == ['second','first']
    assert fixture._reservations == set()
    assert fixture._sessions == set()


def test_one_registering_session_does_not_consume_two_capacity_slots(monkeypatch,db_admin_dsn):
    entered,release = threading.Event(),threading.Event()
    errors = []
    with PostgresRunStore(db_admin_dsn,namespace=uuid.uuid4().hex,max_active_leases=2,
                         lease_s=15,renew_s=3,operation_timeout_s=5) as store:
        store.initialize()  # Explicit provisioning in this fixture-owned database.
        original = store._transport.submit
        def scheduling_boundary(coroutine,*args,**kwargs):
            if threading.current_thread().name == 'registration-first':
                entered.set()
                release.wait(5)
            return original(coroutine,*args,**kwargs)
        monkeypatch.setattr(store._transport,'submit',scheduling_boundary)
        def first():
            try:
                with store.lease(uuid.uuid4().hex): pass
            except Exception as error:
                errors.append(type(error).__name__)
        worker = threading.Thread(target=first,name='registration-first')
        worker.start()
        try:
            assert entered.wait(2), 'first session did not reach registration boundary'
            # There is one registering execution and capacity for two. This
            # must not reject because that one session is counted twice.
            with store.lease(uuid.uuid4().hex): pass
        finally:
            release.set()
            worker.join(10)
        assert not worker.is_alive()
        assert errors == []
