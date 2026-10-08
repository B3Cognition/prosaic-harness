# Accounting context and recovery

Accounting is off by default. Existing Harness callers, checkpoints and invocation receipts keep their existing shape and recovery behavior. No database is required while accounting is off.

Harness 0.6.0 pins the immutable Runtime 0.6.0 release commit `b13a62eac955b19b13fe2c9dc646a188069f72f2`, which provides `accounting_v1`. Normal installation resolves this dependency without a sibling checkout.

To opt in, supply trusted host context and an explicitly configured Runtime recorder:

```python
from prosaic_runtime import ExecutionContext
from prosaic_harness import Harness

harness = Harness(workflow, run_dir, accounting=recorder,
                  context=ExecutionContext(application_id='studio', tenant_id='tenant-42',
                                           billing_account_id='account-42', actor_id='user-7'))
state = harness.run(request)
```

A Runtime configured with `accounting` or `context_defaults` also opts in. The adapter must advertise `accounting_v1`. Recorder persistence failures retain Runtime's failure behavior; Harness never treats an accounting observation as authority to retry or accept an invocation.

ALWAYS derive IDs from trusted host evidence and authorize access to a run in the consuming application. NEVER treat a supplied ID, a run-store namespace or a checkpoint checksum as authorization.

The checkpoint stores `accounting_context` as an optional schema-2 extension. Omitted attribution uses recorder defaults, Runtime defaults or the reserved `default` identity. The resolved snapshot is frozen before the first invocation. When a recorder is configured, `accounting_scope` also freezes its deployment namespace and environment. Changing scope is rejected; future measured dispatch requires the original scope recorder configuration. Each child carries the same attribution and request correlation, with Harness run ID, step ID and a distinct invocation attempt ID. This context is passed separately from model arguments.

On resume, the original snapshot survives changed deployment defaults. Explicitly conflicting application, tenant, billing account, actor, project, run or request IDs are rejected. Resuming an old checkpoint with accounting enabled records the default snapshot and `accounting_migration` provenance under the run-store lease. Completed runs and interrupted requests do not cause an additional provider call. An interrupted request still requires an explicit retry decision.

ALWAYS keep unknown historical measurements unknown. NEVER infer per-provider-call quantities from old invocation totals. Migration preserves old receipts without importing them into the accounting ledger. New receipt accounting context, when present in Runtime's `metadata.accounting_v1`, must match the checkpoint and invocation lineage.

CLI `run` and `resume` accept optional `--application-id`, `--tenant-id`, `--billing-account-id`, `--actor-id`, `--project-id` and `--request-id`. These flags preserve context without configuring durable accounting. Configure a recorder through the SDK; the CLI does not load arbitrary recorder plugins.

Durable recorder installation, deployment namespace/environment provisioning, database ownership, rate cards and reconciliation belong to the recorder and host. Harness checkpoint and accounting persistence are separate recovery boundaries. This integration provides metering lineage; it does not implement customer charging, exporter delivery, verified account mappings or historical receipt import.
