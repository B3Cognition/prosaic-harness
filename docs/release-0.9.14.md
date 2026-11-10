# Harness 0.9.14 — durable tool evidence and citations

Requires Runtime >=0.9.20,<0.10 and Core >=0.5.0,<0.6. This release adapts the
Runtime tool contract to workflows, conversations and selected context packs.

- Bind explicit host `ToolContracts` to ordinary nodes/agents; typed outputs,
  safe scalar progress and citation permission remain separate concerns.
- Seal captured origins, delivery evidence, accepted citations and answer hashes
  into the same owned receipt. Recover saved receipts before considering new work.
- Recheck current permissions when viewing sources, reading tool history or
  submitting retained history. Omitted context requires no unused grant.
- Explicit typed retained references mint fresh turn-scoped evidence IDs; text IDs
  and progress events grant no authority. No source URL is fetched by a view.
- Preserve complete private guard facts independently from selected model context.

Opted-in workflows use state v4 / receipt v3; conversations use session/receipt v4.
Old paths and record families remain unchanged without opt-in. Initialize or migrate
storage explicitly as its owner; workers never perform DDL. The PostgreSQL adapter
0.4.3 supports these markers using existing JSON tables. Drain old writers before
migration; old readers refuse enabled markers instead of guessing.

See [the contract](tool-events-citations.md) and [store notes](release-postgres-0.4.3.md).
Promotion reuses a successful exact-source qualified archive and revalidates every
required record, without rebuilding or repeating its platform/database matrix.
Parallel tools, MCP and sub-agent orchestration remain follow-ups.
