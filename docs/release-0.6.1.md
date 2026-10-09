# Harness 0.6.1 release verification

Ships PostgreSQL store 0.1.1 with atomic transfer from acquiring to registered
lease capacity. One execution no longer consumes two capacity slots during
registration. Database schema and serialized workflow formats remain unchanged.
Pins immutable Runtime 0.7.0 commit `109df2c350b9b0baa2c4074bb23aa7e8222c9395`.

Local macOS ARM core suite: 172 passed against the installed Runtime 0.7 wheel.
Owned PostgreSQL 16/18 adapter suites: 82/82 each, zero skips and verified cleanup,
including crash/standby and separate clean-wheel installs. Core and adapter builds
passed. Packaging gates run against the declared immutable dependency pin.

The registration regression initially failed because its lab-only runtime DSN
was absent in the upstream suite. It now uses the native disposable database
fixture with explicit initialization; production replicas still never migrate.
Release wheel names and metadata gates were updated to 0.6.1/0.1.1. Native CI
and remote asset verification are recorded in the integration lab release ledger.
No paid inference, provider retries or new billing authority is introduced.

Parallel qualification exposed exhausted Docker default address pools and an
inventory list/inspect race during concurrent owned teardown. Explicit free
subnet selection and bounded rereads for confirmed disappearing IDs are covered
by watched negative tests; stable engine failures remain fatal. The pool probe
created only three default networks before exhaustion and verified exact-owned
cleanup. The first probe's short/full-ID cleanup check was corrected; its exact
owned inventory was then empty. Existing networks were never removed.

Final PostgreSQL 16 owner: `e78ec66d4e9b49f19ec17f51b24423bf`.
Final PostgreSQL 18 owner: `b5d6eb21322f447980c0480ed9ede995`.
