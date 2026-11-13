# Releases and compatibility

Harness 0.9.18 adds opt-in [catalogue ontology](release-0.9.18.md) with Core
0.5.1 and Runtime 0.9.23. Ordinary Harness use retains Core 0.5.0 support.
Existing PostgreSQL adapters require no migration for this feature.

Harness 0.9.17 and PostgreSQL store 0.4.5 add [bounded sub-agents](release-0.9.17.md) with Runtime 0.9.23. See [owner migration](release-postgres-0.4.5.md).

Harness 0.9.16 adds [MCP read-tool bindings](release-0.9.16.md) with Runtime 0.9.22.

Harness 0.9.15 / store 0.4.4 add [opt-in parallel reads](release-0.9.15.md) with Runtime 0.9.21. See [owner migration](release-postgres-0.4.4.md).

Harness 0.9.14 / store 0.4.3 add [safe tool events and durable citations](release-0.9.14.md)
with Runtime >=0.9.20,<0.10. The tools train retains Core 0.5.0 and recorder 0.3.0.
Versioned release pages and original archives remain publication authority.

Context-pack release train prepared on 2026-11-09; release pages remain the
publication authority. Harness 0.9.13 targets Runtime >=0.9.19,<0.10 and Core
>=0.5.0,<0.6. Lab 0.9.12 pins the complete public train. Earlier Lab manifests
and published artifacts remain immutable; a newer SDK does not certify a partial
historical mixture.

| Component | Context-pack train | Scope |
| --- | --- | --- |
| Core (`b3-prosaic`) | 0.5.0 | Unchanged canonical Markdown and inert rule tags |
| Runtime (`b3-prosaic-runtime`) | 0.9.19 | Profiled inputs, private facts, bounded variants and frozen v3 turns |
| Harness (`b3-prosaic-harness`) | 0.9.13 | Named context packs, agent defaults and node overrides |
| Runtime PostgreSQL recorder | 0.3.0 | Original published bytes and schema |
| Harness PostgreSQL store | 0.4.2 | Explicit context-pack migration and safe bounded renewal |
| Integration Lab | 0.9.12 | Complete public train and context-pack adoption |

See [Harness release notes](release-0.9.13.md), [adapter migration notes](release-postgres-0.4.2.md),
and the [Lab guide](https://github.com/B3Cognition/prosaic-integration-lab/blob/v0.9.12/docs/context-packs.md).
Lab 0.9.11 retains Runtime 0.9.18 / Harness 0.9.12 and its sent-effort blueprint.

Install current SDKs in a fresh environment; pin versions and archive hashes for reproducible deployments. Optional PostgreSQL adapters require explicit provisioning and operator readiness checks. Never co-install legacy and renamed distributions that own the same imports.

Runtime 0.9.15 advances `value_in_tool_output` to `value-in-tool-output-v2`; explicitly readmit affected bindings when upgrading from 0.9.14. Runtime 0.9.16 headers add no identity fields and leave guard versions unchanged. Harness 0.9.11 adds a source-archive blueprint using versioned validators; Harness0.9.12 adds guarded workflow identity and bounded proof while preserving untagged seals; see [identity/readmission](workflow-rules.md).

## Independently versioned store

[PostgreSQL store 0.4.2](release-postgres-0.4.2.md) adds explicit context-pack
storage migration and prevents false renewal loss behind same-owner record
writes. PostgreSQL 0.4.1 remains available for its historical compatible trains.
The explicit Aurora durability profile still requires deployment-specific
persistence and failover evidence.

## Published history

Every published version is linked below. Backfilled notes explain changes using that version’s source, without attributing newer features or modern validation results to it. Candidate tags without a published release are not listed as releases.

| Release | Published (UTC) | Notes |
| --- | --- | --- |
| [v0.9.13](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.13) | See release page | [Context-pack notes](release-0.9.13.md) |
| [postgres-v0.4.2](https://github.com/B3Cognition/prosaic-harness/releases/tag/postgres-v0.4.2) | See release page | [Migration notes](release-postgres-0.4.2.md) |
| [v0.9.12](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.12) | 2026-11-07 | Published notes |
| [v0.9.11](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.11) | 2026-11-07 | Published notes |
| [v0.9.10](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.10) | 2026-11-06 | Published notes |
| [v0.9.9](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.9) | 2026-11-06 | [backfilled notes](release-history/v0.9.9.md) |
| [v0.9.8](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.8) | 2026-11-05 | Published notes |
| [v0.9.7](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.7) | 2026-11-03 | Published notes |
| [v0.9.6](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.6) | 2026-11-02 | Published notes |
| [v0.9.5](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.5) | 2026-10-29 | [backfilled notes](release-history/v0.9.5.md) |
| [postgres-v0.4.1](https://github.com/B3Cognition/prosaic-harness/releases/tag/postgres-v0.4.1) | 2026-10-20 | Published notes |
| [v0.9.4](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.4) | 2026-10-17 | Published notes |
| [v0.9.2](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.2) | 2026-10-15 | [backfilled notes](release-history/v0.9.2.md) |
| [v0.9.0](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.0) | 2026-10-14 | [backfilled notes](release-history/v0.9.0.md) |
| [v0.8.2](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.8.2) | 2026-10-13 | [backfilled notes](release-history/v0.8.2.md) |
| [v0.8.1](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.8.1) | 2026-10-13 | [backfilled notes](release-history/v0.8.1.md) |
| [v0.8.0](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.8.0) | 2026-10-13 | [backfilled notes](release-history/v0.8.0.md) |
| [v0.7.1](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.7.1) | 2026-10-11 | [backfilled notes](release-history/v0.7.1.md) |
| [v0.6.2](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.6.2) | 2026-10-10 | Published notes |
| [v0.6.1](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.6.1) | 2026-10-09 | Published notes |
| [v0.6.0](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.6.0) | 2026-10-08 | Published notes |
| [v0.5.0](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.5.0) | 2026-10-07 | Published notes |
| [v0.4.2](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.4.2) | 2026-10-07 | Published notes |
| [v0.4.1](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.4.1) | 2026-10-01 | Published notes |
| [v0.4.0](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.4.0) | 2026-10-01 | Published notes |
| [v0.3.0](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.3.0) | 2026-10-01 | Published notes |
| [v0.2.0](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.2.0) | 2026-09-30 | Published notes |

## Release-note checklist

For each future publication, write version-specific notes before release: describe changed behavior, dependency floors and the exact qualified train, identity/fingerprint changes and readmission or migration steps, adapter publication versus witness status, and observed validation with its limits. Link the original qualification and public-consumer proof. Never substitute a generic “qualified release” sentence or rewrite historical package bytes to improve documentation.
