# PostgreSQL persistence for Prosaic Harness

Run on worker A, inspect/resume on worker B, without a shared writable run
directory. Core remains database-free; install this separate adapter only when
you need shared durable state. The API is synchronous; a private I/O thread
bounds network waits. Model execution holds no database connection/transaction.
Core **0.6.0** and adapter **0.1.0** are published together in the
[Harness v0.6.0 release](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.6.0)
as separate wheels and source archives. The adapter is maintained in this
repository but installed and versioned separately, keeping PostgreSQL drivers
optional for core users. Use the v0.6.0 checkout or release wheels for these APIs;
the older v0.5.0 release does not include them.

## 1. Install and supply an existing database

Python 3.11+, PostgreSQL 16 or 18 on a writable primary, Git for the pinned
Runtime dependency, and libpq 17+ are required. `psycopg[binary]` supplies libpq;
older libpq is rejected. From the Harness repository root:

```sh
python3 -m venv .venv-postgres
.venv-postgres/bin/python -m pip install . ./adapters/postgres
export PATH="$PWD/.venv-postgres/bin:$PATH"
prosaic --version
prosaic-harness-postgres --help
```

Harness does **not** provision PostgreSQL, create databases/users, start a
service, or fall back to files. Your operator supplies two DSNs through a secret
manager: `HARNESS_MIGRATION_DSN` (schema owner with database CREATE permission)
and `HARNESS_RUNTIME_DSN` (restricted runtime role). Never put DSNs in Markdown,
YAML, argv, logs or Git. For a local terminal:

```sh
export HARNESS_MIGRATION_DSN="$(python -c 'import getpass; print(getpass.getpass("Migration DSN: "))')"
export HARNESS_RUNTIME_DSN="$(python -c 'import getpass; print(getpass.getpass("Runtime DSN: "))')"
```

Preserve operator TLS/authentication settings, e.g. `sslmode=verify-full` and
certificate roots. The adapter adds `target_session_attrs=read-write` for primary
routing; it never weakens TLS.

## 2. Initialize once, then grant runtime access

```sh
prosaic-harness-postgres init --dsn-env HARNESS_MIGRATION_DSN
```

Initialization is explicit, transactional, repeatable and concurrency-safe.
It creates schema/version 1, not your database. It refuses unknown versions,
foreign-owned, partial or damaged schemas; it does not repair or downgrade them.

As schema owner, apply these grants, replacing `harness_runtime` with your
existing runtime role (role/password creation belongs to your operator):

```sql
GRANT USAGE ON SCHEMA prosaic_harness TO harness_runtime;
GRANT SELECT ON prosaic_harness.schema_version, prosaic_harness.leases,
    prosaic_harness.runs, prosaic_harness.receipts TO harness_runtime;
GRANT INSERT, UPDATE ON prosaic_harness.leases, prosaic_harness.runs TO harness_runtime;
GRANT INSERT ON prosaic_harness.receipts TO harness_runtime;
```

Do **not** grant runtime schema CREATE, schema-version UPDATE, receipt UPDATE,
or table DELETE. Check using the actual application's credentials:

```sh
prosaic-harness-postgres doctor --dsn-env HARNESS_RUNTIME_DSN
```

Default doctor reads only catalogs/settings/privileges: no rows, model calls or
migrations. For an explicit write-and-cleanup test, use migration or dedicated
diagnostic credentials with DELETE on the three data tables:

```sh
prosaic-harness-postgres doctor --dsn-env HARNESS_MIGRATION_DSN --check-write
```

This exercises guarded create/CAS/receipt/read/release operations in a fresh
`prosaic-diagnostic-<uuid>` namespace. Reserve this prefix; applications must not
use it. Cleanup deletes only its exact receipt/run/lease identities, in that
order, after release. It never deletes production lease generations. Cleanup,
interruption and commit-ack failures fail the command. Its error includes the
diagnostic namespace for reconciliation: inspect exact rows before manual
cleanup/retry, never blindly delete by prefix.

## 3. Embed the single Harness engine

```python
from prosaic_harness import Harness, Workflow
from prosaic_harness_postgres import PostgresRunStore

workflow = Workflow.load('/srv/workflows/approval/pause.yml')
# Construct after fork; keep one long-lived store per bounded trusted namespace.
with PostgresRunStore.from_env('HARNESS_RUNTIME_DSN', namespace='my-app') as store:
    store.check_ready()  # startup gate; no implicit init
    h = Harness(workflow, store=store, run_id='0123456789abcdef0123456789abcdef')
    h.run({'task': 'example'})  # use a NEW UUID for each new run
    snapshot = h.status()     # read-only .state and opaque .revision
    h.resume(choice='approve', expected_revision=snapshot.revision)
```

Worker B reconstructs the same Workflow/namespace/run ID and calls status/resume,
not run. Human choices, structured responses and explicit interrupted-call retry
require the current revision. A stale approval cannot approve a later same-named
pause. Never silently fetch a fresh revision to bypass rejection: show current
state and require a new decision. See the [runnable example](../../examples/postgres/README.md).

