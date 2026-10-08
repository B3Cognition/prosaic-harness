"""Namespace-bound RunStore with short transactions and no inference retries."""
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import os
import re
import threading
import time

from prosaic_harness import (RunSnapshot, StoreBusy, StoreCorrupt, StoreUnavailable,
                            LeaseLost, RunBusy, RunNotFound, RunAlreadyExists,
                            RevisionConflict, ReceiptConflict)
from prosaic_harness.run_store import (validate_namespace, validate_id, validate_revision,
                                      encode_document, decode_document, revision_token)
from .transport import PostgresTransport, positive
from . import schema
from .leases import PostgresLease


class PostgresRunStore:
    @classmethod
    def from_env(cls, name, *, namespace, **kwargs):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', name):
            raise ValueError('dsn environment name must be a bounded identifier')
        dsn = os.environ.get(name)
        if not dsn:
            raise StoreUnavailable('required database environment variable is missing')
        return cls(dsn, namespace=namespace, **kwargs)

    def __init__(self, dsn, *, namespace, lease_s=60, renew_s=15,
                 operation_timeout_s=10, pool_timeout_s=5, connect_timeout_s=5,
                 lock_timeout_s=1, statement_timeout_s=5, pool_size=8, max_active_leases=4):
        self.namespace = validate_namespace(namespace)
        positive(lease_s, 'lease_s')
        positive(renew_s, 'renew_s')
        positive(operation_timeout_s, 'operation_timeout_s')
        if (lease_s < 15 or renew_s < 1 or renew_s > lease_s / 3
                or renew_s + operation_timeout_s + 1 >= lease_s):
            raise ValueError('lease timing requires duration >=15, renewal >=1 and adequate deadline margin')
        self.lease_s, self.renew_s = lease_s, renew_s
        self._pid = os.getpid()
        self._mutex = threading.RLock()
        self._sessions = set()
        self._acquiring = 0
        self._max_active_leases = max_active_leases
        self._transport = PostgresTransport(dsn, operation_timeout_s=operation_timeout_s,
            pool_timeout_s=pool_timeout_s, connect_timeout_s=connect_timeout_s,
            lock_timeout_s=lock_timeout_s, statement_timeout_s=statement_timeout_s,
            pool_size=pool_size, max_active_leases=max_active_leases)

    def initialize(self):
        schema.initialize(self._transport)

    def check_ready(self):
        schema.check_ready(self._transport)

    def _local(self, run_id, lease):
        self._transport._check_process()
        validate_id(run_id)
        if (not isinstance(lease, PostgresLease) or lease.store is not self
                or lease.run_id != run_id or lease not in self._sessions):
            raise LeaseLost('lease does not own this store/run')
        lease.check_valid()

    async def _lease_row(self, conn, run_id):
        return await (await conn.execute('SELECT owner,generation,expires_at FROM prosaic_harness.leases '
            'WHERE namespace=%s AND run_id=%s FOR UPDATE', (self.namespace, run_id))).fetchone()

    async def _guard_lease(self, conn, lease):
        self._local(lease.run_id, lease)
        row = await self._lease_row(conn, lease.run_id)
        now = (await (await conn.execute('SELECT pg_catalog.clock_timestamp()')).fetchone())[0]
        if (not row or row[0] != lease.owner or row[1] != lease.generation
                or row[2] is None or row[2] <= now):
            lease._lost = True
            raise LeaseLost('database execution ownership expired or changed')
        lease.check_valid()
        return now

    async def _acquire(self, conn, lease):
        await conn.execute('INSERT INTO prosaic_harness.leases(namespace,run_id) VALUES(%s,%s) '
                           'ON CONFLICT DO NOTHING', (self.namespace, lease.run_id))
        row = await self._lease_row(conn, lease.run_id)
        now = (await (await conn.execute('SELECT pg_catalog.clock_timestamp()')).fetchone())[0]
        if row[0] is not None and row[2] > now:
            raise RunBusy('run is owned by another execution')
        generation = row[1] + 1
        await conn.execute('UPDATE prosaic_harness.leases SET owner=%s,generation=%s,expires_at=%s '
                           'WHERE namespace=%s AND run_id=%s',
                           (lease.owner, generation, now + timedelta(seconds=self.lease_s),
                            self.namespace, lease.run_id))
        return generation

    async def _renew(self, conn, lease):
        now = await self._guard_lease(conn, lease)
        cursor = await conn.execute('UPDATE prosaic_harness.leases SET expires_at=%s '
            'WHERE namespace=%s AND run_id=%s AND owner=%s AND generation=%s',
            (now + timedelta(seconds=self.lease_s), self.namespace, lease.run_id, lease.owner, lease.generation))
        if cursor.rowcount != 1:
            lease._lost = True
            raise LeaseLost('database renewal ownership changed')

    async def _release(self, conn, lease):
        await conn.execute('UPDATE prosaic_harness.leases SET owner=NULL,expires_at=NULL '
            'WHERE namespace=%s AND run_id=%s AND owner=%s AND generation=%s',
            (self.namespace, lease.run_id, lease.owner, lease.generation))

    @contextmanager
    def lease(self, run_id):
        self._transport._check_process()
        validate_id(run_id)
        with self._mutex:
            if len(self._sessions) + self._acquiring >= self._max_active_leases:
                raise StoreBusy('active execution capacity exhausted')
            self._acquiring += 1
        session = PostgresLease(self, run_id, time.monotonic())
        try:
            session.generation = self._transport.call(lambda conn: self._acquire(conn, session))
            session.check_valid()
            with self._mutex:
                self._sessions.add(session)
            self._transport.submit(session.maintain())
        finally:
            with self._mutex:
                self._acquiring -= 1
        primary = None
        try:
            yield session
        except BaseException as exc:
            primary = exc
            raise
        finally:
            try:
                session.stop()
                session._active = False
                self._transport.call(lambda conn: self._release(conn, session), renewal=True)
            except Exception:
                session._lost = True
                if primary is None:
                    raise
                primary.add_note('database lease cleanup failed; reconcile ownership before retrying')
            finally:
                if session._stopped.is_set():
                    with self._mutex:
                        self._sessions.discard(session)

    def _token(self, run_id, revision):
        return revision_token('postgres', self.namespace, run_id, revision)

    async def _read_run(self, conn, run_id, *, lock=False):
        row = await (await conn.execute('SELECT revision,CASE WHEN octet_length(document)<=8388608 '
            'THEN document ELSE NULL END FROM prosaic_harness.runs WHERE namespace=%s AND run_id=%s'
            + (' FOR UPDATE' if lock else ''), (self.namespace, run_id))).fetchone()
        if not row:
            raise RunNotFound('run document not found')
        state = decode_document(row[1])
        if state.get('run_id') != run_id:
            raise StoreCorrupt('checkpoint identity does not match its address')
        return RunSnapshot(state, self._token(run_id, row[0])), row[0]

    def load_run(self, run_id):
        validate_id(run_id)
        async def read(conn):
            return (await self._read_run(conn, run_id))[0]
        return self._transport.call(read)

    def _document(self, run_id, state):
        content = encode_document(state)
        if state.get('run_id') != run_id:
            raise StoreCorrupt('checkpoint identity does not match its address')
        return content.decode('utf-8')

    def _mutate(self, run_id, lease, callback):
        self._local(run_id, lease)
        async def guarded(conn):
            await self._guard_lease(conn, lease)
            return await callback(conn)
        try:
            result = self._transport.call(guarded)
            lease.check_valid()
            return result
        except StoreUnavailable:
            lease._lost = True
            raise

    def create_run(self, run_id, state, lease):
        self._local(run_id, lease)
        document = self._document(run_id, state)
        async def create(conn):
            row = await (await conn.execute('INSERT INTO prosaic_harness.runs(namespace,run_id,revision,document) '
                'VALUES(%s,%s,1,%s) ON CONFLICT DO NOTHING RETURNING revision',
                (self.namespace, run_id, document))).fetchone()
            if not row:
                raise RunAlreadyExists('run already exists; use resume or a new identity')
            return self._token(run_id, row[0])
        return self._mutate(run_id, lease, create)

    def save_run(self, run_id, state, expected_revision, lease):
        self._local(run_id, lease)
        validate_revision(expected_revision)
        document = self._document(run_id, state)
        async def save(conn):
            snapshot, revision = await self._read_run(conn, run_id, lock=True)
            if snapshot.revision != expected_revision:
                raise RevisionConflict('checkpoint changed; refresh status')
            row = await (await conn.execute('UPDATE prosaic_harness.runs SET document=%s,revision=revision+1 '
                'WHERE namespace=%s AND run_id=%s AND revision=%s RETURNING revision',
                (document, self.namespace, run_id, revision))).fetchone()
            if not row:
                raise RevisionConflict('checkpoint changed; refresh status')
            return self._token(run_id, row[0])
        return self._mutate(run_id, lease, save)

    async def _read_receipt(self, conn, run_id, invocation_id):
        row = await (await conn.execute('SELECT CASE WHEN octet_length(document)<=8388608 THEN document '
            'ELSE NULL END,sha256 FROM prosaic_harness.receipts WHERE namespace=%s AND run_id=%s AND invocation_id=%s',
            (self.namespace, run_id, invocation_id))).fetchone()
        if row is None:
            return None
        receipt = decode_document(row[0])
        if (receipt.get('id') != invocation_id or receipt.get('run_id') != run_id
                or hashlib.sha256(encode_document(receipt)).hexdigest() != row[1]):
            raise StoreCorrupt('receipt integrity or identity does not match its address')
        return receipt

    def load_receipt(self, run_id, invocation_id):
        validate_id(run_id)
        validate_id(invocation_id)
        return self._transport.call(lambda conn: self._read_receipt(conn, run_id, invocation_id))

    def save_receipt(self, run_id, invocation_id, receipt, lease):
        self._local(run_id, lease)
        validate_id(invocation_id)
        content = encode_document(receipt)
        if receipt.get('id') != invocation_id or receipt.get('run_id') != run_id:
            raise StoreCorrupt('receipt identity does not match its address')
        async def save(conn):
            await self._read_run(conn, run_id, lock=True)
            await conn.execute('INSERT INTO prosaic_harness.receipts(namespace,run_id,invocation_id,document,sha256) '
                'VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                (self.namespace, run_id, invocation_id, content.decode('utf-8'), hashlib.sha256(content).hexdigest()))
            existing = await self._read_receipt(conn, run_id, invocation_id)
            if encode_document(existing) != content:
                raise ReceiptConflict('immutable receipt differs from committed evidence')
        self._mutate(run_id, lease, save)

    def close(self):
        if self._pid != os.getpid():
            raise StoreBusy('construct database stores after worker fork')
        with self._mutex:
            if self._sessions or self._acquiring:
                raise StoreBusy('drain active executions before closing the store')
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
            exc.add_note('database store cleanup failed; drain pending operations')
