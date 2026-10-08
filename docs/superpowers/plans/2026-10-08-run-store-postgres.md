# Harness RunStore and PostgreSQL Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an application persist Harness runs in an explicitly initialized
PostgreSQL database and safely resume them on another worker, without changing
existing filesystem workflows or adding a database dependency to core.

**Architecture:** Core owns a synchronous RunStore contract, filesystem adapter
and engine admission/recovery. A separate distribution owns PostgreSQL SQL,
connections, renewable leases and setup commands. Its synchronous facade uses
an adapter-owned I/O loop internally so network waits have client-side deadlines;
model execution never runs on that loop or inside a database transaction.

**Tech Stack:** Python >=3.11; existing Harness/Runtime; psycopg >=3.2,<4,
psycopg-pool >=3.2,<4 and libpq >=17 for the adapter only; pytest; PostgreSQL
16 and 18; disposable Podman/Docker fixtures. Default adapter installation uses
`psycopg[binary]`; test binary availability on Linux/arm64 and macOS/arm64.

**Spec:** [Approved design](../specs/2026-10-08-run-store-postgres-design.md).

Status: implementation plan awaiting review and execution-method selection.
The internal nonblocking-I/O clarification is included in this plan for review;
it changes no consumer API and introduces no application asyncio requirement.

## Global Constraints

- Core installation must not install or import a PostgreSQL driver.
- The adapter is a separate distribution under `adapters/postgres/`, not in the core wheel.
- Preserve checkpoint-v2, sealed receipts, fingerprints, ledger/schema admission and file layouts.
- Preserve the `Harness(workflow, run_dir, ...)` constructor and existing CLI behavior.
- Never implicitly initialize/migrate or fall back to local state.
- Preserve existing JSON bounds (8 MiB per persisted document), finite values and independent snapshots.
- Default lease duration is 60 seconds and renewal interval 15 seconds.
- Validate duration >=15 seconds, interval >=1 second and interval <=duration/3.
- Default pool/connect timeouts are 5 seconds, row-lock timeout 1 second, statement timeout 5 seconds and total renewal-operation budget 10 seconds.
- Renewal interval + total renewal budget + safety margin >=lease duration is invalid; safety margin is at least 1 second.
- All adapter tables are permanent/logged; require fsync=on, full_page_writes=on and effective synchronous_commit=on or remote_apply.
- All reads/writes use one authoritative writable primary; no replica or cache recovery reads.
- Lease, run and receipt mutation guards share short transactions; lock lease before run before receipt when needed.
- Use clock_timestamp() after the lease-row lock, not transaction-start time; expired leases cannot renew.
- Human decisions and explicit interrupted-call retry consent require an expected revision for external stores.
- Model/tool interruption never authorizes automatic redispatch; missing receipts require explicit retry consent.
- Applications retain authentication, tenant authorization, scheduling, quotas and external-effect idempotency.
- No HTTP service, queue, database provisioning, historical importer, consumer migration, package publication or remote push.
- Use `.venv/bin/python -m pytest` and `.venv/bin/python -m build`; keep Prosaic on PATH.
- New neutral agent prose uses paired ALWAYS/NEVER rules; no credentials in prose or committed fixtures.

## Review Focus

1. A stale approval from an earlier pause with the same choice name must not advance a later pause (Task 2 and Task 5).
2. A network blackhole, delayed commit reply or cancellation cleanup must not extend the local ownership deadline or create unbounded background work (Task 3 and Task 5).
3. Reconnection to a standby or unsafe session must fail before run-data access/model dispatch, even after a successful startup check (Task 3 and Task 5).
4. Reusing another store's lease or another run's revision must not authorize mutation; a forged namespace is not authorization (Task 1 and Task 4).
5. Unicode payloads, non-finite numbers, symlinks and corrupt seals must not bypass storage bounds or existing admission (Task 1, Task 2 and Task 4).

## File Map and Dependency Order

| Unit | Files | Responsibility |
| --- | --- | --- |
| Core contract | `src/prosaic_harness/run_store.py` | Public protocol, typed errors, revisions and bounded document codecs |
| Filesystem implementation | `src/prosaic_harness/file_store.py` | Descriptor-safe existing layout, flock session and revision checks |
| Existing local utilities | `src/prosaic_harness/store.py` | Keep asset reads/JSON parsing/atomic writes independent of RunStore |
| Public exports | `src/prosaic_harness/__init__.py` | Export RunStore, FileRunStore, RunSnapshot and storage errors |
| Engine | `src/prosaic_harness/engine.py` | Inject storage, retain admission/recovery, enforce human revision and ownership |
| Reusable tests | `src/prosaic_harness/testing.py` | Backend contract assertions without eager pytest or driver imports |
| Adapter package | `adapters/postgres/pyproject.toml`, `README.md`, `src/prosaic_harness_postgres/__init__.py` | Separate build/dependencies and public facade |
| Bounded I/O | `adapters/postgres/src/prosaic_harness_postgres/transport.py` | Process-local loop, two bounded pools, deadlines and safe lifecycle |
| Database setup | `adapters/postgres/src/prosaic_harness_postgres/schema.py` | Version-1 DDL, readiness/durability/privilege checks and initialization |
| Persistence | `adapters/postgres/src/prosaic_harness_postgres/store.py` | Namespace-bound reads, guarded writes and outcome reconciliation |
| Leases | `adapters/postgres/src/prosaic_harness_postgres/leases.py` | Database fencing, renewal and sticky local loss |
| Operator commands | `adapters/postgres/src/prosaic_harness_postgres/cli.py` | init, doctor and explicit disposable write diagnostic |
| Core verification | `tests/test_run_store.py`, `tests/test_store_engine.py` | File conformance and storage-backed engine behaviors |
| Adapter verification | `adapters/postgres/tests/` | Real database/driver, multiprocessing, crash, routing and packaging tests |
| Consumer example | `examples/postgres/` | Human-only start/resume and synthetic inference recovery demonstration |
| Documentation/CI | `README.md`, `examples/README.md`, `.github/workflows/tests.yml` | Explain setup and require adapter integration tests |

