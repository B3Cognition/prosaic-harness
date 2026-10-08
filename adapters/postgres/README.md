# Prosaic Harness PostgreSQL adapter

Separately installed persistence for the synchronous Harness SDK. The caller
provides and initializes an existing PostgreSQL database; core has no PostgreSQL
dependency. Run state is scoped by a trusted application namespace. Applications
retain authentication, authorization, scheduling and external-effect idempotency.

The adapter requires Python 3.11+, PostgreSQL 16+ and libpq 17+ (provided by current
psycopg binary wheels). Its private I/O loop provides bounded connection/query
waits; applications do not need asyncio. No pool or transaction is held during
model execution. Setup and examples are documented in the repository design
and will be exercised by the required integration lane.
