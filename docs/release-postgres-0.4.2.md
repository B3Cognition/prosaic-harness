# Harness PostgreSQL 0.4.2 — context-pack persistence and fenced renewal

This independently versioned adapter requires Harness >=0.9.13,<0.10 and its
compatible Runtime >=0.9.19,<0.10. Core remains database-free and PostgreSQL drivers
remain optional for ordinary Harness users. See the
[release page](https://github.com/B3Cognition/prosaic-harness/releases/tag/postgres-v0.4.2)
for publication status, original wheels/source, hashes and qualification.

## Behavior

Context-pack workflow and conversation records retain bounded captured evidence,
private validation bindings, selected inputs and receipt proof. Restart and saved
receipt adoption recheck current permission and preserve provider-work accounting.
Namespaces, tenant/actor scope, ownership and generations remain fenced.

Renewal now waits for a valid same-owner record transaction within the existing
statement and total I/O deadlines. The ordinary short lock timeout still bounds
normal contention. Failed renewal is sticky, expired/displaced owners cannot
resume writes, and unknown COMMIT outcomes are never silently retried.

## Owner migration and rollback

Drain writers, back up the owned namespace, then use the schema owner to apply
the explicit [context-pack migration](https://github.com/B3Cognition/prosaic-harness/blob/postgres-v0.4.2/docs/context-packs.md#current-authorization-and-durable-storage).
Readiness performs no DDL. Existing workflow/session data is retained; old readers
and writers must not be used for newly admitted context-pack records. To roll
back admission, keep compatible readers to reconcile existing operations instead
of downgrading markers or rewriting saved records.

The default PostgreSQL durability checks and explicit Aurora profile remain in
force. Native PostgreSQL tests are not evidence of Aurora failover behavior.

## Verification

Real database regressions exercise renewal competing with same-owner writes in
both run and session stores, plus expiry, changed generations, network loss and
lost COMMIT acknowledgment. The complete adapter suites and installed legacy
lifecycle gates run on Linux x86/ARM with PostgreSQL 16 and 18. Public index bytes
must match the same qualified SDK bundle used for Harness 0.9.13.
