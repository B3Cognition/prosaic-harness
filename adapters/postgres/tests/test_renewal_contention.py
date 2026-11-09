import asyncio
import threading
import time
import uuid

import pytest


@pytest.mark.parametrize('kind',['run','conversation'])
def test_same_owner_write_does_not_cancel_renewal(db_admin_dsn,kind):
    from prosaic_harness import ConversationScope
    from prosaic_harness_postgres import PostgresRunStore,PostgresSessionStore
    cls=PostgresRunStore if kind=='run' else PostgresSessionStore
    with cls(db_admin_dsn,namespace='renewal-row',lease_s=15,renew_s=1,
             operation_timeout_s=5,lock_timeout_s=.05,statement_timeout_s=3) as store:
        store.initialize(context_packs=True)
        scope=ConversationScope('renewal-row','sandbox','chat','tenant','actor')
        lease_context=store.lease(uuid.uuid4().hex,**({'scope':scope} if kind=='conversation' else {}))
        attempted=threading.Event()
        original=store._renew
        async def observed(conn,lease):
            attempted.set()
            return await original(conn,lease)
        store._renew=observed
        with lease_context as lease:
            original_deadline=lease._deadline
            async def write(conn):
                await store._guard_lease(conn,lease)
                while not attempted.is_set():
                    await asyncio.sleep(.01)
                # A valid foreground transaction owns its lease row while
                # writing a large record. Renewal must wait for that commit.
                await conn.execute('SELECT pg_catalog.pg_sleep(.3)')
            store._transport.call(write)
            end=time.monotonic()+1
            while not lease._lost and lease._deadline==original_deadline and time.monotonic()<end:
                time.sleep(.01)
            lease.check_valid()
            assert lease._deadline>original_deadline
