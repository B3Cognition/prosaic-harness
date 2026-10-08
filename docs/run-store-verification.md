# RunStore/PostgreSQL implementation evidence

Local acceptance on 2026-10-08, branch `codex/harness-run-store-design`.
Core 0.6.0 and separate adapter 0.1.0 are development builds, not releases.
No consumer migration, remote push, package publication or database provisioning.

| Gate | Observed result |
| --- | --- |
| Core/full legacy suite | 153 passed, 37.71s after review fix, no PostgreSQL dependency |
| Real PostgreSQL 16 adapter lane | 77 passed, 90.44s after review fix, no skipped cases |
| Real PostgreSQL 18 adapter lane | 77 passed, 88.77s after review fix, no skipped cases |
| Worker/recovery/routing repeatability | Full lane, focused 17-test run and full lane passed before operator/packaging additions |
| Clean macOS/arm64 wheel environments | Core-only import without psycopg/adapter; both-wheel CLI/SDK init/doctor/write test and restricted-role cross-process pause/resume passed |
| Native Linux/arm64 clean wheels | Linux aarch64, psycopg 3.3.6, libpq 180006; core-only import isolation and both-wheel operator/runtime-role quickstart passed |
| Builds | Core/adapter wheel and sdist builds succeeded |
| CI configuration | Core Python 3.11/3.12/3.13 lane retained; required PostgreSQL 16/18 owned-container/clean-wheel lanes added; remote Actions not run in this local task |

Database proof uses real psycopg/pool, generated disposable databases, exact-owned
Podman containers/networks/volumes, a loopback TCP fault proxy and synthetic
HTTP inference. No TokenProxy or paid model calls. Required mode rejects skips.
The single warning is Python's intentional multi-threaded fork deprecation in
the inherited-store rejection test; normal workers use spawn.

Covered failure edges: worker death at initial/pending/receipt/transition/decision/
completed checkpoints; pending requests require fresh consent; unknown token
usage remains budget-blocked; acknowledged data survives a database SIGKILL;
lost COMMIT acknowledgement is reconciled from the primary without redispatch;
stale streaming standby is rejected; renewed ownership spans initial expiry;
ordinary pool saturation does not starve renewal; lost ownership remains sticky;
stale approval, asset drift, cross-namespace/revision/foreign-lease mutation,
damaged/nonlogged/unsafe schemas, restricted grants, client deadlines, queued
close and network-blackhole cleanup all fail closed.

Scope limits: no zero-loss asynchronous failover or exactly-once external
effects, no product authentication/authorization, no HTTP scheduler/queue, no
file-to-database importer. The application must supply those policies and filter
private state. See [setup and deployment guidance](../adapters/postgres/README.md).

Independent whole-branch review by a fresh gpt-6-astra reviewer found one
Important/P2 defect and no Critical or Minor findings. Queued submissions could
exceed admission capacity and disappear from lifecycle accounting when callers
timed out before the private loop started them. The regression was watched fail,
then passed after reserving capacity synchronously through actual teardown,
using absolute request-start deadlines and observing submitted task exceptions.
Transport/lease/routing passed 29 tests; complete core and both database lanes
then passed. Expired queued work never reaches SQL and close rejects undrained
work. No second reviewer was substituted for regression/full-suite proof.

A native parallel rerun produced one shortened test-worker timeout; the case
passed in isolation. Worker fixtures now use the production default 10-second
budget, except explicit timeout fault tests. Production deadlines were not
relaxed. A subsequent complete PostgreSQL 16 lane passed all 77 tests.

## Implementation/review decisions

The durable [ruling register](decisions/2026-10-08-run-store-postgres-rulings.md)
assigns stable IDs to all twelve decisions and records each reason and cost if
wrong. The summary below is retained as the original acceptance snapshot.

- Keep the approved dedicated branch checkout; no additional worktree isolation.
- libpq rejects readonly routing before SQL inspection: report unavailable rather
  than incompatible, with less precise operator guidance but no admitted work.
- Core/adapter suites run separately because their module names collide; combined
  collection would require import-mode adjustments.
- One required owned-container CI job per major covers adapter/crash/standby
  gates; this increases lane duration, but avoids shared-container mutations.
- Run safety guards inside bounded operations, not retrying pool check hooks;
  transient failures stop and require reconciliation.
- Database administration is trusted; compromised privileged actors can forge
  state because seals are corruption checks, not authentication.
- Exactly-once effects and lossless asynchronous failover remain application/
  platform responsibilities; otherwise duplication/data loss is possible.
- Both backends enforce byte bounds, but serialization overhead can reject a
  near-limit payload sooner on one backend.
- Legacy file callers can omit revisions for compatibility and therefore do not
  receive mandatory stale-action protection.
- Existing filesystem lock-helper exit semantics after fork are unchanged;
  never fork active executions, since inherited cleanup may affect another lock.
- In-flight fenced transactions may commit after local expiry; late output is
  not admitted, and a timeout still requires authoritative reconciliation.
- Routing proof covers primary/stale standby and per-operation guards, not every
  deployment topology; validate your operator's failover behavior separately.

No deferred Minor findings.
