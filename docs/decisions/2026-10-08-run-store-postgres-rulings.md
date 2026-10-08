# RunStore/PostgreSQL implementation rulings

Date: 2026-10-08. Status: accepted for this implementation and preserved for
local integration into `main`, as requested by the maintainer.

This is the durable record of the five implementation rulings and seven
whole-branch review boundary decisions. It records decisions already made;
it does not introduce new implementation behavior or authorize a release.
Implementation/review-fix history ends at `6b6f06e`; the originating branch was
`codex/harness-run-store-design`.

Use the stable `RUNSTORE-Rxxx` IDs in future issues, reviews and changes. Do not
silently erase or reinterpret a ruling: supersede it with a linked decision and
the evidence supporting that change. Local branch deletion does not remove
this record or the underlying commits.

See the [approved design](../superpowers/specs/2026-10-08-run-store-postgres-design.md),
[implementation plan](../superpowers/plans/2026-10-08-run-store-postgres.md),
[verification evidence](../run-store-verification.md) and
[operator setup](../../adapters/postgres/README.md).

## Implementation rulings

### RUNSTORE-R001 — Retain the approved feature checkout

Decision: implement in the existing dedicated feature-branch checkout instead
of creating another worktree.

Reason: the approved plan retained this branch; the checkout was clean and not
`main`. The chat's original workspace belonged to another repository.

Cost if wrong: feature edits have less checkout isolation than a separate
worktree. No edits were made directly on `main` during implementation.

### RUNSTORE-R002 — Classify readonly connection refusal as unavailable

Decision: readonly routing refused by libpq reports `StoreUnavailable`, rather
than `StoreIncompatible`.

Reason: `target_session_attrs=read-write` refuses the connection before SQL
guards can inspect its configuration. No run access or dispatch is admitted.

Cost if wrong: the operator receives connectivity/reconciliation guidance
instead of the more precise incompatible-configuration guidance.

### RUNSTORE-R003 — Run core and adapter suites separately

Decision: run both complete suites as separate pytest invocations.

Reason: they contain colliding test module names under default collection.
Separate invocations preserve the database-free core test lane.

Cost if wrong: combined collection requires import-mode/module-name adjustments;
neither suite is omitted.

### RUNSTORE-R004 — Combine required adapter and recovery CI gates

Decision: each PostgreSQL-major CI job runs adapter, crash/standby and packaging
gates using explicitly owned, loopback-only container fixtures.

Reason: health checks and exact ownership allow recovery tests without mutating
a shared service. Missing infrastructure or skipped required cases fail the lane.

Cost if wrong: CI jobs take longer; recovery coverage is not conditional.

### RUNSTORE-R005 — Guard connections inside bounded operations

Decision: check primary/durability settings inside every bounded operation,
rather than rely on pool check hooks that retry failures.

Reason: retrying check hooks can conceal incompatible configurations. Admission
must fail with a safe error before run-data access.

Cost if wrong: a transient connection failure stops the operation and requires
reconciliation instead of transparently recovering through a pool retry.

## Review boundary decisions

### RUNSTORE-R006 — Trust privileged database administration

Decision: malicious schema owners and direct privileged database tampering are
outside the adapter's protection boundary.

Reason: database administration is trusted. Seals detect corruption; they are
not authentication or protection against someone able to rewrite the database.

Cost if wrong: a compromised privileged actor can forge or destroy run state.
Applications must retain authorization; namespaces are not DB row-level security.

### RUNSTORE-R007 — Do not promise exactly-once effects or lossless failover

Decision: external-effect idempotency and zero-data-loss replication/failover
remain application/operator responsibilities.

Reason: fencing cannot undo a remote side effect or prevent restoring older
database state. These limitations are explicit in the adapter documentation.

Cost if wrong: effects can be duplicated and receipts/generations can be lost
after asynchronous failover, backup restoration or manual rollback.

### RUNSTORE-R008 — Allow bounded serialization overhead to differ

Decision: filesystem and PostgreSQL serialization overhead may differ near the
document-size limit.

Reason: both paths retain their byte bounds and fail closed; the difference
does not bypass controller admission or permit an oversized persisted document.

Cost if wrong: a near-limit payload may be rejected sooner on one backend.

### RUNSTORE-R009 — Preserve optional revisions for legacy file callers

Decision: legacy filesystem callers may continue omitting expected revisions.
External-store human decisions and explicit retry consent require them.

Reason: preserve the existing filesystem constructor/CLI contract while giving
shared storage mandatory stale-action fencing.

Cost if wrong: old filesystem applications do not receive mandatory protection
against stale human submissions until they adopt revision-aware calls.

### RUNSTORE-R010 — Leave existing filesystem fork cleanup unchanged

Decision: do not change the existing filesystem lock helper's inherited exit
semantics in this implementation.

Reason: the reviewer established no new regression in that helper. Construct
workers after fork; do not fork an active execution.

Cost if wrong: inherited cleanup during an active-file fork can affect another
process's lock. This is not a guarantee that active executions are fork-safe.

### RUNSTORE-R011 — Reconcile in-flight commits after local expiry

Decision: a fenced in-flight database transaction can become durable after local
ownership expiry; late output is not admitted and later execution reconciles
authoritative state.

Reason: loss of a reply or local timeout does not prove rollback. The lease-row
lock fences the transaction, and subsequent ownership/admission checks stop
stale continuation. Unknown commits are never blindly repeated.

Cost if wrong: a timed-out write may still be durable. Recovery must reload the
primary and reconcile receipts/decisions before any retry or external effect.

### RUNSTORE-R012 — Require deployment-specific routing validation

Decision: accept primary/stale-standby tests plus per-operation authority checks
without claiming every possible routing/failover topology has been exercised.

Reason: each operation rechecks primary/durability settings before data access;
no additional routing defect was established by review.

Cost if wrong: an untested deployment topology may need additional operational
validation. The operator must verify its own failover behavior.

## Review outcome

The fresh independent whole-branch reviewer found no Critical or Minor findings
and one Important/P2 queued-admission/lifecycle defect. It was fixed in `6b6f06e`
with a watched RED-to-GREEN regression and complete acceptance-suite reruns.
There are no deferred Minor findings. The decisions above do not waive that
fix or any required verification gate.
