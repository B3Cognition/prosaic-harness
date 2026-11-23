# Harness PostgreSQL 0.4.6 — pooled connection check

The store's connection pools now check a connection before handing it out. The check is one empty statement, bounded
by 1 second or half of `pool_timeout_s`, whichever is less. A connection that does not answer is closed and the pool
connects again.

Before this release, a pooled connection whose network path had died silently (a NAT, firewall or load balancer that
forgot it, sending no reset) was handed to the next operation. That operation hung until its deadline and failed with
`StoreUnavailable: database operation interrupted`. An interrupted receipt or session write can also leave a
conversation unable to continue. TCP keepalives on the connection string do not always prevent such drops.

A healthy connection costs one extra round trip per operation. The storage contract, schema and markers are
unchanged: no migration, and 0.4.5 and 0.4.6 workers can share a store.
