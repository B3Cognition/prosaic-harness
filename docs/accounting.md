# Accounting context and recovery

Accounting is off by default. Existing Harness callers, checkpoints and invocation receipts keep their existing shape and recovery behavior. No database is required while accounting is off.

Harness0.9.12 requires Runtime `>=0.9.16,<0.10` and Core `>=0.5.0,<0.6`.
Lab0.9.10 qualifies Runtime0.9.17 with unchanged published Harness0.9.12 and
recorder0.3.0/store0.4.1 bytes. Use published distributions, not sibling editables.

## Request metadata with Runtime 0.9.17

Supply trusted `ExecutionContext(request_metadata={'run': 'benchmark-42', 'variant': 'baseline'})`.
Runtime snapshots bounded strings and exposes exactly `context.request_metadata =
{'version': 1, 'labels': {...}}` to prepare before dispatch. Harness uses public
Runtime context decoding/child APIs, so this needs no Harness engine release.
The diagnostic run label is separate from actual run identity; explicit
`ExecutionContext.run_id` must match the stored lowercase UUID hex. Omit it to let
Harness bind its generated ID. Labels/defaults supplied on resume never relabel
original saved context; use a new run for a new variant. Existing explicit
tenant/payer/actor/scope rebind refusal and no-call receipt recovery remain intact.

None/empty labels preserve legacy accounting bytes/hashes. Present labels
intentionally change accounting payload hashes and private sealed contexts/
receipts, without changing artifact/rule, prepared-turn or workflow/bundle identity
fields. Identical replay is idempotent; same-call label changes conflict. Labels
never enter provider prompts/body/headers or select authority, rates, storage scope,
billing eligibility or retry consent. Raw operator views can contain labels;
hosts must filter public output and keep secrets out of arbitrary labels.

Published recorder0.3.0 uses Runtime's decoder/existing JSONB schema, without DDL,
privilege expansion, republish or old-row rewrite. Labeled contexts need >=0.9.17
readers; old unlabeled rows stay readable. See [Runtime bounds/migration](https://github.com/B3Cognition/prosaic-runtime/blob/v0.9.17/docs/accounting.md#request-metadata-v1)
and the [Lab host](https://github.com/B3Cognition/prosaic-integration-lab/blob/v0.9.10/docs/accounting-request-metadata.md).
Complete-train/PG qualification is separate from version-range compatibility;
no live-provider or financial certification is added.

## Existing accounting opt-in

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

Native contextual tools and effect journals use Runtime's separate
`InvocationScope`. Each invocation carries its own persisted attempt ID, run/step
IDs and the sealed host operation namespace. This scope does not enable
accounting, carry billing attribution, or add accounting checkpoint fields.
`WorkflowBindings(operation_namespace=..., tool_journal=...)` captures the trusted
ledger object privately and seals its static opaque identity/contract declaration.

ALWAYS keep business operation persistence and reconciliation in the consuming
application. NEVER treat an accounting record or Harness receipt as an outcome
commit in the tool journal. A Runtime journal uncertainty failure is a terminal
invocation failure receipt; Harness preserves usage and never automatically
reconciles or retries the effect.
