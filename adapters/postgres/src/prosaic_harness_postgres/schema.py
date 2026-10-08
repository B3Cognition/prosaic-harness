"""Explicit, transactional version-1 setup and read-only readiness checks."""
from prosaic_harness import StoreUninitialized, StoreIncompatible
from prosaic_harness.run_store import STORAGE_CONTRACT_VERSION

SCHEMA_VERSION = 1
MIGRATION_LOCK = 0x50524f53414943

DDL = """
CREATE SCHEMA IF NOT EXISTS prosaic_harness;
CREATE TABLE prosaic_harness.schema_version (
 singleton BOOLEAN PRIMARY KEY CHECK (singleton), schema_version INTEGER NOT NULL,
 storage_contract_version INTEGER NOT NULL);
CREATE TABLE prosaic_harness.leases (
 namespace TEXT NOT NULL CHECK (namespace ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$'),
 run_id TEXT NOT NULL CHECK (run_id ~ '^[0-9a-f]{32}$'),
 generation BIGINT NOT NULL DEFAULT 0 CHECK (generation >= 0), owner TEXT,
 expires_at TIMESTAMPTZ, PRIMARY KEY(namespace, run_id),
 CHECK ((owner IS NULL) = (expires_at IS NULL)));
CREATE TABLE prosaic_harness.runs (
 namespace TEXT NOT NULL, run_id TEXT NOT NULL,
 revision BIGINT NOT NULL CHECK(revision > 0),
 document TEXT NOT NULL CHECK(octet_length(document) <= 8388608),
 PRIMARY KEY(namespace, run_id),
 FOREIGN KEY(namespace, run_id) REFERENCES prosaic_harness.leases(namespace, run_id));
CREATE TABLE prosaic_harness.receipts (
 namespace TEXT NOT NULL, run_id TEXT NOT NULL,
 invocation_id TEXT NOT NULL CHECK(invocation_id ~ '^[0-9a-f]{32}$'),
 document TEXT NOT NULL CHECK(octet_length(document) <= 8388608),
 sha256 TEXT NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
 PRIMARY KEY(namespace, run_id, invocation_id),
 FOREIGN KEY(namespace, run_id) REFERENCES prosaic_harness.runs(namespace, run_id));
INSERT INTO prosaic_harness.schema_version VALUES(TRUE, 1, 1);
"""

COLUMNS = {
    'schema_version': {'singleton': 'boolean', 'schema_version': 'integer', 'storage_contract_version': 'integer'},
    'leases': {'namespace': 'text', 'run_id': 'text', 'generation': 'bigint', 'owner': 'text', 'expires_at': 'timestamp with time zone'},
    'runs': {'namespace': 'text', 'run_id': 'text', 'revision': 'bigint', 'document': 'text'},
    'receipts': {'namespace': 'text', 'run_id': 'text', 'invocation_id': 'text', 'document': 'text', 'sha256': 'text'},
}

CONSTRAINTS = {
    'schema_version': {'CHECK (singleton)', 'PRIMARY KEY (singleton)'},
    'leases': {
        "CHECK ((namespace ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$'::text))",
        "CHECK ((run_id ~ '^[0-9a-f]{32}$'::text))",
        'CHECK ((generation >= 0))', 'CHECK (((owner IS NULL) = (expires_at IS NULL)))',
        'PRIMARY KEY (namespace, run_id)'},
    'runs': {'CHECK ((revision > 0))', 'CHECK ((octet_length(document) <= 8388608))',
        'PRIMARY KEY (namespace, run_id)',
        'FOREIGN KEY (namespace, run_id) REFERENCES prosaic_harness.leases(namespace, run_id)'},
    'receipts': {"CHECK ((invocation_id ~ '^[0-9a-f]{32}$'::text))",
        "CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text))",
        'CHECK ((octet_length(document) <= 8388608))',
        'PRIMARY KEY (namespace, run_id, invocation_id)',
        'FOREIGN KEY (namespace, run_id) REFERENCES prosaic_harness.runs(namespace, run_id)'},
}


