# Harness 0.9.9 — guarded conversations

Preserves host-required guards and composed inspection rules throughout
conversation admission, readmission, execution and interpretation. Hosts supply
registered guards and explicit sealed project roots. Guard declarations become
part of the binding identity; callables remain in memory. Rule violations and
bounded rule outcome metadata survive durable receipts and replay.

The release requires Core 0.5.0 and Runtime 0.9.14, which publishes rule admission.
Harness PostgreSQL store 0.4.1 remains an unchanged compatibility witness, not a
new adapter publication. Existing unguarded identities and receipts retain their
compatibility behavior.

Publish only the exact artifacts qualified by the release workflow, with matching
Core and Runtime lineage, source and installed tests, all platform/Python and
PostgreSQL cells and dependency floors. Verify the actual public bytes and fresh
installed guarded conversations before adopting this release in Lab.
