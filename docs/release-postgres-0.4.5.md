# Harness PostgreSQL 0.4.5 — delegation storage

Use this adapter with Harness 0.9.17 to store bounded delegation attempts and receipts. Delegation uses workflow storage marker 5 and conversation marker 6 in the existing tables.

For a new store, initialize with `sub_agents=True`. For an existing store, drain writers and run the owner migration for each store you use.

```sh
prosaic-harness-postgres migrate-sub-agents --store workflows --dsn-env HARNESS_OWNER_DSN
prosaic-harness-postgres migrate-sub-agents --store conversations --dsn-env HARNESS_OWNER_DSN
```

The migration preserves older record bytes. Use a current worker after the marker changes. Worker roles cannot migrate. See [delegation recovery](sub-agents.md).
