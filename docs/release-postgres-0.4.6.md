# Harness PostgreSQL 0.4.6 — pooled connection check

The adapter checks connections from both the ordinary and lease-renewal pools
before starting a database operation. The check is one empty statement, bounded
by the smallest of one second, half of `pool_timeout_s`, and the remaining checkout
budget. A failed check closes the connection and drains the probe before the
adapter requests a replacement within that same budget. Cancellation performs
the same cleanup and ends checkout before any operation is dispatched.

Before this release, a pooled connection whose network path had died silently (a NAT, firewall or load balancer that
forgot it, sending no reset) was handed to the next operation. That operation hung until its deadline and failed with
`StoreUnavailable: database operation interrupted`. An interrupted receipt or session write can also leave a
conversation unable to continue. TCP keepalives on the connection string do not always prevent such drops.

A healthy connection costs one extra round trip per operation. The storage contract, schema and markers are
unchanged: no migration, and 0.4.5 and 0.4.6 workers can share a store.
