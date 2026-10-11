"""Owner-filtered, fenced SessionStore; no transaction spans host execution."""
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import os
import re
import threading
import time

from prosaic_harness import (ConversationScope, SessionSnapshot, SessionNotFound,
    SessionAlreadyExists, SessionBusy, StoreBusy, StoreCorrupt, StoreUnavailable,
    LeaseLost, RevisionConflict, ReceiptConflict)
from prosaic_harness.run_store import validate_namespace, validate_id, validate_revision
from prosaic_harness.session_codec import encode, decode, digest
from prosaic_harness.session_contracts import (encode_session, decode_session, verify_receipt,
    match_receipt, validate_session_transition)
from .transport import PostgresTransport, positive
from .session_leases import PostgresSessionLease
from . import session_schema


class PostgresSessionStore:
    durable = True

    @classmethod
    def from_env(cls, name, *, namespace, **kwargs):
        if type(name) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', name):
            raise ValueError('dsn environment name must be a bounded identifier')
        dsn = os.environ.get(name)
        if not dsn:
            raise StoreUnavailable('required database environment variable is missing')
        return cls(dsn, namespace=namespace, **kwargs)

    def __init__(self, dsn, *, namespace, lease_s=60, renew_s=15,
                 operation_timeout_s=10, pool_timeout_s=5, connect_timeout_s=5,
                 lock_timeout_s=1, statement_timeout_s=5, pool_size=8, max_active_leases=4):
        self._namespace = validate_namespace(namespace)
        positive(lease_s, 'lease_s')
        positive(renew_s, 'renew_s')
        positive(operation_timeout_s, 'operation_timeout_s')
        if (lease_s < 15 or renew_s < 1 or renew_s > lease_s / 3
                or renew_s + operation_timeout_s + 1 >= lease_s):
            raise ValueError('lease timing requires duration >=15, renewal >=1 and adequate deadline margin')
        self.lease_s, self.renew_s = lease_s, renew_s
        self._pid = os.getpid()
        self._mutex = threading.RLock()
        self._sessions, self._reservations = set(), set()
        self._max_active_leases = max_active_leases
        self._transport = PostgresTransport(dsn, operation_timeout_s=operation_timeout_s,
            pool_timeout_s=pool_timeout_s, connect_timeout_s=connect_timeout_s,
            lock_timeout_s=lock_timeout_s, statement_timeout_s=statement_timeout_s,
            pool_size=pool_size, max_active_leases=max_active_leases)

    @property
    def namespace(self):
        return self._namespace

    def initialize(self):
        session_schema.initialize(self._transport)

    def check_ready(self):
        session_schema.check_ready(self._transport)

    def _scope(self, scope):
        if type(scope) is not ConversationScope or scope.namespace != self.namespace:
            raise SessionNotFound()
        content = encode(scope.to_dict())
        return content, hashlib.sha256(content).hexdigest()

    def _local(self, session_id, lease, scope):
        self._transport._check_process()
        validate_id(session_id)
        content, identity = self._scope(scope)
        if (type(lease) is not PostgresSessionLease or lease.store is not self
                or lease.session_id != session_id or lease.scope_content != content
                or lease.scope_identity != identity or lease not in self._sessions):
            raise LeaseLost('lease does not own this store/session/scope')
        lease.check_valid()

    async def _lease_row(self, conn, session_id):
        return await (await conn.execute('SELECT scope_identity,owner,generation,expires_at '
            'FROM prosaic_harness_conversations.leases WHERE namespace=%s AND session_id=%s FOR UPDATE',
            (self.namespace, session_id))).fetchone()

    async def _guard_lease(self, conn, lease):
        lease.check_valid()
        row = await self._lease_row(conn, lease.session_id)
        now = (await (await conn.execute('SELECT pg_catalog.clock_timestamp()')).fetchone())[0]
        if (not row or row[0] != lease.scope_identity or row[1] != lease.owner
                or row[2] != lease.generation or row[3] is None or row[3] <= now):
            lease._lost = True
            raise LeaseLost('database conversation ownership expired or changed')
        lease.check_valid()
        return now

    async def _acquire(self, conn, lease):
        await conn.execute('INSERT INTO prosaic_harness_conversations.leases '
            '(namespace,session_id,scope_identity) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
            (self.namespace, lease.session_id, lease.scope_identity))
        row = await self._lease_row(conn, lease.session_id)
        now = (await (await conn.execute('SELECT pg_catalog.clock_timestamp()')).fetchone())[0]
        if row[0] != lease.scope_identity:
            raise SessionNotFound()
        if row[1] is not None and row[3] > now:
            raise SessionBusy('session is owned by another execution')
        generation = row[2] + 1
        await conn.execute('UPDATE prosaic_harness_conversations.leases '
            'SET owner=%s,generation=%s,expires_at=%s WHERE namespace=%s AND session_id=%s AND scope_identity=%s',
            (lease.owner, generation, now + timedelta(seconds=self.lease_s),
             self.namespace, lease.session_id, lease.scope_identity))
        return generation

    async def _renew(self, conn, lease):
        now = await self._guard_lease(conn, lease)
        cursor = await conn.execute('UPDATE prosaic_harness_conversations.leases SET expires_at=%s '
            'WHERE namespace=%s AND session_id=%s AND scope_identity=%s AND owner=%s AND generation=%s',
            (now + timedelta(seconds=self.lease_s), self.namespace, lease.session_id,
             lease.scope_identity, lease.owner, lease.generation))
        if cursor.rowcount != 1:
            lease._lost = True
            raise LeaseLost('database conversation renewal ownership changed')

    async def _release(self, conn, lease):
        await conn.execute('UPDATE prosaic_harness_conversations.leases SET owner=NULL,expires_at=NULL '
            'WHERE namespace=%s AND session_id=%s AND scope_identity=%s AND owner=%s AND generation=%s',
            (self.namespace, lease.session_id, lease.scope_identity, lease.owner, lease.generation))

    @contextmanager
    def lease(self, session_id, *, scope):
        self._transport._check_process()
        validate_id(session_id)
        content, identity = self._scope(scope)
        reservation, session, primary = object(), None, None
        try:
            with self._mutex:
                if len(self._reservations) >= self._max_active_leases:
                    raise StoreBusy('active conversation capacity exhausted')
                self._reservations.add(reservation)
            session = PostgresSessionLease(self, session_id, content, identity, time.monotonic())
            session.generation = self._transport.call(lambda conn: self._acquire(conn, session))
            session.check_valid()
            with self._mutex:
                self._sessions.add(session)
            # Retain even an unstarted runner until stop() drains it on the owning loop.
            session._renewal = session.maintain()
            self._transport.submit(session._renewal)
            yield session
        except BaseException as exc:
            primary = exc
            raise
        finally:
            try:
                if session is not None and session.generation is not None:
                    if session._renewal is None:
                        session._stopped.set()
                    else:
                        session.stop()
                    self._transport.call(lambda conn: self._release(conn, session), renewal=True)
            except BaseException:
                session._lost = True
                if primary is None:
                    raise
                primary.add_note('conversation lease cleanup failed; reconcile ownership before retrying')
            finally:
                if session is not None:
                    session._active = False
                with self._mutex:
                    if session is None or session.generation is None or session._stopped.is_set():
                        self._reservations.discard(reservation)
                    if session is not None and session._stopped.is_set():
                        self._sessions.discard(session)

    def _token(self, session_id, scope_identity, revision):
        return digest(['postgres-session-v1', self.namespace, session_id, scope_identity, revision])

    async def _read_session(self, conn, session_id, scope, *, lock=False):
        _, identity = self._scope(scope)
        row = await (await conn.execute('SELECT revision,CASE WHEN octet_length(document)<=8388608 '
            'THEN document ELSE NULL END FROM prosaic_harness_conversations.sessions '
            'WHERE namespace=%s AND session_id=%s AND scope_identity=%s'
            + (' FOR UPDATE' if lock else ''), (self.namespace, session_id, identity))).fetchone()
        if row is None:
            raise SessionNotFound()
        if type(row[1]) is not str:
            raise StoreCorrupt('invalid conversation snapshot')
        state = decode_session(row[1].encode('utf-8'))
        if state['sessionId'] != session_id or state['scope'] != scope.to_dict():
            raise StoreCorrupt('conversation identity does not match its address')
        return SessionSnapshot(session_id, state, self._token(session_id, identity, row[0])), row[0]

    def load_session(self, session_id, *, scope):
        validate_id(session_id)
        self._scope(scope)
        return self._transport.call(lambda conn: self._read_snapshot(conn, session_id, scope))

    async def _read_snapshot(self, conn, session_id, scope):
        return (await self._read_session(conn, session_id, scope))[0]

    def _document(self, session_id, state, scope):
        content = encode_session(state)
        value = decode_session(content)
        if value['sessionId'] != session_id or value['scope'] != scope.to_dict():
            raise StoreCorrupt('conversation identity does not match its address')
        return content, value

    def _mutate(self, session_id, lease, scope, callback):
        self._local(session_id, lease, scope)
        async def guarded(conn):
            self._local(session_id, lease, scope)
            await self._guard_lease(conn, lease)
            return await callback(conn)
        try:
            result = self._transport.call(guarded)
            lease.check_valid()
            return result
        except StoreUnavailable:
            lease._lost = True
            raise

    def create_session(self, session_id, state, lease, *, scope):
        self._local(session_id, lease, scope)
        content, _ = self._document(session_id, state, scope)
        async def create(conn):
            row = await (await conn.execute('INSERT INTO prosaic_harness_conversations.sessions '
                '(namespace,session_id,scope_identity,revision,document) VALUES(%s,%s,%s,1,%s) '
                'ON CONFLICT DO NOTHING RETURNING revision',
                (self.namespace, session_id, lease.scope_identity, content.decode('utf-8')))).fetchone()
            if row is None:
                await self._read_session(conn, session_id, scope)
                raise SessionAlreadyExists()
            return self._token(session_id, lease.scope_identity, row[0])
        return self._mutate(session_id, lease, scope, create)

    def save_session(self, session_id, state, expected_revision, lease, *, scope):
        self._local(session_id, lease, scope)
        validate_revision(expected_revision)
        content, value = self._document(session_id, state, scope)
        async def save(conn):
            snapshot, revision = await self._read_session(conn, session_id, scope, lock=True)
            if snapshot.revision != expected_revision:
                raise RevisionConflict('conversation checkpoint changed; refresh status')
            validate_session_transition(snapshot.state, value)
            row = await (await conn.execute('UPDATE prosaic_harness_conversations.sessions '
                'SET document=%s,revision=revision+1 WHERE namespace=%s AND session_id=%s '
                'AND scope_identity=%s AND revision=%s RETURNING revision',
                (content.decode('utf-8'), self.namespace, session_id, lease.scope_identity, revision))).fetchone()
            if row is None:
                raise RevisionConflict('conversation checkpoint changed; refresh status')
            return self._token(session_id, lease.scope_identity, row[0])
        return self._mutate(session_id, lease, scope, save)

    async def _read_receipt(self, conn, state, invocation_id):
        identity = hashlib.sha256(encode(state['scope'])).hexdigest()
        row = await (await conn.execute('SELECT CASE WHEN octet_length(document)<=8388608 '
            'THEN document ELSE NULL END,sha256 FROM prosaic_harness_conversations.receipts '
            'WHERE namespace=%s AND session_id=%s AND scope_identity=%s AND invocation_id=%s',
            (self.namespace, state['sessionId'], identity, invocation_id))).fetchone()
        if row is None:
            return None
        try:
            if type(row[0]) is not str:
                raise ValueError('receipt document')
            content = row[0].encode('utf-8')
            value = verify_receipt(decode(content))
            canonical = encode(value)
            if (value['invocationId'] != invocation_id or content != canonical
                    or hashlib.sha256(canonical).hexdigest() != row[1]):
                raise ValueError('receipt integrity')
        except (ValueError, TypeError, UnicodeError):
            raise StoreCorrupt('conversation receipt integrity does not match its address') from None
        return match_receipt(state, value)

    def load_receipt(self, session_id, invocation_id, *, scope):
        validate_id(session_id)
        validate_id(invocation_id)
        self._scope(scope)
        async def read(conn):
            snapshot, _ = await self._read_session(conn, session_id, scope)
            return await self._read_receipt(conn, snapshot.state, invocation_id)
        return self._transport.call(read)

    def save_receipt(self, session_id, invocation_id, receipt, lease, *, scope):
        self._local(session_id, lease, scope)
        validate_id(invocation_id)
        value = verify_receipt(receipt)
        if value['invocationId'] != invocation_id:
            raise StoreCorrupt('receipt identity does not match its address')
        content = encode(value)
        async def save(conn):
            snapshot, _ = await self._read_session(conn, session_id, scope, lock=True)
            match_receipt(snapshot.state, value)
            await conn.execute('INSERT INTO prosaic_harness_conversations.receipts '
                '(namespace,session_id,scope_identity,invocation_id,document,sha256) VALUES(%s,%s,%s,%s,%s,%s) '
                'ON CONFLICT DO NOTHING', (self.namespace, session_id, lease.scope_identity,
                 invocation_id, content.decode('utf-8'), hashlib.sha256(content).hexdigest()))
            existing = await self._read_receipt(conn, snapshot.state, invocation_id)
            if encode(existing) != content:
                raise ReceiptConflict('immutable receipt differs from committed evidence')
        self._mutate(session_id, lease, scope, save)

    def close(self):
        if self._pid != os.getpid():
            raise StoreBusy('construct database stores after worker fork')
        with self._mutex:
            if self._sessions or self._reservations:
                raise StoreBusy('drain active conversations before closing the store')
            self._transport.close()

    def __enter__(self):
        self._transport._check_process()
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.close()
        except Exception:
            if exc is None:
                raise
            exc.add_note('conversation store cleanup failed; drain pending operations')