async def ready_on_connection(conn):
    exists = await (await conn.execute("SELECT pg_catalog.to_regclass('prosaic_harness.schema_version')")).fetchone()
    if not exists or exists[0] is None:
        raise StoreUninitialized('run init with migration credentials before accepting work')
    tables = await (await conn.execute("""SELECT c.relname, c.relpersistence, c.relkind
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='prosaic_harness' AND c.relname = ANY(%s)""", (list(COLUMNS),))).fetchall()
    if {r[0] for r in tables} != set(COLUMNS) or any(r[1:] != ('p', 'r') for r in tables):
        raise StoreIncompatible('owned schema must contain permanent logged adapter tables')
    columns = await (await conn.execute("""SELECT c.relname, a.attname, pg_catalog.format_type(a.atttypid,a.atttypmod), a.attnotnull
        FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='prosaic_harness' AND c.relname = ANY(%s)
        AND a.attnum>0 AND NOT a.attisdropped""", (list(COLUMNS),))).fetchall()
    actual = {name: {} for name in COLUMNS}
    for table, column, kind, notnull in columns:
        actual[table][column] = kind
        if notnull != ((table, column) not in {('leases', 'owner'), ('leases', 'expires_at')}):
            raise StoreIncompatible('adapter schema nullability is incompatible')
    if actual != COLUMNS:
        raise StoreIncompatible('adapter schema columns are incompatible')
    constraints = await (await conn.execute("""SELECT c.relname,
        pg_catalog.pg_get_constraintdef(k.oid), k.convalidated, k.contype
        FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='prosaic_harness' AND c.relname = ANY(%s)""", (list(COLUMNS),))).fetchall()
    actual_constraints = {name: set() for name in COLUMNS}
    for table, definition, validated, kind in constraints:
        if not validated:
            raise StoreIncompatible('adapter schema constraints must be validated')
        # PostgreSQL 18 catalogs NOT NULL separately; attnotnull above checks
        # the identical contract on both supported major versions.
        if kind == 'n':
            continue
        actual_constraints[table].add(definition)
    if actual_constraints != CONSTRAINTS:
        raise StoreIncompatible('adapter schema constraints are incompatible')
    version = await (await conn.execute('SELECT schema_version, storage_contract_version FROM prosaic_harness.schema_version')).fetchall()
    if version != [(SCHEMA_VERSION, STORAGE_CONTRACT_VERSION)]:
        raise StoreIncompatible('deploy a compatible adapter/schema; no automatic downgrade')
    for table in COLUMNS:
        privileges = ['SELECT']
        if table in {'leases', 'runs', 'receipts'}:
            privileges.append('INSERT')
        if table in {'leases', 'runs'}:
            privileges.append('UPDATE')
        for privilege in privileges:
            allowed = await (await conn.execute('SELECT pg_catalog.has_table_privilege(%s,%s)',
                                                ('prosaic_harness.' + table, privilege))).fetchone()
            if not allowed or not allowed[0]:
                raise StoreIncompatible('grant required runtime table privileges before accepting work')


def check_ready(transport):
    transport.call(ready_on_connection)


def initialize(transport):
    async def migrate(conn):
        await conn.execute("SELECT pg_catalog.set_config('lock_timeout','25000ms',true), "
                           "pg_catalog.set_config('statement_timeout','28000ms',true)")
        await conn.execute('SELECT pg_catalog.pg_advisory_xact_lock(%s)', (MIGRATION_LOCK,))
        namespace = await (await conn.execute("""SELECT n.oid,
            pg_catalog.pg_has_role(n.nspowner,'USAGE') FROM pg_catalog.pg_namespace n
            WHERE n.nspname='prosaic_harness'""")).fetchone()
        if namespace:
            if not namespace[1]:
                raise StoreIncompatible('migration role must own the adapter schema')
            count = await (await conn.execute('SELECT count(*) FROM pg_catalog.pg_class WHERE relnamespace=%s',
                                              (namespace[0],))).fetchone()
            if count[0]:
                await ready_on_connection(conn)
                return
        await conn.execute(DDL)
        await ready_on_connection(conn)
    transport.call(migrate, timeout_s=30)
