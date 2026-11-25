# Harness 0.9.21

Longer conversations now reuse successful verification of identical session
snapshots. Harness fully validates each new snapshot before caching its canonical
bytes and returns an owned copy to each caller. The cache holds up to 64 MiB of
session content per process. Workers forked from a parent process start with an
empty cache and a fresh lock.

In a local four-turn, file-backed conversation with context packs and a synthetic
provider, caching reduced the median fourth turn from 6.27 s to 2.05 s across
three runs per setting. Verification still scales with retained session content.
Harness checks the lease and bindings on each cancellation poll and readmits
the bindings before saving the receipt.

## Upgrade and resume

Upgrade `b3-prosaic-harness` to 0.9.21 and reopen existing sessions with their
current bindings and stores. The change requires no migration or fresh approval.
Ordinary use supports Prosaic Core >=0.5.0,<0.6 and Runtime >=0.9.25,<0.10.
Release qualification uses Core 0.5.0 and Runtime 0.9.27, with Core 0.5.1
for optional catalogue ontology. The PostgreSQL qualification uses adapter
0.4.6. Its build in this release's evidence is a qualification witness. Install
the published [PostgreSQL adapter 0.4.6](release-postgres-0.4.6.md) for deployments.

The [performance PR](https://github.com/B3Cognition/prosaic-harness/pull/40)
records the benchmark and local regression, database and Integration Lab checks.
The [release assets](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.21)
include the exact-build receipt, checksums and hosted qualification records.