Tasks 1-2 produce backward-compatible core with a replaceable backend. Tasks 3-4
produce the reference adapter. Tasks 5-7 prove distributed behavior and complete
the setup path. Keep the current branch and all existing changes; create/reuse an
isolated execution worktree only at the execution stage if the selected workflow
requires it. Do not copy ignored run data or secrets into it.

## Shared Interface Decisions

`run_store.py` exports `STORAGE_CONTRACT_VERSION = 1`, `RunSnapshot(state: dict,
revision: str)`, `LeaseSession` and `RunStore`. Protocol signatures are:

```python
from dataclasses import dataclass
from typing import ContextManager, Protocol

@dataclass(frozen=True)
class RunSnapshot:
    state: dict
    revision: str

class LeaseSession(Protocol):
    def check_valid(self) -> None: ...

class RunStore(Protocol):
    namespace: str
    def initialize(self) -> None: ...
    def check_ready(self) -> None: ...
    def lease(self, run_id: str) -> ContextManager[LeaseSession]: ...
    def load_run(self, run_id: str) -> RunSnapshot: ...
    def create_run(self, run_id: str, state: dict, lease: LeaseSession) -> str: ...
    def save_run(self, run_id: str, state: dict, expected_revision: str,
                 lease: LeaseSession) -> str: ...
    def load_receipt(self, run_id: str, invocation_id: str) -> dict | None: ...
    def save_receipt(self, run_id: str, invocation_id: str, receipt: dict,
                     lease: LeaseSession) -> None: ...
    def close(self) -> None: ...
```

Ellipsis above is normal Protocol syntax, not deferred implementation. Concrete
backends implement every operation. `StoreError` subclasses `ValueError` so the
existing CLI catches it; `.code` and its public message are safe to display.
Export `StoreUninitialized`, `StoreIncompatible`, `StoreUnavailable`, `StoreBusy`,
`RunBusy`, `LeaseLost`, `RevisionConflict`, `ReceiptConflict`, `RunNotFound`,
`RunAlreadyExists` and `StoreCorrupt`. Codes are snake_case; StoreUnavailable
also has `outcome_unknown: bool = False`. Never expose driver exceptions through
public exception chaining/default diagnostics.

Validate namespace/run/invocation addressing before access. Namespaces use ASCII
`[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`; database run/invocation IDs are lowercase
32-character UUID hex. Revision tokens are bounded strings, maximum 512 bytes,
and bound to namespace/run as well as checkpoint revision; they are equality
tokens, not authorization. File revision derives from checkpoint content;
PostgreSQL revision derives from its increasing BIGINT counter. Use a SHA-256
digest of a backend-specific identity/revision tuple; no caller parsing needed.

`FileRunStore(root, *, namespace='default')` addresses
`root/namespace/run_id/{run.json,run.lock,attempts/}`. Its
`for_run_dir(run_dir)` classmethod is a legacy one-directory binding with the
internal addressing key `legacy`; this key is not the sealed checkpoint UUID.
Legacy Harness construction uses that binding and retains the old generated
checkpoint UUID. Explicit external-store construction requires a UUID run ID.
The engine distinguishes legacy/external mode from constructor arguments, not
by introspecting a PostgreSQL implementation.

`PostgresRunStore(dsn, *, namespace, lease_s=60, renew_s=15,
operation_timeout_s=10, pool_timeout_s=5, connect_timeout_s=5,
lock_timeout_s=1, statement_timeout_s=5, pool_size=8, max_active_leases=4)`
and `from_env(name, **kwargs)` expose only synchronous methods. Validate all
numeric options as finite, non-boolean positive values before starting I/O.
Ordinary pool maximum is 8 by default; renewal pool maximum and active lease
limit are 4. Both use lazy/minimum-zero connections and bounded waiting queues.
StoreBusy means local capacity/lifecycle conflict; RunBusy means another owner
of this run. Public close/context-manager behavior matches the spec.

During execution, core holds one lease and one expected checkpoint revision.
`run()` and `resume()` return dictionaries as before. `status()` returns a
validated RunSnapshot without an execution lease or inference. Legacy `.file`
and `.directory` attributes remain meaningful only for legacy file construction;
external storage never creates a local run directory.

---

### Task 1: Public contract, filesystem backend and reusable conformance

**Files:** Create `run_store.py`, `file_store.py`, `testing.py` under
`src/prosaic_harness/`; modify `__init__.py`; create `tests/test_run_store.py`.
Retain local `store.py` helpers unchanged unless a narrowly tested export is needed.

