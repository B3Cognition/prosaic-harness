# Harness 0.9.15 — parallel read tools

Requires Runtime >=0.9.21,<0.10 and Core >=0.5.0,<0.6. Configure an explicit
host ceiling and select parallelism per workflow agent node or conversation.
Only host-registered concurrent-safe read tools run in bounded windows.

Existing configurations remain sequential. Harness preserves ordered evidence,
current permissions, and durable receipt adoption through the existing lease and
claim fencing. Parallel workflows use state v5 and receipt v4. Parallel
conversations use state and receipt v5.

See [configuration and compatibility](parallel-tools.md) and
[PostgreSQL migration](release-postgres-0.4.4.md).
