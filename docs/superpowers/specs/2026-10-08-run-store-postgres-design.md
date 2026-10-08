# Pluggable Harness run storage and a separate PostgreSQL adapter

Date: 2026-10-08. Status: written specification approved for implementation planning.

Revised after design review: precise lease transactions, revision-bound human
responses, bounded renewal/lifecycle behavior, durable database commits,
primary-only reads and an explicit two-worker setup.
All new interfaces and commands below are proposed, not available in this release.

## Intent and agreed scope

Run Harness workflows in horizontally scaled application containers without
binding durable run state to one container's filesystem. Keep PostgreSQL out of
Harness core, while providing a separately installable, tested reference adapter
with straightforward initialization, diagnostics and cross-worker resume.

Success means a consumer can install the adapter, explicitly initialize an
existing database, verify readiness, start a run on worker A, and resume it on
worker B without losing receipts, human decisions or existing admission rules.

Harness remains the sole workflow-state writer. Applications own authentication,
tenant authorization, scheduling, quotas and external tool-side-effect policy.
This change does not provision a database, add a job queue or turn Harness into an
HTTP service. No automatic retry of an interrupted invocation is introduced.

## Packaging and ownership

1. `prosaic-harness` owns the public storage protocol, storage errors, engine
   integration, filesystem implementation and reusable conformance tests. Its
   ordinary installation must not install or import a PostgreSQL driver.
2. `prosaic-harness-postgres` owns database connections, migrations, leases and
   PostgreSQL persistence. Maintain it as a separate distribution under
   `adapters/postgres/`, with its own `pyproject.toml` and `src/` tree in this repo.
   Root package discovery remains limited to root `src/`; the adapter is not
   bundled in the core wheel. No new remote repository is required.
3. The adapter depends on a compatible Harness storage-contract version and a
   PostgreSQL driver/pool behind the synchronous public storage interface.
   Bounded nonblocking I/O may be used internally; consumers need no event loop.
   Publish their compatibility range and test
   it; do not rely on private engine helpers as a public embedding interface.

The application explicitly constructs and injects a trusted adapter. No arbitrary
module path is loaded from agent prose, workflow YAML or model output.

## Public storage contract

The protocol is synchronous to match the existing engine. Expose `RunStore`,
`FileRunStore`, a lease/session abstraction, and safe typed storage errors.
Namespace-scoped stores expose the following semantic operations:

| Operation | Required behavior |
| --- | --- |
| `initialize()` | Explicit, repeatable backend setup; never invoked implicitly by execution |
| `check_ready()` | Validate storage-contract/schema compatibility and access; no inference or migrations |
| `lease(run_id)` | Acquire exclusive ownership or raise `RunBusy`; release on context exit |
| `load_run(run_id)` | Return `RunSnapshot(state, revision)`, or `RunNotFound` |
| `create_run(run_id, state, lease)` | Create once under valid ownership; return its revision; reject duplicate identities |
| `save_run(run_id, state, expected_revision, lease)` | Atomically compare revision/ownership, persist the next snapshot and return its revision |
| `load_receipt(run_id, invocation_id)` | Read a bounded immutable receipt or report absence |
| `save_receipt(run_id, invocation_id, receipt, lease)` | Persist once; identical repeat is idempotent, conflicting repeat is rejected |

Lease sessions provide `check_valid()`; renewable implementations maintain
ownership until release or failure. Engine code uses these semantics rather than
filesystem paths or provider-specific transactions. The implementation plan will
define concrete type signatures, not change these guarantees.

`RunSnapshot.state` is an independent, bounded checkpoint copy;
`RunSnapshot.revision` is an opaque equality token for that committed checkpoint.
Consumers must not parse, increment or manufacture revision tokens. A status read
does not acquire an execution lease, renew one, or promise that its snapshot will
remain current after returning. PostgreSQL may encode its increasing revision;
FileRunStore may derive a token from the sealed checkpoint under its existing
file lock. Neither requires adding a field to checkpoint-v2. Lease owners and
fencing generations are private to the adapter and never user-facing tokens.

