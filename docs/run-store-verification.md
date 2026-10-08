# RunStore/PostgreSQL implementation evidence

Local acceptance on 2026-10-08, branch `codex/harness-run-store-design`.
Core 0.6.0 and separate adapter 0.1.0 are development builds, not releases.
No consumer migration, remote push, package publication or database provisioning.

| Gate | Observed result |
| --- | --- |
| Core/full legacy suite | 153 passed, 36.04s, no PostgreSQL dependency |
| Real PostgreSQL 16 adapter lane | 76 passed, 81.35s, no skipped cases |
| Real PostgreSQL 18 adapter lane | 76 passed, 81.61s, no skipped cases |
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

Independent whole-branch review follows these local acceptance checks; its
findings and any regression fixes will be recorded before final handoff.
