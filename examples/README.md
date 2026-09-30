# Reusable workflow blueprints

Start with the installation and endpoint setup in the [root README](../README.md).
Run commands below from the repository root. `.venv/bin` must be on PATH so the
controller can inspect Markdown with the installed Prosaic CLI.

## Single validated agent

```sh
.venv/bin/prosaic-harness run examples/single.yml \
  --checks examples/checks.py --input examples/request.json --run-dir runs/single
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
                           decision (ultra) → final review (strong) → final check
                                ↑                  │                     │
                                └── rejected ──────┘                     ↓
                                                          human pause → done/rejected
```

```sh
.venv/bin/prosaic-harness run examples/tokenproxy-review.yml \
  --checks examples/checks.py --input examples/request.json --run-dir runs/review --events
.venv/bin/prosaic-harness status --run-dir runs/review
.venv/bin/prosaic-harness resume examples/tokenproxy-review.yml \
  --checks examples/checks.py --run-dir runs/review --choice approve
```

The author receives the latest review on repair. Each model's response must pass
its JSON Schema before the next step runs. A valid review with `approved: false`
follows the repair edge; malformed JSON/schema failure retries the same invocation
with feedback. Limits are fourteen calls, three visits per step, two attempts per
visit and a one-hour whole-run deadline. Exhaustion blocks; it never approves by
default. `review.yml`
uses your operator-configured profiles instead of TokenProxy.

Inspect `run.json` for accepted outputs and decisions, and `attempts/*.json`
for all raw outputs, model events, validation history associations, and usage.
Schema validation proves shape and declared bounds, not factual correctness.
A reviewer's semantic verdict is also model output; human acceptance remains a
separate event. An interruption at the human pause needs no further model call.

## Read-only file evidence

```sh
.venv/bin/prosaic-harness run examples/tokenproxy-read-only.yml \
  --checks examples/checks.py --input examples/read-request.json --run-dir runs/read --events
```

The balanced reader declares read tools in Markdown, YAML allows only `read_file`,
and the step grants it only within `examples/evidence`. The source is synthetic,
including a quoted instruction that the agent should ignore. Use `read-only.yml`
for another endpoint. The pinned Runtime v0.3.0 provides read provenance; see
[hardening setup](../docs/hardening.md).
The step requires successful read receipts covering the complete declared file
with its matching path and byte hash, then checks source IDs and supporting quotes.
This verifies which bytes reached the model, not its interpretation of them.

## Python embedding

```sh
.venv/bin/python examples/run_workflow.py examples/tokenproxy-review.yml \
  --checks examples/checks.py --input examples/request.json --run-dir runs/python-review
.venv/bin/python examples/run_workflow.py examples/tokenproxy-review.yml \
  --checks examples/checks.py --run-dir runs/python-review --resume --choice approve
```

The public API is `Workflow.load(path)` followed by
`Harness(workflow, run_dir, validators=...).run(json_input)` or `.resume(choice=...)`.
Applications may supply `on_event` for progress and a compatible `runtime` object
for an execution adapter. The default adapter is Prosaic Runtime v0.3.0.
Callbacks should not raise exceptions; a raised callback interrupts the run.
Blueprints are repository assets; clone the repository to use them.

## Evidence checks and reviewer probe

`--checks examples/checks.py` explicitly trusts and executes that local Python
file. Never load untrusted code. Its CHECKS registry is versioned by file hash.
Claims now carry source IDs and exact quotes; decisions carry structured numeric
calculations. The checker catches unknown IDs, reassigned/invented quotes,
unsupported metric labels and wrong denominators. Quotes alone do not prove
paraphrase correctness. Final semantic and human review remain separate safeguards.
The clean path makes five model calls across all four tiers.

To spend two calls testing the reviewer against intentionally bad drafts:

```sh
.venv/bin/python examples/evaluate_reviewer.py --config examples/tokenproxy.yml --live
```

Both drafts must be rejected. Approval or malformed output makes the probe fail;
schema validity alone is not a passing evaluation.