Namespace/run/invocation identifiers are bounded values, never filesystem paths
or SQL identifiers. Validate before access; parameterize database values. Every
operation, including receipt reads, is namespace- and run-scoped. Namespace
selection must come from trusted application context: it is not authentication.
The application must authorize every status/resume/human-decision request.

Storage revisions and fencing tokens are envelope metadata, not edits to the
existing sealed checkpoint body. Preserve checkpoint-v2 validation, receipt
hashes, ledger checks, workflow/prose/schema fingerprints and output admission.
Preserve existing JSON bounds (8 MiB per persisted document), finite values and
independent snapshots. Never persist an unsupported or malformed document.
Apply the byte limit to serialized UTF-8 payloads before writing and before
decoding stored data; preserve the canonical JSON/seal rules across backends.
Do not let a driver's automatic JSON decoding bypass the bounded read path.
Stores enforce document/envelope bounds; the engine still validates workflow
state, receipt relationships and admission policy. Unkeyed checkpoint seals
detect corruption, not malicious writes by a privileged database operator.

Keep local asset reads and bounded JSON helpers separate from run persistence.
Introducing RunStore must not redirect Workflow prose, schema or evidence reads
into the database, or weaken their existing filesystem safeguards.

## Engine API and backward compatibility

Retain `Harness(workflow, run_dir, ...)` and current CLI commands. Adapt that path
through `FileRunStore`; existing `run.json`, `run.lock` and `attempts/` layouts,
descriptor-pinned no-symlink checks and lock behavior remain intact. Existing
valid filesystem runs must still resume, including validated human responses.
Filesystem backend initialization has no database/schema prerequisite; its
existing safe directory creation on first execution remains supported. Explicit
`initialize()` refers to backend schema/setup, not creating every run directory.

Add an explicit alternative `Harness(workflow, store=store, run_id=run_id, ...)`.
Supplying both `run_dir` and `store`, or omitting a run identifier for an external
store, is a configuration error. Database-backed new runs use a host-generated
32-character lowercase UUID hex as both their storage run identifier and
checkpoint `run_id`. Legacy file runs retain their existing internal UUID and
run-directory addressing.

Add `Harness.status()` returning `RunSnapshot` through the store; `run()` and
`resume()` retain their existing checkpoint-dictionary return shape. Add
`expected_revision=` to `resume()` as described below. Execution requires
readiness and lease ownership before creating pending work or calling Runtime.
Never fall back to local storage when an explicit external backend fails.

Public connection/pool and store lifecycle is explicit (`close()` and context
manager support). A process may share a pool/store across independent runs, but
not an execution lease or Harness instance. Reconstruct the store after a process
fork; do not inherit live connections or renewal threads.
An attempted `close()` with active execution/renewal sessions fails explicitly
without closing their pool. Applications first stop accepting work and drain or
cancel active executions. Session exit stops and joins its renewal activity
within a bounded shutdown budget before the store closes; no renewal may access
a closed pool. Cleanup failures do not replace the original execution error.

## PostgreSQL storage and ownership

Use an adapter-owned `prosaic_harness` schema with `schema_version`, `runs`,
`leases` and `receipts` tables. Keys include namespace and run identifier;
receipt keys also include invocation identifier. Run rows hold the checkpoint
document and monotonically increasing revision. Separate lease rows hold lease owner, fencing
generation and expiry, allowing ownership acquisition before a run exists.
Receipt rows hold immutable documents and their hashes, with a foreign key to
the run. Creating a run checks the lease in the same short transaction. Retain
lease fencing generations across ownership releases and takeovers.
No arbitrary schema/table name comes from workflow or user input.

### Durability and authoritative reads

