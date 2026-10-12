"""Independent, explicit version-1 conversation storage and readiness."""
from prosaic_harness import StoreUninitialized, StoreIncompatible

SCHEMA_VERSION = STORAGE_CONTRACT_VERSION = 1
MIGRATION_LOCK = 0x50524348415401
SCHEMA = 'prosaic_harness_conversations'

DDL = """
CREATE SCHEMA IF NOT EXISTS prosaic_harness_conversations;
CREATE TABLE prosaic_harness_conversations.schema_version (
 singleton BOOLEAN PRIMARY KEY CHECK (singleton), schema_version INTEGER NOT NULL,
 storage_contract_version INTEGER NOT NULL);
CREATE TABLE prosaic_harness_conversations.leases (
 namespace TEXT NOT NULL CHECK (namespace ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$'),
 session_id TEXT NOT NULL CHECK (session_id ~ '^[0-9a-f]{32}$'),
 scope_identity TEXT NOT NULL CHECK (scope_identity ~ '^[0-9a-f]{64}$'),
 generation BIGINT NOT NULL DEFAULT 0 CHECK (generation >= 0),
 owner TEXT CHECK (owner ~ '^[0-9a-f]{32}$'), expires_at TIMESTAMPTZ,
 PRIMARY KEY(namespace, session_id), UNIQUE(namespace, session_id, scope_identity),
 CHECK ((owner IS NULL) = (expires_at IS NULL)));
CREATE TABLE prosaic_harness_conversations.sessions (
 namespace TEXT NOT NULL, session_id TEXT NOT NULL, scope_identity TEXT NOT NULL,
 revision BIGINT NOT NULL CHECK (revision > 0),
 document TEXT NOT NULL CHECK (octet_length(document) <= 8388608),
 PRIMARY KEY(namespace, session_id), UNIQUE(namespace, session_id, scope_identity),
 FOREIGN KEY(namespace, session_id, scope_identity) REFERENCES
 prosaic_harness_conversations.leases(namespace, session_id, scope_identity));
CREATE TABLE prosaic_harness_conversations.receipts (
 namespace TEXT NOT NULL, session_id TEXT NOT NULL, scope_identity TEXT NOT NULL,
 invocation_id TEXT NOT NULL CHECK (invocation_id ~ '^[0-9a-f]{32}$'),
 document TEXT NOT NULL CHECK (octet_length(document) <= 8388608),
 sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
 PRIMARY KEY(namespace, session_id, invocation_id),
 FOREIGN KEY(namespace, session_id, scope_identity) REFERENCES
 prosaic_harness_conversations.sessions(namespace, session_id, scope_identity));
INSERT INTO prosaic_harness_conversations.schema_version VALUES(TRUE, 1, 1);
"""

COLUMNS = {
    'schema_version': {'singleton': 'boolean', 'schema_version': 'integer',
                       'storage_contract_version': 'integer'},
    'leases': {'namespace': 'text', 'session_id': 'text', 'scope_identity': 'text',
               'generation': 'bigint', 'owner': 'text', 'expires_at': 'timestamp with time zone'},
    'sessions': {'namespace': 'text', 'session_id': 'text', 'scope_identity': 'text',
                 'revision': 'bigint', 'document': 'text'},
    'receipts': {'namespace': 'text', 'session_id': 'text', 'scope_identity': 'text',
                 'invocation_id': 'text', 'document': 'text', 'sha256': 'text'},
}

CONSTRAINTS = {
    'schema_version': {'CHECK (singleton)', 'PRIMARY KEY (singleton)'},
    'leases': {
        "CHECK ((namespace ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$'::text))",
        "CHECK ((session_id ~ '^[0-9a-f]{32}$'::text))",
        "CHECK ((scope_identity ~ '^[0-9a-f]{64}$'::text))",
        "CHECK ((owner ~ '^[0-9a-f]{32}$'::text))",
        'CHECK ((generation >= 0))', 'CHECK (((owner IS NULL) = (expires_at IS NULL)))',
        'PRIMARY KEY (namespace, session_id)', 'UNIQUE (namespace, session_id, scope_identity)'},
    'sessions': {'CHECK ((revision > 0))', 'CHECK ((octet_length(document) <= 8388608))',
        'PRIMARY KEY (namespace, session_id)', 'UNIQUE (namespace, session_id, scope_identity)',
        'FOREIGN KEY (namespace, session_id, scope_identity) REFERENCES '
        'prosaic_harness_conversations.leases(namespace, session_id, scope_identity)'},
    'receipts': {"CHECK ((invocation_id ~ '^[0-9a-f]{32}$'::text))",
        "CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text))",
        'CHECK ((octet_length(document) <= 8388608))',
        'PRIMARY KEY (namespace, session_id, invocation_id)',
        'FOREIGN KEY (namespace, session_id, scope_identity) REFERENCES '
        'prosaic_harness_conversations.sessions(namespace, session_id, scope_identity)'},
}


