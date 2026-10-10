# Harness production verification

H5 adds native Runtime budgets, independent operation scopes and static effect
journal bindings. Checkpoint v2 and receipt v1 remain unchanged. Publication and
final native-platform/database qualification are coordinator gates.

## Dependency evidence

Source checks use immutable archives of Core
`aad4bf45ae1c242f4451700ca59b27280010573a` and reviewed Runtime
`4143457dc7624681e80f59b398e05f9a3f5e9116`. Installed checks use the exact qualified
Core CI wheel (`b3-prosaic==0.4.0`, SHA-256
`120a956fd009ac7db7319a6a2493079441533818320d8adfdcba7b94b47be602`) and Runtime P1
`d7cf94ad1baf55bd63d7c21c11bc24f55c1e6a2e` (`b3-prosaic-runtime==0.8.0`, SHA-256
`c79f2f8960ea1657c5919d4335a0c0b9ce3eb4a70ba92f313f627713bc5a81d1`). P1 changes
metadata without changing the reviewed public interfaces.

The disposable candidate environment contains only the b3 Core/Runtime/Harness
family, including both manifest-selected PostgreSQL adapters. No legacy/new
package coinstallation occurs. `pip check` succeeds. Local checks ran on Python
3.12.14, Darwin 27.2.0, arm64.

## Observed gates

With `PYTHONPATH` selecting immutable dependency archives and Harness source,
and `PATH` selecting the fresh candidate environment:

```sh
.tools/h5-wheel-env/bin/python -m pytest tests/test_runtime_boundaries.py \
  tests/test_workflow_factory.py tests/test_native_execution.py \
  tests/test_native_workers.py tests/test_recovery_contracts.py -q
.tools/h5-wheel-env/bin/python -m pytest -q
.venv/bin/python -m build
.tools/h5-wheel-env/bin/python -I scripts/workflow_factory_smoke.py
```

The exact focused gate passed **157 tests**. The complete suite passed **545
tests**, with no skips. An expanded public API gate against the installed Harness
wheel under `python -I`, without repository pytest configuration, passed **282
tests**. All 19 production modules match source/sdist/wheel bytes.

The isolated public smoke checks installed b3 ownership, discovery,
bundle/reference reconstruction, input preparation and interaction. A contextual
tool receives the sealed namespace; one Harness invocation produces two provider
requests, one tool dispatch and 14 reported tokens. Status, rejected human
responses and fresh-factory resume make no extra requests. Checkpoint v2, receipt
v1 and receipt identity survive. Separate child workers adopt normal and
token-limit failure receipts after a crash before acceptance. Node and the
Prosaic executable are absent from worker/smoke PATH.

The initial `.venv/bin/python -m pytest` source-overlay run passed 541 tests and
failed four: three isolated workers imported legacy installed Runtime, and the
old H1 native fixture asserted no operation scope despite H5's required scope.
The latter now asserts independent scope without observer/accounting options;
ordinary fake adapters retain released keywords. The fresh candidate environment
resolves the stale dependency failures. Its final full result is 545 tests above;
the existing `.venv` was never modified.

## Required PostgreSQL qualification

```sh
.venv/bin/python -m pytest adapters/postgres/tests/test_native_factory.py \
  adapters/postgres/tests/test_engine.py adapters/postgres/tests/test_store.py \
  adapters/postgres/tests/test_recovery.py --require-postgres -q
```

This required lane was attempted and failed with **26 setup errors** because no
explicitly owned `HARNESS_TEST_DATABASE_URL` is configured. These are unavailable
fixture errors, not qualifying skips or successful PostgreSQL evidence. The
coordinator reports a 15-second Docker-info timeout; no shared Docker restart,
global cleanup or shared service database connection was attempted.

Native SQL coverage includes fresh bundle reconstruction, budget failure receipt
adoption, usage/validator versions and interaction revisions. Invalid or stale
human decisions assert unchanged SQL state and revision. Actual owned PostgreSQL
16 and 18, Linux qualification, minimum dependency bounds and final committed
five-wheel closure remain coordinator gates.

ALWAYS record unavailable native lanes separately from passing source and wheel
checks. NEVER treat missing fixture skips or portable store tests as PostgreSQL
qualification.
