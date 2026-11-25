# Harness 0.9.22

Context-pack records and conversation bindings now decode the canonical bytes
they validated when they were created. Reads return fresh copies for callers.
Binding readmission still checks the current declarations before effects.

In a scripted tool-calling conversation with context packs and a file store,
the first turn went from 3.05 s to 1.98 s. In the same PR's readmission profile,
one binding readmission went from 15.7 ms to 10.8 ms. These are workload-specific
measurements. [Performance PR](https://github.com/B3Cognition/prosaic-harness/pull/41)

## Upgrade and resume

Upgrade `b3-prosaic-harness` to 0.9.22. Existing sessions can resume with their
current bindings and stores. Ordinary use supports Prosaic Core >=0.5.0,<0.6
and Runtime >=0.9.25,<0.10. Release qualification uses Core 0.5.0 and Runtime
0.9.27, with Core 0.5.1 for optional catalogue ontology. The PostgreSQL 0.4.6
build is a qualification witness for the separately published adapter.

The [release assets](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.22)
include the release receipt, checksums, and hosted qualification records.