**Interfaces:** Consumes existing `locked`, `read_json`, `write_json`, `MAX_BYTES`,
`parse_json` and checkpoint seals. Produces the Shared Interface Decisions above
and `assert_run_store_contract(store, *, state, receipt)` in `testing.py`.
Conformance receives full sealed fixtures created through the existing legacy
Harness/FakeRuntime test setup; it does not manufacture partial checkpoints.

- [ ] **Step 1: Write failing tests for isolated snapshots, stale/foreign leases,
  duplicate create, CAS, immutable receipts, bounds and existing layout.**

```python
def test_snapshot_is_independent(tmp_path, paused_state):
    from prosaic_harness import FileRunStore
    store = FileRunStore(tmp_path, namespace="tenant-a")
    run_id = paused_state["run_id"]
    with store.lease(run_id) as lease:
        store.create_run(run_id, paused_state, lease)
    snapshot = store.load_run(run_id)
    snapshot.state["inputs"]["task"] = "mutated"
    assert store.load_run(run_id).state["inputs"] == {"task": "draft"}

def test_foreign_lease_cannot_write(tmp_path, paused_state):
    from prosaic_harness import FileRunStore, LeaseLost
    a = FileRunStore(tmp_path, namespace="tenant-a")
    b = FileRunStore(tmp_path, namespace="tenant-b")
    with a.lease(paused_state["run_id"]) as lease:
        with pytest.raises(LeaseLost):
            b.create_run(paused_state["run_id"], paused_state, lease)
```

`paused_state` fixture calls the existing `setup(..., pause=True)` and
`Harness(..., runtime=FakeRuntime(['{"approved":true}'])).run({'task':'draft'})`
in a separate seed directory. Obtain its matching receipt from `attempts/`.
Add literal cases for NaN/infinity, duplicate JSON keys, a UTF-8 payload crossing
8 MiB by bytes, wrong namespace/run revision, `../` identifiers, symlink
parents/destinations, corrupt seal and two live flock sessions. Assert no file
changes on failed writes. Wrong-run revision uses two independently seeded runs.

- [ ] **Step 2: Run RED:** `.venv/bin/python -m pytest -q tests/test_run_store.py`.
  Expected: missing public FileRunStore/new contract failures, not fixture errors.
- [ ] **Step 3: Implement bounded codecs, safe errors and descriptor-safe FileRunStore.**

```python
def encode_document(value):
    if not isinstance(value, dict):
        raise StoreCorrupt("document must be an object")
    encoded = json.dumps(value, sort_keys=True, allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise StoreCorrupt("document exceeds size limit")
    return encoded

def save_run(self, run_id, state, expected_revision, lease):
    self._validate_lease(run_id, lease)
    current = self.load_run(run_id)
    if current.revision != expected_revision:
        raise RevisionConflict("checkpoint changed; refresh status")
    encode_document(state)
    write_json(self._directory(run_id) / "run.json", state)
    return self.load_run(run_id).revision
```

`decode_document` bounds input before UTF-8 decoding, uses existing strict JSON
parsing, verifies root/seal and returns a fresh object. File writes use existing
atomic/fsynced helpers, not path-based replacements. Session validation checks
store identity, addressing key, PID and active lock ownership; an exited session
is permanently invalid. Create rejects any existing checkpoint rather than
overwriting it. Receipt repeats compare bounded canonical payloads; mismatches
raise ReceiptConflict. Status reads may observe one atomically committed file
snapshot without acquiring the execution lock. Close rejects active sessions.
`testing.py` contains plain assertion helpers, no eagerly imported pytest.
- [ ] **Step 4: Run GREEN and full suite:** focused command, then
  `.venv/bin/python -m pytest -q`; expect all existing legacy cases unchanged.
- [ ] **Step 5: Commit only Task 1 files:** `feat: add Harness run storage contract and file backend`.

### Task 2: Engine integration, human revision targeting and lease-loss origin

**Files:** Modify `engine.py` and public exports; create `tests/test_store_engine.py`.
Keep CLI argument/output compatibility and `workflow.py` asset reads unchanged.

**Interfaces:** Consumes Task 1 protocols. Produces
`Harness(workflow, run_dir=None, *, store=None, run_id=None, runtime=None,
on_event=None, validators=None, cancelled=None, clock=time.time)`;
`status() -> RunSnapshot`; and
`resume(*, choice=None, response=None, retry_interrupted=False,
expected_revision=None) -> dict`.

- [ ] **Step 1: Write failing engine tests for explicit storage without a local
  run directory, stale human consent and receipt recovery.**

```python
def test_external_decision_requires_current_revision(tmp_path, monkeypatch):
    from prosaic_harness import FileRunStore, RevisionConflict
    flow = setup(tmp_path, monkeypatch, pause=True)
    runtime = FakeRuntime(['{"approved":true}'])
    store = FileRunStore(tmp_path / "storage", namespace="app")
    h = Harness(flow, store=store, run_id="a" * 32, runtime=runtime)
    assert h.run({"task": "draft"})["status"] == "waiting"
    snapshot = h.status()
    with pytest.raises(ValueError):
        h.resume(choice="approve")
    with pytest.raises(RevisionConflict):
        h.resume(choice="approve", expected_revision="stale")
    assert len(runtime.calls) == 1
    assert h.resume(choice="approve", expected_revision=snapshot.revision)["status"] == "completed"
```

