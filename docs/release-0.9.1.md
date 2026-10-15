# Harness 0.9.1 candidate

Requires Runtime >=0.9.5 and integrates its cooperative lifecycle through workflow
and conversation persistence/lease cleanup. See [execution-lifecycle](execution-lifecycle.md).
Hosts retain process signaling, readiness, product queues and publication policy.

No automatic interrupted-call retry or accounting reconciliation is introduced.
Existing schema admission and explicit acknowledgement requirements remain intact.
PostgreSQL adapter stays 0.4.0; upgrading from 0.3 requires its explicit storage
contract migration with drained old writers, as documented for Harness 0.9.0.

Local qualification: 835 passed; two dedicated disposable-PostgreSQL lifecycle
lanes skipped because their explicit database was not configured. Cerebro separately
passed its owned PostgreSQL integration and signal/replay suite. Wheels/sdists,
archive packaging, clean installed workflow and conversation/context smoke tests
passed. Release remains pending normal review and explicit publication after
Runtime 0.9.5.

## Known no-effect failure retry

`Conversation.retry_failed(..., expected_revision=revision,
acknowledge_effect_risk=True)` appends a bounded attempt to the latest original
failed message. It requires exact adopted receipts for every prior attempt,
complete usage, zero tool calls and no uncertain effects. Frozen input/context,
accounting lineage and cumulative session quotas remain unchanged. Status,
recover and duplicate send do not automatically retry a failed request. Hosts
still enforce the original request deadline and aggregate token allowance.
Completed turns, workflow commands, stale revisions and unknown usage cannot use
this transition. PostgreSQL and FileSessionStore enforce the same monotonic
transition contract; no record migration is required for this API.
