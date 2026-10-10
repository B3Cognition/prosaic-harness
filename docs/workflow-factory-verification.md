# Validated workflow factory: implementation verification

Initial local checkpoint: 2026-10-10. Candidate versions: Prosaic 0.3.2, Runtime 0.7.1,
Harness 0.6.2. Implementation is local on `codex/validated-workflow-factory`
in all three repositories; no push, merge, release or live provider call had occurred
at this checkpoint. Subsequent platform qualification and publication are recorded
in [the 0.6.2 release notes](release-0.6.2.md) and its verification asset.

The [normative design](superpowers/specs/2026-10-09-workflow-mvp-design.md)
and [API guide](workflow-factory.md) describe the supported boundary. Host policy,
catalogue content and private bindings admit logical workflow proposals. Native
workflows need no client directory and cannot grant filesystem or CLI access.
Approved composition and new inline instructions have independent permissions.

## Verification evidence

| Gate | Result |
| --- | --- |
| Prosaic full suite | 466 passed |
| Immutable v0.2.0 TypeScript reference/original CLI oracle | Passed; 13 suites / 55 original tests |
| Runtime full suite | 495 passed, 1 opt-in test skipped |
| Harness full suite, Python 3.12.14 / current schema dependencies | 337 passed in 43.79 seconds |
| Harness Python 3.11.15 / jsonschema 4.23.0 / referencing 0.28.4 | 333 full-suite tests passed; final 4 composition tests also passed |
| PostgreSQL 16.15 real native/store/controller/recovery checks | 24 passed, zero skips |
| PostgreSQL 18.6 same checks | 24 passed, zero skips |
| Core, Runtime, Harness wheel and source builds | Passed |
| PostgreSQL adapter compatible wheel/source build and metadata checks | Passed |
| Clean installed Core wheel smoke | Passed with Node hidden |
| Clean installed native workflow smoke, Python 3.12 and 3.11 minimum dependencies | Passed with Node and Prosaic executable hidden |
| Clean environment dependency checks | No broken requirements |
| Diff whitespace checks | Passed |

The installed native example used one successful host tool callback and two
synthetic loopback provider requests, then validated a human selection and
resumed from a freshly reconstructed factory without another invocation.
The separate two-process test rebuilt the same fingerprint with independent
host bindings, preserved receipt bytes and enforced response/revision checks.
Checkpoint version 2 and receipt version 1 remain unchanged.

The [database evidence](workflow-factory-database-verification.md) records
official checksums, exact fixture ownership and commands. Both servers were
stopped, checked absent and removed along with their downloads and binaries.
Only small server logs remain. Existing Docker-based standby/full crash-matrix
and Linux CI lanes remain configured; those platform gates were not rerun here.

## Reviewed failure boundaries

Independent reviews and regression fixes cover canonical typed artifacts,
effective provider/routing validation, default model-tier permission, owned
registries/configuration, original admission seals and actual adapter identity.
Schema checks cover scoped static references, duplicate IDs/anchors, cycles,
boolean schema positions, per-root work bounds and aggregate schema-body bytes.

Execution checks cover input rejection before state creation, preparation before
pending dispatch, private directory cleanup, required tool versions, binding
freshness, separate inline/composition permission and bounded calls/visits.
Malformed or oversized returned results become valid failure receipts before
commit; usage and invocation completion survive normal/failure receipt adoption.
Terminal run documents reserve both encoded bytes and expanded nodes. Live
validator changes, unsafe workflow mutation and stale human revisions fail closed.

Historical YAML defaults/fingerprints, deeper and productive recursive schemas,
CLI/sandbox preparation, acquisitions and opaque trusted legacy test adapters
retain their compatibility behavior. A raw pathless Workflow cannot execute.

## Candidate dependency chain and release boundary

Runtime pins Core commit `737bc0f4e6b5d3bd7bd370f2c0d408bc89eb494f`.
Harness pins Runtime commit `833ace8dc01c125e653e451287d2fcc316b33627`.
Clean candidate environments installed the matching local wheels with declared
third-party dependencies, rather than fetching unpublished VCS commits.

Publishing requires making the dependency commits reachable in Core → Runtime
→ Harness order and completing the normal CI/release process. These local
candidate checks do not claim a published release or replace required platform
CI. Trusted callbacks/schema CPU remain cooperative, reported token budgets can
overshoot within one invocation, and remote completion before receipt commit
remains ambiguous with explicit retry consent.

The initial disk blocker was cleared by removing 158 identified inactive
Echelon fixture directories from `/private/tmp`, recovering approximately 99 GiB.
Unrelated temporary content and the existing Core research note were preserved.