Also create a two-pause workflow sharing the `approve` choice: submit pause-1
revision after reaching pause 2 and assert rejection/no new calls/no mutation.
Add supplied-token enforcement for legacy file mode, stale retry consent,
missing receipt -> interrupted_call, saved receipt -> adoption without dispatch,
validator/schema/tool/evidence drift, unchanged deadline/call/token budgets,
mutually exclusive constructor options and wrong sealed/storage run ID.
A controlled LeaseSession test double loses ownership during Runtime and after
receipt commit; assert LeaseLost, no admitted output/no stale blocked write.
This double tests engine branching only; Task 5 proves actual database fencing.

- [ ] **Step 2: Run RED:** `.venv/bin/python -m pytest -q tests/test_store_engine.py`.
  Expected: unsupported store/status/revision APIs.
- [ ] **Step 3: Replace only run persistence/locking paths and retain controller rules.**

```python
def _save(self, state):
    self._lease.check_valid()
    state.update(seal(state))
    if self._revision is None:
        self._revision = self.store.create_run(self._storage_run_id, state, self._lease)
    else:
        self._revision = self.store.save_run(
            self._storage_run_id, state, self._revision, self._lease)

def _check_expected_revision(self, expected_revision, *, human_action):
    if human_action and not self._legacy_file_mode and expected_revision is None:
        raise ValueError("expected_revision is required for this response")
    if expected_revision is not None and expected_revision != self._revision:
        raise RevisionConflict("checkpoint changed; refresh status")
```

An execution context checks ready, enters `store.lease`, loads the snapshot and
records `_revision`, and clears `_lease` on exit. New-run create is separate from
resume load. Legacy construction binds key `legacy`; external new checkpoints
use the provided UUID. Replace all direct receipt access in `_verify_ledger`,
resume recovery and `_drive` with RunStore operations. Preserve the order
pending commit -> Runtime -> receipt commit -> `_accept` -> checkpoint advance.
`status()` validates seal/state/ledger but does not mutate or dispatch.

Before each dispatch/admission/persistence boundary call lease.check_valid().
Runtime's cancellation callback returns true on LeaseLost and remembers that
cause; after Runtime returns, raise LeaseLost before receipt/admission rather
than passing it into `_block('cancelled')`. Trusted validators and event callbacks
must not swallow that storage error. Ordinary user cancellation keeps existing
behavior. On StoreUnavailable with unknown commit outcome, stop; on next owned
resume, validate/adopt authoritative receipts or require explicit retry. Do not
automatically rerun a human response or invoke Runtime during reconciliation.
- [ ] **Step 4: Run GREEN, entire core suite, and existing CLI transport tests.**
  Commands: focused tests; `.venv/bin/python -m pytest -q`; `prosaic --version`.
- [ ] **Step 5: Commit:** `feat: route Harness execution through RunStore`.

### Task 3: Separate adapter package, bounded transport and schema readiness

**Files:** Create adapter `pyproject.toml`, `README.md`, `__init__.py`,
`transport.py`, `schema.py`; create adapter tests `conftest.py`, `test_transport.py`,
`test_schema.py`, `support/tcp_proxy.py`. Modify root package version for the new
public contract: core 0.6.0; adapter starts at 0.1.0. These are unpublished build
versions, not authorization to publish/release.

**Interfaces:** Produces process-local `PostgresTransport` with synchronous
`call(async_operation, *, renewal=False, timeout_s=10)` and `close()`;
schema functions `initialize(transport)` and `check_ready(transport)`;
adapter package dependency `prosaic-harness>=0.6,<0.7`.
Install psycopg binary and psycopg-pool only in the adapter environment.

- [ ] **Step 1: Write failing real-driver tests for uninitialized readiness,
  idempotent/parallel initialization and bounded network failure.**

```python
def test_network_blackhole_has_client_deadline(db_admin_dsn, tcp_proxy):
    from prosaic_harness import StoreUnavailable
    from prosaic_harness_postgres.transport import PostgresTransport
    with tcp_proxy(db_admin_dsn) as proxy:
        with PostgresTransport(proxy.dsn, operation_timeout_s=1) as transport:
            transport.call(lambda conn: conn.execute("SELECT 1"))
            proxy.block_server_replies()
            started = time.monotonic()
            with pytest.raises(StoreUnavailable):
                transport.call(lambda conn: conn.execute("SELECT 1"))
            assert time.monotonic() - started < 2
            assert transport.pending_operations == 0
```

`db_admin_dsn` comes only from `HARNESS_TEST_DATABASE_URL`; absence skips local
adapter integration only unless `--require-postgres` is set, which fails the
session. The TCP proxy is test-only, loopback-only, forwards a real PostgreSQL
connection and can pause/close replies; SSL disabling applies only to this
explicit disposable local fixture, never adapter defaults. `pending_operations`
is an internal transport diagnostic for production lifecycle accounting, not a
test-only method. Use outer subprocess time limits so a hung test cannot hang CI.

Test pool saturation, unreachable startup, double/active close, post-fork use,
NaN/boolean/unsafe timing options, raw driver-error/DSN redaction, schema-version
rollback/newer version, nonlogged tables, readonly connections, unsafe WAL/session
settings and actual runtime grants. Removing a guard must make dispatch fail a test.

- [ ] **Step 2: Run RED in the adapter test environment:**
  `python -m pytest -q adapters/postgres/tests/test_transport.py adapters/postgres/tests/test_schema.py --require-postgres`.
  Missing adapter behavior must fail, not be skipped because no database exists.
