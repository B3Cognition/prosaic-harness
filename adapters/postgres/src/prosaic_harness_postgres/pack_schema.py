"""Owner-only, schema-wide opt-in; never rewrite run or receipt documents."""
from prosaic_harness import StoreIncompatible,StoreUninitialized,StoreBusy


def migrate(transport,*,schema,target,versions,lock,ready):
    # These identifiers are internal constants, never user/model data.
    if (schema,target) not in {('prosaic_harness',2),('prosaic_harness_conversations',3)}:
        raise StoreIncompatible()
    async def operation(conn):
        await conn.execute("SELECT pg_catalog.set_config('lock_timeout','25000ms',true), "
            "pg_catalog.set_config('statement_timeout','28000ms',true)")
        await conn.execute('SELECT pg_catalog.pg_advisory_xact_lock(%s)',(lock,))
        owner=await (await conn.execute("SELECT pg_catalog.pg_has_role(nspowner,'USAGE') "
            'FROM pg_catalog.pg_namespace WHERE nspname=%s',(schema,))).fetchone()
        if owner is None: raise StoreUninitialized('initialize storage explicitly first')
        if owner[0] is not True: raise StoreIncompatible('migration role must own the adapter schema')
        current=await (await conn.execute('SELECT schema_version,storage_contract_version FROM '+schema+'.schema_version')).fetchall()
        if len(current)!=1 or current[0] not in versions: raise StoreIncompatible('migration requires intact known storage')
        await ready(conn,expected_versions=current[0])
        if current[0]==(target,target): return
        # Includes every namespace. This transaction is brief and never spans
        # inference, a counter, a validator or any host callback.
        await conn.execute('LOCK TABLE '+schema+'.leases IN EXCLUSIVE MODE')
        active=await (await conn.execute('SELECT EXISTS(SELECT 1 FROM '+schema+'.leases '
            'WHERE owner IS NOT NULL AND expires_at>pg_catalog.clock_timestamp())')).fetchone()
        if active[0]: raise StoreBusy('drain all writers to the shared schema before migration')
        changed=await conn.execute('UPDATE '+schema+'.schema_version '
            'SET schema_version=%s,storage_contract_version=%s WHERE singleton IS TRUE',(target,target))
        if changed.rowcount!=1: raise StoreIncompatible()
        await ready(conn,expected_versions=(target,target))
    return transport.call(operation,timeout_s=30)