async def ready_on_connection(conn):
    namespace = await (await conn.execute("SELECT oid,pg_catalog.has_schema_privilege(oid,'USAGE'), "
        "pg_catalog.pg_has_role(nspowner,'USAGE') "
        "FROM pg_catalog.pg_namespace WHERE nspname=%s", (SCHEMA,))).fetchone()
    if namespace is None:
        raise StoreUninitialized('initialize conversation storage explicitly before accepting work')
    if not namespace[1]:
        raise StoreIncompatible('grant conversation schema usage before accepting work')
    tables = await (await conn.execute("""SELECT c.relname,c.relpersistence,c.relkind,
        c.relowner=n.nspowner,c.relrowsecurity
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=%s AND c.relname=ANY(%s)""", (SCHEMA, list(COLUMNS)))).fetchall()
    if not tables:
        raise StoreUninitialized('initialize conversation storage explicitly before accepting work')
    if {row[0] for row in tables} != set(COLUMNS) or any(
            row[1:] != ('p', 'r', True, False) for row in tables):
        raise StoreIncompatible('conversation storage requires intact owner-controlled logged tables')
    columns = await (await conn.execute("""SELECT c.relname,a.attname,
        pg_catalog.format_type(a.atttypid,a.atttypmod),a.attnotnull
        FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=%s AND c.relname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped""",
        (SCHEMA, list(COLUMNS)))).fetchall()
    actual = {name: {} for name in COLUMNS}
    for table, column, kind, notnull in columns:
        actual[table][column] = kind
        if notnull != ((table, column) not in {('leases', 'owner'), ('leases', 'expires_at')}):
            raise StoreIncompatible('conversation schema nullability is incompatible')
    if actual != COLUMNS:
        raise StoreIncompatible('conversation schema columns are incompatible')
    constraints = await (await conn.execute("""SELECT c.relname,
        pg_catalog.pg_get_constraintdef(k.oid),k.convalidated,k.contype
        FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=%s AND c.relname=ANY(%s)""", (SCHEMA, list(COLUMNS)))).fetchall()
    actual_constraints = {name: set() for name in COLUMNS}
    for table, definition, validated, kind in constraints:
        if not validated:
            raise StoreIncompatible('conversation schema constraints must be validated')
        # PostgreSQL 18 exposes NOT NULL separately; attnotnull above is authoritative.
        if kind != 'n':
            actual_constraints[table].add(definition)
    if actual_constraints != CONSTRAINTS:
        raise StoreIncompatible('conversation schema constraints are incompatible')
    for table in COLUMNS:
        privileges = ['SELECT']
        if table in {'leases', 'sessions', 'receipts'}:
            privileges.append('INSERT')
        if table in {'leases', 'sessions'}:
            privileges.append('UPDATE')
        for privilege in privileges:
            permitted = await (await conn.execute('SELECT pg_catalog.has_table_privilege(%s,%s)',
                (SCHEMA + '.' + table, privilege))).fetchone()
            if not permitted or not permitted[0]:
                raise StoreIncompatible('grant required conversation table privileges before accepting work')
    # Owners (including effective inherited owners) remain operator credentials
    # for initialization/diagnostics. They cannot become restricted runtime roles
    # through SDK checks; the embedding host must keep those credentials separate.
    if not namespace[2]:
        forbidden_schema = await (await conn.execute('SELECT pg_catalog.has_schema_privilege(%s,%s)',
            (namespace[0], 'CREATE'))).fetchone()
        if not forbidden_schema or forbidden_schema[0] is not False:
            raise StoreIncompatible('use least-privilege conversation runtime grants')
        for table in COLUMNS:
            forbidden = ['DELETE', 'TRUNCATE']
            columns = []
            if table == 'schema_version':
                forbidden.extend(['INSERT', 'UPDATE'])
                columns.extend(['INSERT', 'UPDATE'])
            elif table == 'receipts':
                forbidden.append('UPDATE')
                columns.append('UPDATE')
            excess = await (await conn.execute('SELECT pg_catalog.has_table_privilege(%s,%s)',
                (SCHEMA + '.' + table, ','.join(forbidden)))).fetchone()
            if not excess or excess[0] is not False:
                raise StoreIncompatible('use least-privilege conversation runtime grants')
            if columns:
                # Table ACL inspection misses column-only grants. This function
                # includes both table/column permissions and inherited privileges.
                excess_columns = await (await conn.execute('SELECT pg_catalog.has_any_column_privilege(%s,%s)',
                    (SCHEMA + '.' + table, ','.join(columns)))).fetchone()
                if not excess_columns or excess_columns[0] is not False:
                    raise StoreIncompatible('use least-privilege conversation runtime grants')
    versions = await (await conn.execute('SELECT schema_version,storage_contract_version '
        'FROM prosaic_harness_conversations.schema_version')).fetchall()
    if versions != [(SCHEMA_VERSION, STORAGE_CONTRACT_VERSION)]:
        raise StoreIncompatible('conversation schema version is incompatible; no automatic migration')


def check_ready(transport):
    transport.call(ready_on_connection)


def initialize(transport):
    async def migrate(conn):
        await conn.execute("SELECT pg_catalog.set_config('lock_timeout','25000ms',true), "
                           "pg_catalog.set_config('statement_timeout','28000ms',true)")
        await conn.execute('SELECT pg_catalog.pg_advisory_xact_lock(%s)', (MIGRATION_LOCK,))
        namespace = await (await conn.execute("SELECT n.oid,pg_catalog.pg_has_role(n.nspowner,'USAGE') "
            'FROM pg_catalog.pg_namespace n WHERE n.nspname=%s', (SCHEMA,))).fetchone()
        if namespace:
            if not namespace[1]:
                raise StoreIncompatible('migration role must own conversation schema')
            count = await (await conn.execute('SELECT count(*) FROM pg_catalog.pg_class WHERE relnamespace=%s',
                                               (namespace[0],))).fetchone()
            if count[0]:
                try:
                    await ready_on_connection(conn)
                except StoreUninitialized:
                    raise StoreIncompatible('partial conversation schema requires operator repair') from None
                return
        await conn.execute(DDL)
        await ready_on_connection(conn)
    transport.call(migrate, timeout_s=30)
