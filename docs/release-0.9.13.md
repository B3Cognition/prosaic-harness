# Harness 0.9.13 — reusable context packs

Each agent can have a named context default, and each workflow node can select
its own pack. Packs select declared Markdown, request fields and accepted tool
or node outputs. Database-backed services supply accepted records through their
existing tools; Harness binds those records without owning application queries.
See [context packs](https://github.com/B3Cognition/prosaic-harness/blob/v0.9.13/docs/context-packs.md) and the
[runnable Markdown example](https://github.com/B3Cognition/prosaic-harness/blob/v0.9.13/docs/../examples/context-packs/workflow.yml).

## Changes

- Reusable versioned packs, agent defaults and node overrides with bounded
  captured items, deterministic variants, provenance and citation identities.
- Invocation-scoped deferred reads with current-use authorization and bounded
  complete/partial outcomes. Revocation is rechecked on retained reads and reuse.
- Selected model context is separate from complete frozen validation facts.
  Private guard input is explicit, and safe feedback does not expose diagnostics.
- Durable workflow/conversation snapshots, receipt adoption and frozen Runtime
  restoration preserve bindings across restart without inventing provider work.
- File and optional PostgreSQL storage have explicit context-pack migrations.

## Compatibility and migration

Requires Core >=0.5.0,<0.6 and Runtime >=0.9.19,<0.10. Optional PostgreSQL 0.4.2
requires Harness >=0.9.13,<0.10. The Runtime recorder remains the original 0.3.0.
Lab 0.9.12 pins the complete public train.

Packs are opt-in. Pack-free callers retain their existing payloads and identities;
legacy records remain readable. Opt-in workflows use checkpoint v3, invocation
receipt v2 and guard proof v2; opt-in conversations use session/receipt wrappers v3.
Private facts do not become model context merely because a guard needs them.

Before storage migration, drain writers and back up the owned namespace. Apply
the documented migration using the schema owner; runtime roles perform no DDL.
Rollback disables new pack admission while keeping compatible readers available
to settle saved v3 work. Do not downgrade markers or reintroduce old writers.
See [migration and rollback](https://github.com/B3Cognition/prosaic-harness/blob/v0.9.13/docs/context-packs.md#current-authorization-and-durable-storage)
and [PostgreSQL 0.4.2 notes](https://github.com/B3Cognition/prosaic-harness/blob/v0.9.13/docs/release-postgres-0.4.2.md).

## Qualification

The [release page](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.13)
is the authority for published original bytes and attached exact-source records.
Required gates cover Linux x86/ARM, macOS Intel/ARM, Python 3.11–3.13, dependency
floors, installed wheels, PostgreSQL 16/18, legacy lifecycle and restricted roles.
Lab qualifies all 12 context-pack cases on x86/ARM × PostgreSQL16/18 with zero
skips and verified fixture cleanup. Synthetic checks do not establish live-model
quality or savings.
