# Pluggable Harness run storage and a separate PostgreSQL adapter

Date: 2026-10-08. Status: design specification awaiting written-spec approval.

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
   synchronous PostgreSQL driver/pool. Publish their compatibility range and test
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
| `load_run(run_id)` | Return a bounded state snapshot and storage revision, or `RunNotFound` |
| `create_run(run_id, state, lease)` | Create once under valid ownership; reject duplicate identities |
| `save_run(run_id, state, expected_revision, lease)` | Atomically compare revision/ownership and persist the next snapshot |
| `load_receipt(run_id, invocation_id)` | Read a bounded immutable receipt or report absence |
| `save_receipt(run_id, invocation_id, receipt, lease)` | Persist once; identical repeat is idempotent, conflicting repeat is rejected |

Lease sessions provide `check_valid()`; renewable implementations maintain
ownership until release or failure. Engine code uses these semantics rather than
filesystem paths or provider-specific transactions. The implementation plan will
define concrete type signatures, not change these guarantees.

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
UUID as both their storage run identifier and checkpoint `run_id`. Legacy file
runs retain their existing internal UUID and run-directory addressing.

Add a public, read-only status operation through the store. Execution requires
readiness and lease ownership before creating pending work or calling Runtime.
Never fall back to local storage when an explicit external backend fails.

Public connection/pool and store lifecycle is explicit (`close()` and context
manager support). A process may share a pool/store across independent runs, but
not an execution lease or Harness instance. Reconstruct the store after a process
fork; do not inherit live connections or renewal threads.

## PostgreSQL storage and ownership

Use an adapter-owned `prosaic_harness` schema with version metadata, run, lease
and receipt tables. Keys include namespace and run identifier; receipt keys also
include invocation identifier. Run rows hold the checkpoint document and
monotonically increasing revision. Separate lease rows hold lease owner, fencing
generation and expiry, allowing ownership acquisition before a run exists.
Receipt rows hold immutable documents and their hashes, with a foreign key to
the run. Creating a run checks the lease in the same short transaction. Retain
lease fencing generations across ownership releases and takeovers.
No arbitrary schema/table name comes from workflow or user input.

Acquisition atomically admits one owner when a lease is absent or expired, and
increments its fencing generation. Renew, release, checkpoint writes and receipt
writes compare owner and generation; writes also require an unexpired lease.
The database clock determines expiry. A replaced owner cannot renew, release or
write through an old token. No pooled connection or transaction remains held for
the whole model invocation.

Default lease duration is 60 seconds and renewal interval 15 seconds. Both are
operator-configurable; validate duration >= 15 seconds, interval >= 1 second and
interval <= duration / 3. Connection/acquisition/query waits must be bounded.
The renewal loop uses short transactions, tracks the last confirmed expiry and
stops on release. A failed renewal is treated conservatively as lost ownership;
the execution cooperatively cancels and rejects further persistence/admission.

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
2. Save the pending invocation and consumed call budget before model dispatch.
3. Execute Runtime outside a database transaction under cooperative cancellation.
4. Save the sealed receipt before admitting output and advancing the checkpoint.
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

Human pauses hold no lease or database connection while waiting. A resume request
reacquires ownership, revalidates state/receipts/evidence and validates the declared
choice/response before committing. Concurrent responses cannot both advance the
same checkpoint. File and database backends enforce the same admission rules.

## Initialization and diagnostics

The adapter CLI provides these proposed commands:

```sh
prosaic-harness-postgres init --dsn-env DATABASE_URL
prosaic-harness-postgres doctor --dsn-env DATABASE_URL
```

`init` connects to an existing database and explicitly creates or upgrades only
the owned schema. Serialize concurrent initialization with a database advisory
lock held within a short migration transaction. Record the schema version in the
same transaction. Re-running on the current version is a no-op. Reject unknown
newer schemas. First-release migration creates the initial schema; subsequent
migrations must be versioned, reviewed and non-destructive. Coordinate upgrades
with application maintenance rather than migrating beneath active workers.

`doctor` is read-only: verify connectivity, compatible schema version and the
required runtime table privileges. It does not create tables or claim that a
read-only privilege check proves live concurrency behavior. Offer an explicit
`--check-write` option to perform bounded disposable write/lease/receipt checks
in a diagnostic namespace, cleaning its own records and reporting cleanup errors.
Neither mode contacts a model. Exit nonzero on incompatibility or missing access.

Workers run `check_ready()` at startup before accepting work and verify readiness
when acquiring execution sessions. Separate migration and runtime roles: only
the migration role requires schema/DDL permission. Document the required grants
and a copy/paste setup using secret environment variables. No schema destruction,
reset command or implicit migration is included in this first release.

Errors expose stable codes such as `store_uninitialized`, `store_incompatible`,
`store_unavailable`, `run_busy`, `lease_lost`, `revision_conflict`,
`receipt_conflict` and `run_not_found`. Never expose DSNs, database-driver messages,
credentials, prompt contents or stored outputs in default diagnostics. Preserve
deployment TLS requirements; do not silently disable certificate verification.

## Consumer walkthrough and deployment limits

Provide a complete two-worker example: install both packages, configure an
existing database, initialize, run doctor, execute a synthetic workflow to a
human pause on worker A, then reconstruct and resume on worker B. Use immutable
workflow/prose/schema assets available to both workers and a matching evidence
snapshot. Database-backed run state does not automatically distribute files
needed by Runtime tools; read roots/resources must exist with matching hashes
on the executing worker. Local CLI scratch remains ephemeral.

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
- Lease expiry, renewal, takeover, and rejection of an old worker's checkpoint,
  receipt, renewal and release operations.
- Slow invocation exceeding the initial lease duration with successful renewal;
  renewal failure causes cancellation/no admission and no automatic redispatch.
- Process death before dispatch, after pending persistence, after receipt commit,
  and before checkpoint advancement. Existing receipt recovery executes no second
  model call; missing receipts require explicit retry consent.
- Connection loss and uncertain commits, receipt conflict/corruption, concurrent
  human responses and workflow/evidence/fingerprint changes.
- A full worker-A pause/worker-B resume demonstration, valid human response
  admission, and safe rejection of invalid/stale responses.

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
