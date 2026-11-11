# Harness PostgreSQL 0.4.4

Requires Harness >=0.9.15,<0.10. Parallel workflows use storage marker 4.
Parallel conversations use marker 5. These markers use the existing JSON tables.

Initialize new stores with `parallel_tools=True`. For existing stores, drain
writers and run `migrate_parallel_tool_storage()` as the owner. The migration
keeps existing record bytes. Worker roles cannot migrate, and older writers
refuse the new storage markers.

See [Harness release notes](release-0.9.15.md) and the
[configuration and compatibility guide](parallel-tools.md).