- [ ] **Step 3: Implement bounded I/O and explicit version-1 migration.**

Use one owned asyncio loop thread per long-lived transport, separate ordinary
and renewal AsyncConnectionPool instances, `open=False`, `min_size=0`, bounded
max_size/max_waiting/reconnect_timeout and connection check/reset hooks. Store the
creator PID and reject inherited use before touching the loop or connections.
No application callback executes on the I/O thread.

Each call registers an operation before submission, owns one connection and
shares a monotonic budget across pool wait, begin, SQL and commit. Reserve the
last 2 seconds of the default 10-second budget for cancellation/connection
discard; for a smaller budget reserve at most half. Schedule a deadline handler
on the loop that marks the request timed out, closes/quarantines its owned
connection and cancels its task. Bound cleanup with `asyncio.wait`, not an
unbounded wait-for-cancellation. A discarded connection never returns as healthy
to the pool. Pending operations remain registered until teardown completes;
late success cannot be delivered to a timed-out caller. An unresolved cleanup
keeps capacity occupied, returns a safe error and makes close fail without
closing used pools. Test hard bounds before proceeding to lease implementation.
Use libpq>=17 bounded cancellation; do not depend on cancellation success to
infer transaction outcome. Psycopg documents these
[async cancellation limits](https://www.psycopg.org/psycopg3/docs/advanced/async.html)
and [bounded cancellation](https://www.psycopg.org/psycopg3/docs/api/connections.html).

Use READ COMMITTED transactions and transaction-local lock/statement timeouts;
validate `pg_is_in_recovery()`, `transaction_read_only`, fsync, full_page_writes
and effective synchronous_commit before run-data access. Preserve remote_apply.
Use qualified adapter table names and a trusted pg_catalog-only search path.
Initialization accepts no missing/nonexisting database fallback. It acquires
`pg_advisory_xact_lock(0x50524f53414943)` (pass the integer as a SQL parameter),
checks version metadata, runs normal logged DDL and writes version 1 atomically.
Migration budget is 30 seconds including cleanup; parallel init has the same
bound, and an unknown schema version is never upgraded/downgraded automatically.
Migration lock/statement waits use the remaining maintenance budget rather
than the 1-second execution lock timeout; no phase extends the total deadline.

```sql
CREATE SCHEMA IF NOT EXISTS prosaic_harness;
CREATE TABLE prosaic_harness.schema_version (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton),
    schema_version INTEGER NOT NULL,
    storage_contract_version INTEGER NOT NULL
);
CREATE TABLE prosaic_harness.leases (
    namespace TEXT NOT NULL CHECK (namespace ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$'),
    run_id TEXT NOT NULL CHECK (run_id ~ '^[0-9a-f]{32}$'),
    generation BIGINT NOT NULL DEFAULT 0 CHECK (generation >= 0),
    owner TEXT,
    expires_at TIMESTAMPTZ,
    PRIMARY KEY (namespace, run_id),
    CHECK ((owner IS NULL) = (expires_at IS NULL))
);
CREATE TABLE prosaic_harness.runs (
    namespace TEXT NOT NULL,
    run_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK (revision > 0),
    document TEXT NOT NULL CHECK (octet_length(document) <= 8388608),
    PRIMARY KEY (namespace, run_id),
    FOREIGN KEY (namespace, run_id) REFERENCES prosaic_harness.leases(namespace, run_id)
);
CREATE TABLE prosaic_harness.receipts (
    namespace TEXT NOT NULL,
    run_id TEXT NOT NULL,
    invocation_id TEXT NOT NULL CHECK (invocation_id ~ '^[0-9a-f]{32}$'),
    document TEXT NOT NULL CHECK (octet_length(document) <= 8388608),
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (namespace, run_id, invocation_id),
    FOREIGN KEY (namespace, run_id) REFERENCES prosaic_harness.runs(namespace, run_id)
);
INSERT INTO prosaic_harness.schema_version VALUES (TRUE, 1, 1);
```

DDL above applies only when the owned schema is new. Existing version 1 must
pass catalog/table/constraint checks, not reexecute CREATE TABLE or silently
repair damaged/partial schemas. Before creating within a pre-existing schema,
verify trusted ownership; fail closed rather than adopting attacker-created
objects. No runtime schema-version UPDATE, receipt UPDATE or DELETE grants.
Check expected table persistence and runtime SELECT/INSERT/UPDATE privileges
through catalogs without creating rows. Return safe stable errors from the facade.
- [ ] **Step 4: Run GREEN and entire core/adapter suites against a real database.**
- [ ] **Step 5: Commit:** `feat: add isolated PostgreSQL adapter setup and bounded I/O`.

### Task 4: PostgreSQL leases, immutable receipts and revision-fenced persistence

**Files:** Create adapter `store.py`, `leases.py`, `tests/test_store.py`,
`tests/test_leases.py`; export PostgresRunStore from adapter `__init__.py`.

**Interfaces:** Consumes transport/schema and core contract. Produces
PostgresRunStore/lease context with the constructor above, matching all protocol
operations and safe context-manager support. Public snapshots/revisions never
contain owner/fencing tokens. Private lease session owns store/PID/run identity,
owner UUID, generation, sticky loss, conservative expiry and renewal task handle.

- [ ] **Step 1: Write failing real-PostgreSQL conformance and expiry tests.**

```python
def test_expired_owner_cannot_renew_without_takeover(pg_store, expire_lease):
    from prosaic_harness import LeaseLost
    with pg_store.lease("a" * 32) as lease:
        expire_lease("a" * 32)  # Separate admin connection; test helper only.
        with pytest.raises(LeaseLost):
            pg_store._transport.call(
                lambda conn: pg_store._renew(conn, lease), renewal=True)
        with pytest.raises(LeaseLost):
            lease.check_valid()
```

Add old-owner create/checkpoint/receipt/release tests after takeover, generation
persistence after release, identical/conflicting receipts, stale/wrong-run
revisions and foreign store leases. For fresh-time checks, hold the lease row
with another connection, advance expires_at into the past while holding it,
then release and assert the waiting writer fails. Do not wait 60 seconds to
manufacture expiry; alter only fixture-owned lease rows with admin credentials.

- [ ] **Step 2: Run RED:** adapter store/lease tests with `--require-postgres`.
- [ ] **Step 3: Implement guarded SQL and bounded renewable sessions.**

Within acquisition: INSERT a zero-generation released row ON CONFLICT DO NOTHING,
lock that row, then read clock_timestamp(). Admit only released/expired rows;
otherwise RunBusy. Set fresh owner/generation+1/expiry and commit before yielding.
Within renewal/mutation: validate local session, lock the lease, read fresh time
and compare owner/generation/unexpired; any mismatch marks the session lost.
The actual guards use bound values, not formatted identifiers:

```sql
SELECT owner, generation, expires_at
FROM prosaic_harness.leases
WHERE namespace = %s AND run_id = %s FOR UPDATE;
SELECT clock_timestamp();
UPDATE prosaic_harness.leases
SET expires_at = %s
WHERE namespace = %s AND run_id = %s AND owner = %s AND generation = %s;
```

The third statement is a renewal only after comparing the first row to the
second statement's time; require exactly one updated row. Store new local
deadline as monotonic request-start + lease duration, never reply-arrival time.
Release compares owner/generation, clears owner/expiry, retains the row and
generation and cannot invalidate another session. Renewal uses its reserved
pool and bounded active-lease admission; its task stops/joins on session exit.
A lost flag cannot clear even if a late renewal transaction committed.
`_renew(conn, lease)` is the coroutine used by the actual renewal task; the
test invokes that same routine through the synchronous transport bridge.
Never call the synchronous bridge from its own I/O thread.

CRUD guards share the lease transaction; lock current run after lease. Compare
the opaque expected token derived from the current BIGINT revision, increment
revision atomically and return the new token only after commit acknowledgement.
Create is INSERT-only; duplicates are RunAlreadyExists. Receipt insertion uses
INSERT ON CONFLICT DO NOTHING, then bounded read/canonical comparison on repeat;
it never overwrites and requires live ownership even for identical repeats.
Use TEXT rather than automatic JSONB decoding, the core bounded codec and
database byte constraints. Reads scope every query by namespace/run and invocation.
Oversized/corrupt/missing ledger receipts fail closed, not as receipt absence.

```sql
SELECT revision, CASE WHEN octet_length(document) <= 8388608
                     THEN document ELSE NULL END
FROM prosaic_harness.runs WHERE namespace = %s AND run_id = %s;
UPDATE prosaic_harness.runs SET document = %s, revision = revision + 1
WHERE namespace = %s AND run_id = %s AND revision = %s
RETURNING revision;
```

If commit acknowledgement is lost, return StoreUnavailable(outcome_unknown=True)
and mark an execution lease lost when its ownership cannot be established.
Core stops; a subsequent owned resume reloads authoritative state/receipts.
Do not transparently repeat a modifying transaction or reenter Runtime. Stop
and reconcile an unknown release instead of assuming it permits another owner.
- [ ] **Step 4: Run GREEN, reusable conformance and full engine cases on PG/File.**
  Reuse `assert_run_store_contract` and parameterized controller cases; retain
  legacy filesystem-specific symlink/layout tests separately.
- [ ] **Step 5: Commit:** `feat: add fenced PostgreSQL run persistence and renewable leases`.

### Task 5: Independent workers, crash durability and recovery release gates

**Files:** Create adapter tests `test_workers.py`, `test_recovery.py`,
`test_durability.py`, `test_routing.py`, `support/workers.py`,
`support/local_cluster.py`, `support/model_server.py`; extend test fixtures.

**Interfaces:** `local_cluster.py` provides `start --engine podman|docker`,
`test`, `stop` commands and a temporary ownership manifest. Test fixtures expose
`pg_store`, `runtime_dsn`, `migration_dsn`, `standby_dsn`, `paused_state`,
`expire_lease(run_id)`, `worker(command)` and `model_server.request_count`.
Workers construct fresh stores after spawn, never inherit loops/connections.

- [ ] **Step 1: Write failing independent-process tests for the core promises.**

```python
def test_receipt_committed_before_worker_death_is_adopted(worker, model_server):
    first = worker("run-until-receipt-commit")
    first.wait_for_receipt_committed(timeout=10)
    first.kill_and_wait(timeout=5)
    second = worker("resume-same-run")
    state = second.wait_for_checkpoint(timeout=10)
    assert state["status"] == "completed"
    assert state["calls"] == 1
    assert model_server.request_count == 1
```

Workers use a test-only store wrapper to stop at committed edges; it delegates
real writes then signals through a multiprocessing Event. No production crash
hook is added. The shared workflow is immutable at one absolute fixture path.
The synthetic HTTP server records real request counts and implements fixed JSON
replies/delayed responses; these tests never call TokenProxy or external models.

Cover death before dispatch, pending-without-receipt, receipt-before-advance,
decision-after-commit, checkpoint transition and completion. Pending-without-
receipt resumes blocked without a model call; explicit retry needs a fresh
revision and preserves consumed budget. Kill/restart the fixture database after
acknowledged commits and check all rows survive. The fixture, not production
code, exposes crash/alter/configure methods.

- [ ] **Step 2: Run RED with independent processes and outer hard timeouts.**
  `python -m pytest -q adapters/postgres/tests --require-postgres`.
  Synchronize races with Events/barriers and database row locks, not timing-only sleeps.
- [ ] **Step 3: Complete fixtures and repair only failures demonstrated by tests.**

```python
ctx = multiprocessing.get_context("spawn")
ready = ctx.Event()
release = ctx.Event()
process = ctx.Process(target=run_worker, args=(runtime_dsn, run_id, ready, release))
process.start()
assert ready.wait(10), "worker did not reach its durable checkpoint"
release.set()
process.join(10)
assert not process.is_alive(), "worker exceeded its execution bound"
```

`run_worker` is defined in support/workers.py and creates its own store/Workflow.
Every test registers process cleanup; after the outer bound it terminates only
its own child and reports a failure. A live renewal spans the original lease
duration; an accelerated valid lease configuration keeps tests practical.
Saturate ordinary pool slots while renewal stays healthy; pause renewal replies
past the cached deadline, verify sticky LeaseLost and discard returned output.
Test late approvals at a later same-named pause and simultaneous human submissions.

For lost COMMIT replies, the TCP proxy blocks server replies while a separate
admin connection observes the committed row; drop the proxied connection and
assert no premature dispatch/admission or blind repeat. Reconstruct/resume on
the primary and assert receipt/decision reconciliation. Standby fixture streams
the primary then pauses replay: stale checkpoint/missing receipt must never be
accepted through the standby DSN. Unsafe fsync/full_page_writes/session settings
and unlogged tables are altered only in disposable instances and fail readiness.

Local cluster containers have generated names `prosaic-harness-pgtest-<uuid>`
and loopback-only random host ports. Their temporary manifest records exact
container IDs and names for cleanup; validate those before stopping/removing.
Never delete an existing database/schema, touch unrelated containers or use a
broad name/glob. Test-only trust authentication is confined to the isolated
fixture/network. Host psql is not required; fixture administration uses driver
connections and container-owned PostgreSQL tools for replica/crash setup.
- [ ] **Step 4: Run GREEN repeatedly, then all core and adapter tests.**
  Run worker/recovery/routing suites three times; no conditional skips in the
  required lane. Check wrong namespace, runtime/tool executable paths, validators,
  evidence and retained absolute deadline/call/token budgets before dispatch.
- [ ] **Step 5: Commit:** `test: prove cross-worker PostgreSQL recovery and fencing`.

### Task 6: Operator CLI, complete examples and clear consumer documentation

**Files:** Create adapter `cli.py`, `tests/test_cli.py`, `tests/test_examples.py`;
create `examples/postgres/pause.yml`, `runtime.yml`, `synthetic.yml`,
`subagents/author.md`, `schemas/result.json`, `run_workflow.py`, `README.md`;
modify root README/examples index and adapter README/entry point.

**Interfaces:** `prosaic-harness-postgres init --dsn-env NAME`;
`doctor --dsn-env NAME [--check-write]`. Example runner supports start/status/
resume with trusted namespace/run ID and explicit expected revision; it embeds
the one Harness engine, not a new workflow interpreter.

- [ ] **Step 1: Write failing subprocess tests for setup/errors and two-worker example.**

```python
def test_doctor_missing_secret_is_safe(run_cli):
    result = run_cli("doctor", "--dsn-env", "MISSING_HARNESS_DSN", env={})
    assert result.returncode != 0
    assert "store_unavailable" in result.stderr
    assert "Traceback" not in result.stderr
```

`run_cli` preserves a controlled process PATH and installed-package environment,
removes the named DSN, and captures output. Add init-twice, denied DDL/runtime
grants, incompatible schema, read-only doctor with no changed records, explicit
write diagnostic cleanup/failure reporting and sentinel-secret redaction tests.
Run start/status in worker A and resume in worker B as separate subprocesses
with the real runtime role; assert waiting/completed and stale-response rejection.

- [ ] **Step 2: Run RED:** CLI/example tests in the required adapter lane.
- [ ] **Step 3: Implement the small CLI and actual runnable fixtures.**

```yaml
version: 1
runtime: runtime.yml
source: .
start: approval
limits: {max_calls: 1, timeout_s: 10}
steps:
  approval:
    kind: pause
    question: Approve this synthetic request?
    choices: {approve: done, reject: rejected}
  done: {kind: finish}
  rejected: {kind: finish, outcome: rejected}
```

The human-only fixture loads valid assets but invokes no model; its runtime.yml
uses a synthetic loopback profile. The separate agent fixture has actual prose
with ALWAYS/NEVER rules and result schema, and points to the test model server.
`run_workflow.py` uses argparse, public SDK methods and JSON stdin/files to
transport run/revision identity between processes; status output explicitly
contains its revision. Production documentation warns to filter private state.
No credentials or raw database errors are printed.

`doctor --check-write` uses a generated, adapter-reserved diagnostic namespace
and migration/diagnostic credentials with DELETE permission. Run actual guarded
store operations then delete only its exact receipt/run/lease identities in
receipt -> run -> lease order. It never deletes production lease generations.
Cleanup errors fail the command; interruptions cannot silently leave a passing
result. Default doctor reads catalogs/settings only and does not touch a model.

Documentation includes package install, existing-database prerequisite, separate
DSN environment names, the approved runtime SQL grants, init/doctor/start/status/
resume commands, stable mount/executable paths, clock synchronization, pool
capacity per process, missing initialization and stale/lease-lost error remedies.
Use one long-lived store per bounded trusted application namespace, not a pool
per request. Explain that prose tool grants do not grant database permissions.
State external-effect idempotency and asynchronous-failover rollback limits.
- [ ] **Step 4: Run GREEN and execute all documented commands from clean installs.**
- [ ] **Step 5: Commit:** `docs: add tested PostgreSQL setup and cross-worker examples`.

### Task 7: Mandatory CI, clean-wheel isolation and final acceptance

**Files:** Modify `.github/workflows/tests.yml`; create adapter
`tests/test_packaging.py`; add `MANIFEST.in`/package-data configuration only if
required by wheel inspection. Update plan checkboxes and implementation notes
with actual verification outcomes, not presumed success.

**Interfaces:** Existing core job retains Python 3.11/3.12/3.13 and no PostgreSQL
dependency. A required adapter job tests PostgreSQL 16/18; an owned-container
recovery/routing job executes restart/standby tests. Required tests may not pass
by skipping missing infrastructure. Local Podman arm64 verifies native container
and wheel installation alongside the CI x86_64 lane.

- [ ] **Step 1: Write failing wheel-install tests for dependency isolation and CLI.**

```python
def test_core_wheel_has_no_postgres_dependency(core_only_python):
    report = subprocess.run(
        [core_only_python, "-c",
         "import importlib.util; import prosaic_harness; "
         "assert importlib.util.find_spec('psycopg') is None; "
         "assert importlib.util.find_spec('prosaic_harness_postgres') is None"],
        capture_output=True, text=True)
    assert report.returncode == 0, report.stderr
```

`core_only_python` belongs to a fresh temporary venv installed from the built
core wheel and declared runtime dependencies, not this checkout or its PATH.
Another clean environment installs both wheels and executes the complete CLI/
SDK quick start. Inspect wheel contents/metadata and run core-only import in a
subprocess; do not merely grep the pyproject. Avoid importing adapter tests from
core's default `testpaths=['tests']`.

- [ ] **Step 2: Run RED before packaging/CI changes.** Missing adapter entry point,
  wheel discovery/version contracts or leaked dependencies must fail explicitly.
- [ ] **Step 3: Wire separate builds and required database jobs.**

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m build
.venv/bin/python -m build adapters/postgres
python -m pytest -q adapters/postgres/tests --require-postgres
git diff --check
```

CI builds/installs the local core wheel before the adapter so >=0.6,<0.7 resolves
to this checkout, then installs only the adapter's test requirements. Configure
health-checked disposable PostgreSQL service credentials; use fixture-owned
containers for crash/standby scenarios, never kill the shared service used by
other tests. CI test collection fails if a required case is skipped. Keep model
servers synthetic and live inference opt-in. No publish/tag/release step is added.
- [ ] **Step 4: Run GREEN: full suites, wheel/sdist builds, clean installations,
  documented two-worker smoke, and arm64 fixture evidence.** Record exact counts,
  versions and any unmet platform gate. Do not call it MVP-ready with a skipped
  PostgreSQL/timeout/recovery gate or a red test.
- [ ] **Step 5: Commit:** `ci: require PostgreSQL adapter recovery and packaging checks`.
- [ ] **Step 6: Final independent review and handoff.** Follow the selected
  execution skill's reviewer gate. Address actionable findings with failing
  regressions first and rerun affected/full suites. Leave local commits ready
  for the user's review; do not push, publish or migrate consumers without a
  separate request.

## Plan Self-Review and Current Evidence

- Spec coverage: public storage/file compatibility -> Tasks 1-2; packaging,
  schema/durability/primary guards -> Task 3; lease/CAS/receipt semantics -> Task 4;
  recovery/human targeting/process safety -> Tasks 2/5; setup/diagnostics/deployment
  limits -> Task 6; mandatory real database/platform/build proof -> Task 7.
- Review Focus coverage: each of the five conditions has its owning test cases
  above; test-only crash/proxy/process controls remain outside production classes.
- Interface consistency: revision is always an opaque string; load returns
  RunSnapshot; create/save return revision; receipt absence is None, corruption
  is an error; namespaces are constructor-bound; lease loss remains sticky.
- Baseline before implementation: `.venv/bin/python -m pytest -q` passed
  **122 tests in 34.95 seconds** on 2026-10-08. No adapter tests or driver installs
  have been performed at this planning checkpoint.
- Written-spec approval permits this plan. Product implementation starts only
  after plan review and execution-method selection. Native execution is
  recommended here because the seven tasks depend tightly on the same storage,
  lease and engine interfaces; retain an independent whole-branch review.
