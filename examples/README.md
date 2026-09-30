# Reusable workflow blueprints

Start with the installation and endpoint setup in the [root README](../README.md).
Run commands below from the repository root. `.venv/bin` must be on PATH so the
controller can inspect Markdown with the installed Prosaic CLI.

## Single validated agent

```sh
.venv/bin/prosaic-harness run examples/single.yml \
  --input examples/request.json --run-dir runs/single
```

The `fast` briefer returns a schema-validated summary and source-bound facts.
It has no tools. Use `tokenproxy-single.yml` with `TOKENPROXY_KEY` for the supplied
private endpoint. Requests use synthetic launch data, not Echelon workflows.

## Author, reviewer, bounded repair, human approval

```text
brief (fast) → draft (balanced) → review (strong) → gate
                  ↑                                │
                  └──────── rejected ───────────────┤
                                                   ↓ approved
                                  decision (ultra) → human pause → done/rejected
```

```sh
.venv/bin/prosaic-harness run examples/tokenproxy-review.yml \
  --input examples/request.json --run-dir runs/review --events
.venv/bin/prosaic-harness status --run-dir runs/review
.venv/bin/prosaic-harness resume examples/tokenproxy-review.yml \
  --run-dir runs/review --choice approve
```

The author receives the latest review on repair. Each model's response must pass
its JSON Schema before the next step runs. A valid review with `approved: false`
follows the repair edge; malformed JSON/schema failure retries the same invocation
with feedback. Limits are ten calls, three visits per step, and two attempts per
visit. Limit exhaustion blocks rather than approving by default. `review.yml`
uses your operator-configured profiles instead of TokenProxy.

Inspect `run.json` for accepted outputs and decisions, and `attempts/*.json`
for all raw outputs, model events, validation history associations, and usage.
Schema validation proves shape and declared bounds, not factual correctness.
A reviewer's semantic verdict is also model output; human acceptance remains a
separate event. An interruption at the human pause needs no further model call.

## Read-only file evidence

```sh
.venv/bin/prosaic-harness run examples/tokenproxy-read-only.yml \
  --input examples/read-request.json --run-dir runs/read --events
```

The balanced reader declares read tools in Markdown, YAML allows only `read_file`,
and the step grants it only within `examples/evidence`. The source is synthetic,
including a quoted instruction that the agent should ignore. Use `read-only.yml`
for another endpoint. The step requires a successful `read_file` event before
accepting the JSON result, so a schema-valid claim of a read cannot advance alone.
Inspect the receipt's tool event and answer for correctness; the check verifies
tool success, not which file was read or the accuracy of the findings.

## Python embedding

```sh
.venv/bin/python examples/run_workflow.py examples/tokenproxy-review.yml \
  --input examples/request.json --run-dir runs/python-review
.venv/bin/python examples/run_workflow.py examples/tokenproxy-review.yml \
  --run-dir runs/python-review --resume --choice approve
```

The public API is `Workflow.load(path)` followed by
`Harness(workflow, run_dir).run(json_input)` or `.resume(choice=...)`.
Applications may supply `on_event` for progress and a compatible `runtime` object
for an execution adapter. The default adapter is Prosaic Runtime v0.2.0.
Callbacks should not raise exceptions; a raised callback interrupts the run.
Blueprints are repository assets; clone the repository to use them.
