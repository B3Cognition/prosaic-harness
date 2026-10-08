# Two-worker PostgreSQL example

First complete [installation, explicit init, grants and doctor](../../adapters/postgres/README.md).
Use the current checkout's unreleased core 0.6.0 / adapter 0.1.0. From repository
root with `.venv-postgres/bin` on PATH and a secret-managed `HARNESS_RUNTIME_DSN`,
worker A starts a new run and reports state/revision:

```sh
export EXAMPLE_RUN_ID="$(python -c 'import uuid; print(uuid.uuid4().hex)')"
printf '%s\n' '{"task":"synthetic request"}' | python examples/postgres/run_workflow.py start \
  --dsn-env HARNESS_RUNTIME_DSN --namespace my-app --run-id "$EXAMPLE_RUN_ID"
python examples/postgres/run_workflow.py status \
  --dsn-env HARNESS_RUNTIME_DSN --namespace my-app --run-id "$EXAMPLE_RUN_ID"
```

The default pause.yml performs **zero model calls**; no AI endpoint/key is needed.
Worker B uses the same run ID/namespace and unchanged assets at identical absolute
paths. Copy the current status revision to `EXAMPLE_REVISION`, then submit:

```sh
python examples/postgres/run_workflow.py resume --choice approve \
  --expected-revision "$EXAMPLE_REVISION" --dsn-env HARNESS_RUNTIME_DSN \
  --namespace my-app --run-id "$EXAMPLE_RUN_ID"
```

It completes; reject leads to rejection. An old/missing revision is rejected
without advancement; never replace it automatically. Start reads a JSON object
from stdin. Commands return operator JSON `{"state":...,"revision":...}`; this
private state must be filtered by authenticated applications. The runner is not
an HTTP server or another workflow interpreter.

For real Runtime inference against a **synthetic loopback** model server, set
runtime.yml's URL to that fixture and pass `--workflow examples/postgres/synthetic.yml`
to every command. It invokes paired ALWAYS/NEVER prose, validates the result
schema and pauses. Changing assets/URL after starting invalidates resume. Tests
provide the synthetic server and assert actual HTTP counts; no external keys.

An interrupted call without a receipt stays blocked. After reviewing possible
external effects, `resume --retry-interrupted --expected-revision ...` supplies
explicit consent; the abandoned call still consumes budget. A committed receipt
is adopted without another call. Follow the adapter recovery guidance for
store_unavailable, lease_lost and revision_conflict.