`load_run` returns an independent RunSnapshot; create/save return revisions.
Receipt absence is None, corruption is an error. Writes require this store/run's
active lease. Tokens are run/namespace scoped, not lease owner/fencing tokens.
Receipts are immutable; identical repeats need live ownership. Sealed finite
JSON is limited to 8 MiB per document including UTF-8 bytes. Public APIs return
no driver objects. The legacy `Harness(workflow, run_dir)` and filesystem CLI
remain supported; the adapter adds no new workflow interpreter.

## Deployment and safety

- All reads/writes use the authoritative writable primary, never replicas/caches.
  Tables must be permanent/logged; fsync/full_page_writes must be on, effective
  synchronous_commit on or remote_apply. Existing remote_apply is preserved.
  Primary/WAL guards run on every operation/reconnection.
- Mount immutable workflow, prose, schema, evidence and reviewed tool assets at
  identical absolute paths across workers. Keep executables, validator versions
  and Runtime configuration identical. Drift fails before dispatch. PostgreSQL
  moves run state, not assets or private tool scratch.
- Synchronize worker/database clocks and avoid abrupt clock steps. Expiry uses
  fresh clock_timestamp() after the lease-row lock; local ownership uses a
  conservative monotonic deadline starting before the request, not at reply.
- Default lease/renewal 60s/15s. Duration >=15s; renewal >=1s and <=duration/3;
  renewal + operation budget + 1s must be less than duration. Default total I/O
  budget 10s, pool/connect 5s, row lock 1s, statement 5s. Deadlines cover pool,
  network and COMMIT waits. Stalled connections are quarantined; unresolved
  operations retain capacity and prevent unsafe close.
- Default lazy pool bounds per store/process: 8 ordinary + 4 renewal connections,
  maximum 4 active leases. Renewal has reserved capacity. Multiply capacity
  across replicas/namespaces; do not create a pool per HTTP request. Applications
  still own scheduling, model concurrency and quotas.
- Construct after fork; do not share across processes. Drain executions before
  close/context exit. Threads can share a store; use a separate Harness per run.
- Namespaces are trusted isolation keys, **not authorization or DB row-level
  security**. A shared DB role can directly access other namespaces. Derive
  namespace/run ownership from authenticated server state, never browser/model
  input. Applications own tenant authorization and admission policies.
- Raw status state contains private inputs, evidence, responses and history.
  Products must expose a filtered authorized view, not the operator demo JSON.
- Prose frontmatter requests tools; Runtime/workflow permissions authorize them.
  Neither grants database permissions. No HTTP service, queue, PostgreSQL server
  or historical file importer is included.
- Fencing stops stale DB mutations, not external tool/model effects. Use
  application-owned idempotency keys. Pending calls without receipts require
  explicit fresh retry consent, not automatic redispatch. Unknown token usage
  may still prevent a token-budgeted retry; abandoned calls retain their budget.
- Acknowledged WAL durability is not zero-loss asynchronous failover. A lagging
  promoted primary or older backup can lose receipts/generations. Require
  operator replication guarantees where needed; do not promise exactly-once
  external effects from this adapter.

## Errors and recovery

| Code | Action |
| --- | --- |
| store_uninitialized | Operator runs init, applies grants, then doctor. |
| store_incompatible | Check role/version/primary/WAL settings and intact logged schema; no automatic repair. |
| store_unavailable | Restore primary connectivity and reload status. outcome_unknown means a commit may have succeeded; never blindly repeat writes/effects. |
| run_busy | Another worker owns execution; back off without launching another call. |
| lease_lost | Stop dispatch/admission/writes, discard late output; acquire fresh execution and reconcile durable state. |
| revision_conflict | Show the user's current pause and require a new explicit decision. |
| store_busy | Drain active/queued/renewal work; construct a new store after fork. |
| receipt_conflict / store_corrupt | Stop; investigate evidence without overwriting it. |

## Development verification

Core tests need no database/driver. Adapter tests use disposable databases and
synthetic inference, never TokenProxy. Required mode fails rather than skips
missing infrastructure. Select Podman/Docker explicitly for crash/standby gates:

```sh
python -m pip install -e '.[test]' -e './adapters/postgres[test]'
python adapters/postgres/tests/support/local_cluster.py start --engine podman --version 16
# Retain the printed ownership.json path as FIXTURE_MANIFEST.
python adapters/postgres/tests/support/local_cluster.py test --manifest "$FIXTURE_MANIFEST"
python adapters/postgres/tests/support/local_cluster.py stop --manifest "$FIXTURE_MANIFEST"
```

Repeat with version 18. Stop validates exact IDs/names/ownership labels before
removing only owned containers/volumes/network. Generated fixture networks and
loopback ports use synthetic trust authentication, never production defaults.
# Lease registration candidate

The unpublished 0.1.1 candidate transfers acquisition capacity into registered
session capacity atomically under the existing store mutex. A registering lease
can no longer be counted twice while maintenance is scheduled. The database
storage/fencing contract is unchanged. A unit scheduling-boundary regression and
an owned PostgreSQL 16/18 race regression cover the transition.
