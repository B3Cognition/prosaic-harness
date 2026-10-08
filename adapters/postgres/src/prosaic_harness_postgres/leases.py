"""Private renewable execution sessions; database generations fence writes."""
import asyncio
import os
import threading
import time
import uuid

from prosaic_harness import LeaseLost, StoreError, StoreBusy


class PostgresLease:
    def __init__(self, store, run_id, started):
        self.store, self.run_id = store, run_id
        self.pid = os.getpid()
        self.owner = uuid.uuid4().hex
        self.generation = None
        self._deadline = started + store.lease_s
        self._lost = False
        self._active = True
        self._stopping = threading.Event()
        self._stopped = threading.Event()
        self._task = None

    def check_valid(self):
        if (self.pid != os.getpid() or not self._active or self._lost
                or time.monotonic() >= self._deadline):
            self._lost = True
            raise LeaseLost('database execution session is no longer owned')

    async def maintain(self):
        self._task = asyncio.current_task()
        try:
            while not self._stopping.is_set():
                await asyncio.sleep(self.store.renew_s)
                if self._stopping.is_set():
                    break
                started = time.monotonic()
                await self.store._transport.execute_async(
                    lambda conn: self.store._renew(conn, self), renewal=True)
                self.check_valid()
                self._deadline = started + self.store.lease_s
        except (StoreError, asyncio.CancelledError):
            self._lost = True
        except Exception:
            self._lost = True
        finally:
            self._stopped.set()

    def stop(self):
        self._stopping.set()
        def cancel():
            if self._task is not None:
                self._task.cancel()
        self.store._transport._loop.call_soon_threadsafe(cancel)
        if not self._stopped.wait(self.store._transport.operation_timeout_s + 2):
            self._lost = True
            raise StoreBusy('renewal task has not drained; retain store until cleanup completes')
