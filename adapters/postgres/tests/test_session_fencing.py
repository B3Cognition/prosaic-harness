"""Local ownership and SQL-boundary fencing; no database simulator."""
import asyncio
from datetime import datetime, timezone, timedelta
from dataclasses import replace
import threading
import time

import pytest
from prosaic_harness import ConversationScope, LeaseLost, SessionNotFound, StoreCorrupt
from prosaic_harness_postgres import PostgresSessionStore


def scope():
    return ConversationScope('test', 'sandbox', 'chat', 'tenant', 'actor')


def local_store():
    # Construct a real store with lazy pools: no SQL or socket until an operation.
    return PostgresSessionStore('host=127.0.0.1 port=9 dbname=unused', namespace='test')


def test_scope_cannot_cross_a_live_local_lease_before_sql():
    from prosaic_harness_postgres.session_leases import PostgresSessionLease
    with local_store() as store:
        owner = scope()
        content, identity = store._scope(owner)
        lease = PostgresSessionLease(store, 'a' * 32, content, identity, time.monotonic())
        store._sessions.add(lease)
        try:
            store._local('a' * 32, lease, owner)
            with pytest.raises(LeaseLost):
                store._local('a' * 32, lease, replace(owner, actor='foreign'))
            with pytest.raises(LeaseLost):
                store._local('b' * 32, lease, owner)
            lease.pid = -1
            with pytest.raises(LeaseLost):
                store._local('a' * 32, lease, owner)
        finally:
            store._sessions.remove(lease)


class LeaseRows:
    """Specific two-statement boundary: locked lease row and database time."""
    def __init__(self, row, now):
        self.row, self.now = row, now
        self.result = None
    async def execute(self, query, params=()):
        if query.startswith('SELECT scope_identity,owner,generation,expires_at'):
            assert params == ('test', 'a' * 32)
            self.result = self.row
        elif query == 'SELECT pg_catalog.clock_timestamp()':
            self.result = (self.now,)
        else:
            raise AssertionError('guard must not mutate or access another SQL boundary')
        return self
    async def fetchone(self):
        return self.result


@pytest.mark.parametrize('drift', ['scope', 'owner', 'generation', 'expires', 'missing'])
def test_database_lease_drift_is_sticky_and_fails_before_mutation(drift):
    from prosaic_harness_postgres.session_leases import PostgresSessionLease
    with local_store() as store:
        content, identity = store._scope(scope())
        lease = PostgresSessionLease(store, 'a' * 32, content, identity, time.monotonic())
        lease.generation = 3
        now = datetime.now(timezone.utc)
        row = [identity, lease.owner, 3, now + timedelta(seconds=30)]
        if drift == 'scope': row[0] = 'f' * 64
        elif drift == 'owner': row[1] = 'b' * 32
        elif drift == 'generation': row[2] = 4
        elif drift == 'expires': row[3] = now
        elif drift == 'missing': row = None
        with pytest.raises(LeaseLost):
            asyncio.run(store._guard_lease(LeaseRows(row, now), lease))
        assert lease._lost
        with pytest.raises(LeaseLost):
            lease.check_valid()


class SessionRows:
    def __init__(self, document):
        self.document = document
    async def execute(self, query, params):
        # Assert the SQL boundary always filters the full trusted scope digest.
        assert 'AND scope_identity=%s' in query
        assert len(params) == 3 and params[:2] == ('test', 'a' * 32)
        self.identity = params[2]
        return self
    async def fetchone(self):
        return None if self.document is None else (1, self.document)


def test_returned_snapshot_must_match_owner_and_address():
    from support.session_documents import document
    from prosaic_harness.session_contracts import encode_session
    owner = scope()
    with local_store() as store:
        foreign = document(replace(owner, actor='foreign'))
        with pytest.raises(StoreCorrupt):
            asyncio.run(store._read_session(SessionRows(encode_session(foreign).decode()), 'a' * 32, owner))
        with pytest.raises(SessionNotFound):
            asyncio.run(store._read_session(SessionRows(None), 'a' * 32, owner))


def test_capacity_is_held_once_during_renewal_registration(monkeypatch):
    from prosaic_harness_postgres import session_store as implementation
    acquired = []
    fixture = object.__new__(PostgresSessionStore)
    fixture._namespace = 'test'
    fixture._mutex = threading.RLock()
    fixture._sessions, fixture._reservations = set(), set()
    fixture._max_active_leases = 2
    class Lease:
        def __init__(self, store, sid, content, identity, started):
            self.session_id = sid
            self._stopped = threading.Event()
            self._stopped.set()
        def check_valid(self): pass
        def stop(self): pass
        async def maintain(self): pass
    class Transport:
        nested = False
        def _check_process(self): pass
        def call(self, *args, **kwargs): return 1
        def submit(self, coroutine):
            coroutine.close()
            if not self.nested:
                self.nested = True
                with fixture.lease('b' * 32, scope=scope()):
                    acquired.append('second')
    fixture._transport = Transport()
    monkeypatch.setattr(implementation, 'PostgresSessionLease', Lease)
    with fixture.lease('a' * 32, scope=scope()):
        acquired.append('first')
    assert acquired == ['second', 'first']
    assert fixture._sessions == set() and fixture._reservations == set()