All adapter tables must be permanent, logged tables, never temporary or
unlogged. PostgreSQL documents the crash-recovery limitations of unlogged
tables in [CREATE TABLE](https://www.postgresql.org/docs/current/sql-createtable.html).
Require `fsync=on`, `full_page_writes=on` and an effective
`synchronous_commit` of `on` or `remote_apply` for every modifying transaction.
Validate these requirements before writes; never weaken a stricter configured
commit mode. Readiness and doctor fail closed on unsafe or unverifiable settings
or table persistence. They do not change global database configuration.
These requirements follow PostgreSQL's
[WAL durability settings](https://www.postgresql.org/docs/current/runtime-config-wal.html).

Wait for successful durable commit acknowledgement before dispatching Runtime
after a pending checkpoint, or admitting a receipt/decision as persisted.
Timeout or connection loss during commit is an unknown outcome, not successful
persistence; use the reconciliation rules below. Every modifying transaction,
including lease acquisition/renewal and schema initialization, follows the same
durability policy.

Use the same authoritative writable-primary endpoint for all adapter access,
including status, checkpoint and receipt reads. No replica/read-pool routing
or stale caches may decide receipt absence, revisions or recovery. Validate
primary/writable state on connection checkout and transaction entry; reject
standby/read-only connections before accessing run data. With libpq-based
drivers, use `target_session_attrs=read-write` as an additional connection guard,
not a substitute for validating pooled connections. See PostgreSQL's
[connection selection](https://www.postgresql.org/docs/current/libpq-connect.html).
Local lease-deadline polling remains query-free as specified below.

The deployment must provide one writable authority and fence a former primary
before accepting work on its replacement; adapter leases cannot fence two
independently writable databases. Ordinary database restart/crash recovery is
covered by this durability contract. Asynchronous replication/failover or backup
restoration can lose acknowledged state, including receipts and fencing history;
primary-only reads do not remove that risk. See PostgreSQL's
[replication guarantees](https://www.postgresql.org/docs/current/warm-standby.html).
The MVP does not provision HA or promise zero-loss asynchronous failover. After
known or suspected state rollback, the operator stops affected executions and
reconciles external effects before resuming; do not automatically redispatch.
Lossless failover requires separately validated deployment replication/fencing
guarantees, not an adapter setting alone.

### Transaction rules

Acquisition serializes creation of an absent lease row and admits one owner when
the lease is released or expired, incrementing its generation. Every guarded
mutation locks the lease row first, then the run row if needed, then a receipt
row if needed. Ownership validation and mutation occur in the same short
transaction. An out-of-transaction `check_valid()` cannot authorize a later write.
The consistent lock order and transaction-held row locks follow
[PostgreSQL's locking semantics](https://www.postgresql.org/docs/current/explicit-locking.html).
Immutable receipt reads need no additional update lock; uniqueness and guarded
insertion enforce their immutability without granting runtime receipt updates.

After acquiring the lease row lock, read `clock_timestamp()` to compare expiry
and calculate a new lease expiry. Do not use `now()`/`transaction_timestamp()`:
their transaction-start time can be stale after a lock wait. PostgreSQL
documents this distinction in its
[current-time functions](https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT).

Renewal requires matching owner/generation **and an unexpired lease**. An expired
owner cannot revive its lease even if nobody has taken over. Checkpoint and
receipt writes require the same conditions; even an identical receipt repeat
checks ownership before returning success. Release compares owner/generation
and clears ownership without deleting the generation; an old release cannot
affect a replacement owner. Acquisition of a new session is not renewal of a
lost one and never permits an old execution to continue.

The guarded mutation is serialized against takeover until transaction end.
Do not promise that a commit physically finishes before the expiry instant:
a short transaction can cross it, but a new owner cannot acquire the locked row
until that transaction ends. Checkpoint revision comparison occurs inside that
same transaction. No connection or transaction is held during model execution.

### Renewal and loss of ownership

Default lease duration is 60 seconds and renewal interval 15 seconds. Both are
operator-configurable; validate duration >= 15 seconds, interval >= 1 second and
interval <= duration / 3. Default pool/connect timeouts are 5 seconds, row-lock
timeout 1 second, statement timeout 5 seconds, and total renewal-operation budget
10 seconds. These phase limits share the total budget, not consecutive unlimited
waits. Configure PostgreSQL timeouts per adapter transaction, not globally;
[server timeout behavior](https://www.postgresql.org/docs/current/runtime-config-client.html)
does not replace a client-side bound on pool, transport and commit waits.
All execution storage operations, including acquisition, reads and release, use
bounded waits; migration commands have a separately documented maintenance budget.
Reject settings where renewal interval plus total renewal budget plus a safety
margin (at least 1 second) reaches the lease duration. Shorter leases therefore
also require shorter operation budgets.

Reserve bounded connection capacity for renewal; ordinary status/checkpoint
traffic cannot consume it. Limit active leases to that capacity instead of
allowing an unbounded renewal backlog. The implementation plan must specify the
pool arrangement, transport bounds and shutdown budget and test saturation.

Use a conservative local monotonic deadline derived from the time **before** the
successful acquisition/renewal request plus its lease duration. Never set the
deadline to response-arrival time plus duration. `check_valid()` uses this cached
deadline and a sticky loss flag; Runtime cancellation polling must not issue a
database query each time. The database remains authoritative for every write.

Renewal failure or reaching the conservative deadline marks the session lost.
A late renewal response cannot clear that flag. Stop renewal on release; reject
further persistence/admission and cooperatively cancel execution. Preserve
`lease_lost` as the cause: the engine must not turn it into ordinary cancellation
and then try to persist a durable blocked checkpoint through the stale lease.

Check ownership before dispatch, at Runtime cancellation/tool boundaries, after
Runtime returns, and before admission/persistence. Do not invent a durable
"blocked" update when ownership is already lost: return a safe storage error,
leaving recovery to the next valid owner. A non-cooperative callback may still
finish an external side effect; lease fencing does not provide exactly-once tool
execution. Applications need idempotency keys and/or externally enforced fencing
for side-effecting integrations.

## Invocation persistence and recovery

Preserve the current ordering:

1. Acquire ownership, load/validate the run, and check immutable workflow evidence.
2. Save the pending invocation and consumed call budget, and receive durable
   commit acknowledgement before model dispatch.
3. Execute Runtime outside a database transaction under cooperative cancellation.
4. Durably commit the sealed receipt before admitting output and advancing
   the checkpoint.
5. Persist the resulting checkpoint with revision and lease checks.

Receipt persistence and checkpoint advancement may be separate short transactions.
The deliberate gap is recoverable: if a valid receipt exists for the saved pending
invocation, a new owner validates and adopts it without another model call.
If no receipt exists, preserve `interrupted_call` and explicit retry consent.
Expired ownership alone never authorizes an automatic model/tool retry.

Connection loss after a commit can leave its outcome unknown. Do not blindly
repeat dispatch or rewrite state. Reload the authoritative revision/receipt under
valid ownership to determine whether a storage operation committed; if unable to
determine it, return `StoreUnavailable` and stop. Identical receipt writes are
safe to reconcile; inconsistent receipts are corruption/conflict errors.

### Human decisions and stale requests

Human pauses hold no lease or database connection while waiting. A consumer reads
`status()`, displays the permitted choices/response form, and returns that
snapshot's revision with the submitted decision. For external stores,
`resume(choice=..., response=..., expected_revision=...)` requires that token;
explicit `retry_interrupted=True` consent also requires it. A missing token is
a configuration/input error, not permission to apply a decision to current state.
Legacy file-based resume/CLI callers may omit it; supplied tokens are enforced
on both backends without changing the sealed checkpoint format.

Under newly acquired ownership, reload and validate the checkpoint and compare
the expected revision before decision mutation or model dispatch. Mismatch
raises `revision_conflict` without applying the response or calling Runtime.
Then revalidate receipts, fingerprints/evidence and the declared choice/response
before committing. A repeated choice name at a later pause does not make an old
approval valid. File and database backends retain the same admission rules.

After a stale response the application refreshes status and asks for a new
decision; it must not automatically attach the old decision to the new token.
Concurrent submissions for one revision cannot both advance it. An uncertain
decision commit is reconciled by reloading under ownership, not by blindly
reapplying the response. This API does not promise an application-level
idempotent HTTP response; an already-committed duplicate may return a conflict.

## Initialization and diagnostics

The adapter CLI provides these proposed commands:

```sh
prosaic-harness-postgres init --dsn-env HARNESS_MIGRATION_DATABASE_URL
prosaic-harness-postgres doctor --dsn-env HARNESS_DATABASE_URL
```

`init` connects to an existing database and explicitly creates or upgrades only
the owned schema. Serialize concurrent initialization with a transaction-level
advisory lock held within a short migration transaction, released automatically
on commit/rollback. Never leave a session-level advisory lock on a pooled
connection. Record the schema version in the same transaction. Re-running on
the current version is a no-op. Reject unknown
newer schemas. First-release migration creates the initial schema; subsequent
migrations must be versioned, reviewed and non-destructive. Coordinate upgrades
with application maintenance rather than migrating beneath active workers.

`doctor` is read-only: verify connectivity, compatible schema version and the
required runtime table privileges, logged tables, crash-safe settings and a
writable-primary connection. It does not create tables or claim that a
read-only privilege check proves live concurrency behavior. Offer an explicit
`--check-write` option to perform bounded disposable write/lease/receipt checks
in a diagnostic namespace, cleaning its own records and reporting cleanup errors.
Neither mode contacts a model. Exit nonzero on incompatibility or missing access.

Workers run `check_ready()` at startup before accepting work and verify readiness
when acquiring execution sessions. Connection/transaction guards also apply
after pool reconnects; a startup check is not permanent proof of safe routing or
durability. Unsafe database configuration returns `store_incompatible` with a
safe remedy; connectivity loss returns `store_unavailable`. Separate migration
and runtime roles: only the migration role requires schema/DDL permission.
Document the required grants
and a copy/paste setup using secret environment variables. No schema destruction,
reset command or implicit migration is included in this first release.

Errors expose stable codes such as `store_uninitialized`, `store_incompatible`,
`store_unavailable`, `run_busy`, `lease_lost`, `revision_conflict`,
`receipt_conflict` and `run_not_found`. Never expose DSNs, database-driver messages,
credentials, prompt contents or stored outputs in default diagnostics. Preserve
deployment TLS requirements; do not silently disable certificate verification.

| Error | Consumer action |
| --- | --- |
| `store_uninitialized` | Have the migration operator run `init`; do not create local fallback state |
| `store_incompatible` | Deploy a compatible adapter/schema with coordinated maintenance; no automatic downgrade |
| `store_unavailable` | Restore connectivity; reload to reconcile uncertain writes before deciding on retry |
| `run_busy` | Another worker owns this run; wait or report conflict, not a second dispatch |
| `lease_lost` | Stop this execution; a new owner reloads and reconciles receipts before any explicit retry |
| `revision_conflict` | Refresh status; request a new human decision for the new revision |
| `receipt_conflict` | Stop and investigate conflicting/corrupt evidence; do not overwrite it |
| `run_not_found` | Check the authorized namespace/run identity; do not probe other tenants |

Configuration errors (including unsafe lease timings or a missing decision
revision) fail before inference. Fingerprint/evidence drift retains the existing
fail-closed behavior; deploy matching assets or deliberately start a new run.

## Consumer walkthrough and deployment limits

### Proposed quick start

Ship a self-contained `examples/postgres/pause.yml` fixture with a human-only
pause (`approve`/`reject`) and no model calls, plus a separate synthetic-model
fixture exercising pending calls and receipt recovery. Both include their
required workflow/runtime assets. The following is the target SDK walkthrough,
not instructions for an already implemented adapter.

From the repository root, install the two separate distributions:

```sh
python -m pip install . ./adapters/postgres
```

An operator supplies an existing database and two pre-created login roles. Set
`HARNESS_MIGRATION_DATABASE_URL` and `HARNESS_DATABASE_URL` using the deployment's
secret manager; do not put credential values into these examples, prose or logs.
Both roles need `CONNECT` on the existing database. The migration role needs
`CREATE` on that database for initial schema creation and ownership/DDL access
to the owned schema thereafter; it does not need `CREATEDB`. The runtime role
does not need DDL access. Both DSNs must target the same writable primary, not a
read-replica/load-balanced reader endpoint. The operator retains crash-safe WAL
settings and defines failover fencing/recovery policy; `init` and `doctor` do not
configure the database cluster. Initialize with the migration role:

```sh
prosaic-harness-postgres init --dsn-env HARNESS_MIGRATION_DATABASE_URL
```

The migration operator then grants runtime access (here `harness_runtime` is the
pre-created runtime role; substitute its trusted deployment name). These are
object-scoped [PostgreSQL grants](https://www.postgresql.org/docs/current/sql-grant.html),
not permission declarations in agent prose:

```sql
GRANT USAGE ON SCHEMA prosaic_harness TO harness_runtime;
GRANT SELECT ON ALL TABLES IN SCHEMA prosaic_harness TO harness_runtime;
GRANT INSERT, UPDATE ON TABLE prosaic_harness.runs, prosaic_harness.leases
    TO harness_runtime;
GRANT INSERT ON TABLE prosaic_harness.receipts TO harness_runtime;
```

The initial design requires no sequence privileges or runtime deletion rights.
Future migrations must document grants for new objects. Verify with runtime
credentials; optionally test disposable writes using the migration role, which
also has the deletion rights needed to clean up diagnostic records:

```sh
prosaic-harness-postgres doctor --dsn-env HARNESS_DATABASE_URL
prosaic-harness-postgres doctor --dsn-env HARNESS_MIGRATION_DATABASE_URL --check-write
```

Worker A starts and pauses a run. Use the same immutable workflow image/mounts
on worker B, for example with the fixture mounted at `/workflows/pause.yml`:

```python
import uuid
from prosaic_harness import Harness, Workflow
from prosaic_harness_postgres import PostgresRunStore

# Supplied by trusted application context after authorization, not model output.
trusted_namespace = "example-tenant"
run_id = uuid.uuid4().hex
workflow = Workflow.load("/workflows/pause.yml")

with PostgresRunStore.from_env(
    "HARNESS_DATABASE_URL", namespace=trusted_namespace
) as store:
    store.check_ready()  # Never calls initialize().
    harness = Harness(workflow, store=store, run_id=run_id)
    state = harness.run({"task": "Review this synthetic request."})
    assert state["status"] == "waiting"
    snapshot = harness.status()
    # Pass this identity/revision to the authorized UI with its pause choices.
    decision_target = {"run_id": run_id, "revision": snapshot.revision}
```

Worker B receives that decision target and the user's explicit choice. Resolve
the namespace from trusted application context again and authorize the request:

```python
from prosaic_harness import Harness, Workflow
from prosaic_harness_postgres import PostgresRunStore

# These request values carry no authorization by themselves.
run_id = decision_target["run_id"]
expected_revision = decision_target["revision"]
trusted_namespace = "example-tenant"  # Resolve from authorized app context again.
workflow = Workflow.load("/workflows/pause.yml")

with PostgresRunStore.from_env(
    "HARNESS_DATABASE_URL", namespace=trusted_namespace
) as store:
    store.check_ready()
    harness = Harness(workflow, store=store, run_id=run_id)
    state = harness.resume(choice="approve", expected_revision=expected_revision)
    assert state["status"] == "completed"
```

Never replace `expected_revision` with a newly fetched revision just to make a
failed request succeed. A production application must redact/filter status before
displaying it: checkpoints can contain sensitive inputs, outputs and evidence.
These snippets run in separate worker processes; the application transports the
decision target, not a Harness instance, connection or lease. The adapter CLI
handles setup/diagnostics; the SDK runs workflows without a second CLI engine.

### What must be shared between workers

Use compatible core/adapter/Runtime versions and identical immutable workflow,
prose, schemas, validator versions and sealed runtime/tool configuration. A
matching evidence hash alone is not enough: the existing workflow fingerprint
includes runtime configuration and custom-tool descriptors; CLI descriptors
include the resolved executable path and manifest hash. Keep mount, executable
and interpreter paths stable across workers, as well as endpoint/profile,
read-root and sandbox policy settings. Do not weaken fingerprints for portability.

Database-backed state does not distribute files needed by tools. Read resources
and evidence must remain available with matching contents and permissions on
the executing worker. Local CLI scratch remains ephemeral. Workflow deadlines
remain the stored absolute deadline, not a fresh budget on each worker; synchronize
host clocks because existing engine run-deadline checks use host wall time.
Lease expiry uses database time and is a separate mechanism.

The reference example takes a trusted namespace, uses separate runtime/migration
credentials, never logs secrets, and demonstrates the expected failure messages
for omitted initialization and conflicting workers. Include a disposable
container-based PostgreSQL fixture for local tests, without treating that fixture
as production database provisioning. No Studio or Echelon migration is part of
this change.

Do not call the adapter a distributed scheduler. Applications assign runs to
workers and manage endpoint-wide concurrency, HTTP overload, authentication and
retention/backups. This release has no automatic filesystem-to-database importer
or historical-run rewrite; start new external-store runs while preserving the
ability to resume existing filesystem runs.

## Verification and acceptance

Ship reusable backend conformance tests covering create/load/status, bounded and
finite documents, snapshot independence, duplicate run creation, immutable
receipts, revision conflicts, exclusive ownership, isolation of namespaces and
safe errors. Run the same engine behavior tests on the filesystem and PostgreSQL
implementations. In-memory doubles are not distributed-safety evidence.

Require real PostgreSQL tests using independent processes/connections for:

- Parallel execution of different runs and rejection of concurrent ownership of
  one run; wrong-namespace status, receipt and resume access cannot cross over.
- Concurrent initialization, initialization rollback and compatible/incompatible
  schema detection; read-only doctor does not mutate schema or contact a model.
- Readiness/doctor reject unsafe WAL settings, unlogged tables and standby or
  read-only connections. Pool reconnects cannot bypass primary/durability guards.
  A session/DSN setting of `synchronous_commit=off` cannot authorize dispatch;
  retain a configured `remote_apply` mode rather than downgrading it.
- Crash and restart a disposable PostgreSQL instance after acknowledged pending, receipt
  and decision commits: each remains present after recovery. Delay/drop commit
  acknowledgements and prove no premature dispatch/admission or blind redispatch.
  Use a primary/standby fixture to prove standby routing is rejected even when
  it contains an older checkpoint or lacks an already-committed receipt.
- Lease expiry, renewal, takeover, and rejection of an old worker's checkpoint,
  receipt, renewal and release operations; an expired lease cannot renew even
  without takeover, and generations survive release/reacquisition.
- Hold a lease-row lock until after expiry: a waiting mutation must use fresh
  database time after obtaining the lock and reject stale ownership. Exercise
  the consistent lock order and receipt idempotency under stale ownership.
- Slow invocation exceeding the initial lease duration with successful renewal;
  renewal failure causes `lease_lost`, no durable blocked write, no admission and
  no automatic redispatch. Saturate ordinary pool capacity without starving
  renewal; delayed responses cannot revive a locally lost session. Cancellation
  polling performs no database reads; test bounded shutdown and active-store close.
- Process death before dispatch, after pending persistence, after receipt commit,
  and before checkpoint advancement. Existing receipt recovery executes no second
  model call; missing receipts require explicit retry consent.
- Connection loss and uncertain commits, receipt conflict/corruption, concurrent
  human responses and workflow/evidence/fingerprint changes.
- A full worker-A pause/worker-B resume demonstration, valid human response
  admission, and safe rejection of invalid/stale responses. Reuse the same
  choice name at a later pause and prove that its earlier revision cannot approve
  it; cover missing tokens, stale retry consent and uncertain decision commits.
- Two workers with different resolved tool paths, runtime settings, validator
  versions or evidence must fail before dispatch/admission. Preserve the stored
  run deadline and remaining call/token budgets on takeover.
- Execute the documented quick start from clean installations with distinct
  migration/runtime roles. Confirm the runtime role cannot migrate or delete
  runs; diagnostic cleanup touches only its own disposable namespace, and
  default doctor performs no writes. Verify failure messages and secret redaction.

Run the full core suite and package builds; install both wheels into a clean
environment. Verify core-only import/install without PostgreSQL dependencies,
existing file-based CLI behavior and checkpoint-v2 compatibility. CI must require
the PostgreSQL integration lane for adapter acceptance, not pass by skipping it.
Use synthetic model servers/data; live inference is not required for storage
conformance and remains separately opt-in.

## Review boundary

This document specifies the approved approach, not implemented behavior. After
written-spec approval, prepare an implementation plan with concrete interfaces,
TDD milestones, migration/lease SQL, CI fixtures and dependency packaging. Do not
publish packages, create remote repositories or migrate consumers during design.
