"""Deterministic registration race against an explicitly owned PostgreSQL DB."""
import os
import threading
import uuid
import pytest
from prosaic_harness_postgres import PostgresRunStore


def test_unit_registration_boundary_has_capacity_and_releases_all_counts(monkeypatch):
    from prosaic_harness_postgres import store as implementation
    acquired = []
    fixture = object.__new__(PostgresRunStore)
    fixture._mutex = threading.RLock()
    fixture._sessions = set()
    fixture._acquiring = 0
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
    assert fixture._acquiring == 0
    assert fixture._sessions == set()


def test_one_registering_session_does_not_consume_two_capacity_slots(monkeypatch):
    dsn = os.environ.get('HARNESS_EXISTING_RUNTIME_DSN')
    if not dsn:
        pytest.fail('an owned pre-provisioned Harness runtime DSN is required')
    entered,release = threading.Event(),threading.Event()
    errors = []
    with PostgresRunStore(dsn,namespace=uuid.uuid4().hex,max_active_leases=2,
                         lease_s=15,renew_s=3,operation_timeout_s=5) as store:
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
