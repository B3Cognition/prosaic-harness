# Drain workflows through persistence

Harness 0.9.2 requires Runtime >=0.9.5. `Harness.lifecycle` shares the concrete
Runtime/RuntimeAdapter lifecycle by default. `run()` and `resume()` remain active
until final checkpoints, observations, receipt persistence, lease release and
workspace cleanup complete. A drain does not cancel steps in an admitted workflow
or release its ownership early. It prevents new root runs/resumptions.

```python
from prosaic_runtime import ExecutionLifecycle, ProsaicRuntime
from prosaic_harness import Harness

lifecycle = ExecutionLifecycle()
runtime = ProsaicRuntime(config, lifecycle=lifecycle)
harness = Harness(workflow, store=store, run_id=run_id, runtime=runtime)
# Host runs harness.run(inputs) in a worker thread.
lifecycle.begin()  # Host also withdraws readiness and queue admission.
lifecycle.wait()   # Supervisor thread, after fencing, before store.close().
store.close()
```

A host may pass `lifecycle=...` when Harness constructs the Runtime. If an existing
Runtime is supplied, a differing lifecycle is rejected. Trusted fake/custom
Runtimes without lifecycle support receive a Harness-owned scope tracking the
complete synchronous Harness operation. Extend the same scope around product
queue/publication writes using `with lifecycle.work():`.

`Conversation(..., lifecycle=shared)` similarly tracks create/send/recovery,
explicit retry and workflow commands through session persistence/lease cleanup.
Ordinary/interpretation Runtimes share its lifecycle. Linked workflow execution
is additionally covered by its enclosing conversation command. Read-only status
remains available after draining begins. No signal handlers or web framework
are installed by the package.

See Runtime's execution-lifecycle documentation for timeout/threading semantics.
Pending calls remain pending after abrupt interruption. Existing explicit
acknowledgement requirements for retrying interrupted effects are unchanged;
shutdown/draining never reconciles unknown token usage or clears a product hold.

Upgrading from Harness 0.8 and PostgreSQL adapter 0.3 also requires the existing
explicit conversation storage-contract migration. Stop/drain old writers, retain
backups, and use the owner-only `PostgresSessionStore.migrate_context_storage()`
API from adapter 0.4. Runtime credentials and readiness must never migrate storage.
This advances the storage marker from 1 to 2 without rewriting conversation rows.
