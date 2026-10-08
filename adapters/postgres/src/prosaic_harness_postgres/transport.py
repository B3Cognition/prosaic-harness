"""Synchronous facade over bounded, process-owned PostgreSQL I/O."""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
import logging
import math
import os
import threading
import time
import uuid

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool
from prosaic_harness import StoreError, StoreBusy, StoreIncompatible, StoreUnavailable


def positive(value, name, *, integer=False):
    if (type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            or (integer and type(value) is not int)):
        raise ValueError(f'{name} must be a finite positive {"integer" if integer else "number"}')
    return value


class _PoolRedaction(logging.Filter):
    def __init__(self, prefix):
        super().__init__()
        self.prefix = prefix

    def filter(self, record):
        if self.prefix in record.getMessage():
            record.msg = 'Harness PostgreSQL pool connection unavailable'
            record.args = ()
        return True


@dataclass(eq=False)
class _Operation:
    deadline: float
    work_deadline: float
    connection: object = None
    task: object = None
    expired: bool = False
    commit_started: bool = False


class PostgresTransport:
    def __init__(self, dsn, *, operation_timeout_s=10, pool_timeout_s=5,
                 connect_timeout_s=5, lock_timeout_s=1, statement_timeout_s=5,
                 pool_size=8, max_active_leases=4):
        for name, value in locals().copy().items():
            if name.endswith('_s'):
                positive(value, name)
        positive(pool_size, 'pool_size', integer=True)
        positive(max_active_leases, 'max_active_leases', integer=True)
        if psycopg.pq.version() < 170000:
            raise StoreIncompatible('libpq 17+ is required for bounded cancellation')
        try:
            if not isinstance(dsn, str) or not dsn:
                raise ValueError()
            # This is a connection guard, not permission to disable TLS/options.
            conninfo = make_conninfo(dsn, target_session_attrs='read-write',
                                     connect_timeout=max(1, math.ceil(connect_timeout_s)))
        except Exception:
            raise StoreUnavailable('invalid database connection configuration') from None
        self.operation_timeout_s = operation_timeout_s
        self.pool_timeout_s = pool_timeout_s
        self.lock_timeout_s = lock_timeout_s
        self.statement_timeout_s = statement_timeout_s
        self._pid = os.getpid()
        self._mutex = threading.RLock()
        self._pending = set()
        self._closing = False
        self._close_lock = threading.Lock()
        self._closed = False
        self._capacity = 2 * (pool_size + max_active_leases)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever,
                                        name='harness-postgres-io', daemon=True)
        self._prefix = 'harness-' + uuid.uuid4().hex
        self._filter = _PoolRedaction(self._prefix)
        logging.getLogger('psycopg.pool').addFilter(self._filter)
        self._thread.start()

        async def open_pools():
            settings = dict(conninfo=conninfo, kwargs={'autocommit': True}, min_size=0,
                            open=False, timeout=pool_timeout_s,
                            reconnect_timeout=connect_timeout_s, num_workers=1)
            self._ordinary = AsyncConnectionPool(**settings, max_size=pool_size,
                                                max_waiting=pool_size, name=self._prefix + '-work')
            self._renewal = AsyncConnectionPool(**settings, max_size=max_active_leases,
                                               max_waiting=max_active_leases, name=self._prefix + '-renew')
            await self._ordinary.open()
            await self._renewal.open()
        try:
            asyncio.run_coroutine_threadsafe(open_pools(), self._loop).result(5)
        except Exception:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(1)
            logging.getLogger('psycopg.pool').removeFilter(self._filter)
            raise StoreUnavailable('database pool startup failed') from None

    def _check_process(self):
        if self._pid != os.getpid():
            raise StoreBusy('construct database stores after worker fork')
        if self._closed:
            raise StoreBusy('database store is closed')
        if self._closing:
            raise StoreBusy('database store is closing')

    @property
    def pending_operations(self):
        with self._mutex:
            return len(self._pending)

    def _reserve(self, budget):
        # Reserve synchronously before the loop can be delayed. Registration
        # lasts through actual SQL/runner teardown, not just caller patience.
        self._check_process()
        deadline = time.monotonic() + budget
        operation = _Operation(deadline, deadline - min(2, budget / 2))
        with self._mutex:
            self._check_process()
            if len(self._pending) >= self._capacity:
                raise StoreBusy('database operation capacity exhausted')
            self._pending.add(operation)
        return operation

    @staticmethod
    def _check_deadline(operation):
        if operation.expired or time.monotonic() >= operation.work_deadline:
            operation.expired = True
            raise StoreUnavailable('database operation deadline exceeded; reconcile before retrying',
                                   outcome_unknown=operation.commit_started)

    async def _guard(self, conn):
        row = await (await conn.execute("""SELECT pg_catalog.pg_is_in_recovery(),
            pg_catalog.current_setting('transaction_read_only'),
            pg_catalog.current_setting('fsync'), pg_catalog.current_setting('full_page_writes'),
            pg_catalog.current_setting('synchronous_commit')""")).fetchone()
        if not row or row[0] or row[1:4] != ('off', 'on', 'on') or row[4] not in {'on', 'remote_apply'}:
            raise StoreIncompatible('require writable primary, logged durability and safe WAL settings')

    async def _sql(self, operation, callback, renewal, budget):
        self._check_deadline(operation)
        pool = self._renewal if renewal else self._ordinary
        conn = await pool.getconn(timeout=min(self.pool_timeout_s, budget))
        operation.connection = conn
        try:
            await self._guard(conn)
            async with conn.transaction():
                await conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                await conn.execute("SELECT pg_catalog.set_config('search_path','pg_catalog',true), "
                                   "pg_catalog.set_config('lock_timeout',%s,true), "
                                   "pg_catalog.set_config('statement_timeout',%s,true)",
                                   (f'{min(self.lock_timeout_s, budget)*1000:.0f}ms',
                                    f'{min(self.statement_timeout_s, budget)*1000:.0f}ms'))
                await self._guard(conn)
                self._check_deadline(operation)
                result = await callback(conn)
                self._check_deadline(operation)
                operation.commit_started = True
            return result
        finally:
            await pool.putconn(conn)

    async def _expire(self, operation):
        operation.expired = True
        # Close before cancellation, avoiding a blocking cancellation round trip.
        if operation.connection is not None:
            await operation.connection.close()
        if operation.task is not None:
            operation.task.cancel()

    def _retire(self, operation):
        with self._mutex:
            self._pending.discard(operation)
        # Observe orphan exceptions so they cannot print a raw driver error.
        if operation.task is not None and not operation.task.cancelled():
            operation.task.exception()

    async def execute_async(self, callback, *, renewal=False, timeout_s=None, _operation=None):
        """Internal adapter entry point; callbacks are trusted database operations."""
        budget = self.operation_timeout_s if timeout_s is None else positive(timeout_s, 'timeout_s')
        cleanup = min(2, budget / 2)
        operation = _operation if _operation is not None else self._reserve(budget)
        timer = None
        try:
            self._check_process()
            self._check_deadline(operation)
            remaining = operation.work_deadline - time.monotonic()
            operation.task = asyncio.create_task(self._sql(operation, callback, renewal, remaining))
            timer = self._loop.call_at(self._loop.time() + remaining,
                                      lambda: asyncio.create_task(self._expire(operation)))
            try:
                result = await asyncio.shield(operation.task)
            except asyncio.CancelledError:
                await self._expire(operation)
                await asyncio.wait({operation.task}, timeout=cleanup)
                if operation.expired:
                    raise StoreUnavailable('database operation interrupted; reconcile before retrying',
                                           outcome_unknown=operation.commit_started) from None
                raise
            if operation.expired or time.monotonic() >= operation.deadline:
                raise StoreUnavailable('database operation deadline exceeded; reconcile before retrying',
                                       outcome_unknown=operation.commit_started)
            return result
        except StoreError:
            raise
        except psycopg.errors.InsufficientPrivilege:
            raise StoreIncompatible('database role lacks required privileges') from None
        except Exception:
            raise StoreUnavailable('database access failed; restore connectivity and reconcile',
                                   outcome_unknown=operation.commit_started) from None
        finally:
            if timer is not None:
                timer.cancel()
            if operation.task is None or operation.task.done():
                self._retire(operation)
            else:
                operation.task.add_done_callback(lambda _: self._retire(operation))

    def call(self, callback, *, renewal=False, timeout_s=None):
        self._check_process()
        if threading.current_thread() is self._thread:
            raise StoreBusy('synchronous database calls cannot run on the I/O thread')
        budget = self.operation_timeout_s if timeout_s is None else positive(timeout_s, 'timeout_s')
        operation = self._reserve(budget)
        coroutine = self.execute_async(callback, renewal=renewal, timeout_s=budget, _operation=operation)
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        except BaseException:
            coroutine.close()
            self._retire(operation)
            raise
        # A timed-out caller cannot consume the eventual submitted exception.
        future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            return future.result(max(0, operation.deadline - time.monotonic()))
        except FutureTimeout:
            operation.expired = True
            self._loop.call_soon_threadsafe(lambda: asyncio.create_task(self._expire(operation)))
            # Don't cancel the concurrent Future: that reports completion before
            # the queued runner starts/drains, and can orphan its exception.
            raise StoreUnavailable('database operation deadline exceeded; reconcile before retrying',
                                   outcome_unknown=True) from None
        except BaseException:
            if not future.done():
                operation.expired = True
                self._loop.call_soon_threadsafe(lambda: asyncio.create_task(self._expire(operation)))
            raise

    def submit(self, coroutine):
        self._check_process()
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    def close(self):
        if self._pid != os.getpid():
            raise StoreBusy('construct database stores after worker fork')
        if self._closed:
            return
        if threading.current_thread() is self._thread or not self._close_lock.acquire(blocking=False):
            raise StoreBusy('database cleanup is already running')
        async def close_pools():
            await self._ordinary.close(timeout=1)
            await self._renewal.close(timeout=1)
            remaining = asyncio.all_tasks() - {asyncio.current_task()}
            for task in remaining:
                task.cancel()
            if remaining:
                _, pending = await asyncio.wait(remaining, timeout=1)
                if pending:
                    raise StoreBusy('database workers have not drained')
        try:
            with self._mutex:
                if self._pending:
                    raise StoreBusy('drain pending database operations before closing')
                self._closing = True
            try:
                asyncio.run_coroutine_threadsafe(close_pools(), self._loop).result(5)
            except StoreBusy:
                raise
            except Exception:
                raise StoreBusy('database workers have not drained') from None
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(1)
            if self._thread.is_alive():
                raise StoreBusy('database I/O thread has not stopped')
            self._loop.close()
            self._closed = True
            logging.getLogger('psycopg.pool').removeFilter(self._filter)
        finally:
            self._close_lock.release()

    def __enter__(self):
        self._check_process()
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.close()
        except Exception:
            if exc is None:
                raise
            exc.add_note('database cleanup failed; drain pending operations')
