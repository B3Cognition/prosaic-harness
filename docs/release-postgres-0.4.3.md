# Harness PostgreSQL 0.4.3

Requires Harness >=0.9.14,<0.10. Add explicit tool-contract workflow marker 3 and
conversation marker 4 on the existing JSON storage layout. Fresh namespaces use
`initialize(tool_contracts=True)`; existing namespaces require owner-only
`migrate_tool_contract_storage()` after draining writers. No record rewriting,
worker startup DDL or automatic migration. Lease generation, ownership, capacity
and immutable-receipt fencing remain enforced. Older readers refuse the marker.

Runtime recorder 0.3.0 remains independently versioned with unchanged public bytes.
See [Harness notes](release-0.9.14.md) and [the contract](tool-events-citations.md).
