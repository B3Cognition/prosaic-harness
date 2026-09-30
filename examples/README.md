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

## Staged acquisition and no-tool preloading

The staged blueprint requires the development Runtime, not the published v0.3.0
pin. With sibling checkouts, install Harness using the root README, then override
only its Runtime dependency in the same environment:

```sh
.venv/bin/python -m pip install --no-deps -e ../prosaic-runtime
export PATH="$PWD/.venv/bin:$PATH"
export TOKENPROXY_KEY  # after loading the value from your shell configuration
.venv/bin/prosaic-harness validate examples/tokenproxy-staged-read.yml --checks examples/checks.py
.venv/bin/prosaic-harness run examples/tokenproxy-staged-read.yml \
  --checks examples/checks.py --input examples/read-request.json --run-dir runs/staged-first --events
.venv/bin/prosaic-harness run examples/tokenproxy-preloaded-evidence.yml \
  --checks examples/checks.py --input examples/read-request.json --run-dir runs/preloaded-first --events
```

Use new run directories each time. On uv-created environments without pip, use
`uv pip install --python .venv/bin/python --no-deps -e ../prosaic-runtime`.
For another endpoint, configure `runtime.yml` and substitute `staged-read.yml`
or `preloaded-evidence.yml` respectively. Preloading works with the released
Runtime pin; staging fails preflight when `acquisition_v1` is unavailable.

Staging sends only `evidence-acquisition.md` at first. The existing granted
`read_file` must succeed before `evidence-reader.md`, final caller arguments
and JSON instructions are appended to the same conversation. Both phases count
as one Harness invocation; output-validation retries start a new bounded
invocation, including a new acquisition. Missing/failed acquisition never retries
or changes modes automatically. Full-file/hash receipts and the existing
schema/source/quote checks remain required. Model reads after acquisition are
still subject to the same tool budget.

The no-tool blueprint instead passes the controller's immutable evidence
snapshot to `evidence-analyst.md`. It advertises no tools and produces no native
read events. Both paths use the same brief schema and source/quote validator.
Neither path guarantees interpretation accuracy just because bytes arrived.

Run the same validated task across every configured model, streaming on/off:

```sh
.venv/bin/python examples/evaluate_evidence.py --live --config examples/tokenproxy.yml \
  --streaming both --jobs 2 --run-dir runs/evidence-matrix-first
```

`--live` explicitly authorizes requests; `--mode staged`/`preloaded` and
`--streaming on`/`off` narrow the matrix. Concurrency is capped at two. JSONL
reports admission and native-read counts; run directories preserve receipts and
validation feedback. Any blocked case makes the program exit 1. This is a live
diagnostic, not an accuracy benchmark or a tier ranking.

### Explicit JSON response mode

Some endpoints honor native tools but still return explanatory text around the
final JSON. The Harness rejects that text instead of extracting a convenient
substring. On the supplied TokenProxy, Ornith's staged example completed with
streaming both on and off when JSON mode was explicitly enabled (one invocation
and one native read each). That is a small endpoint-specific observation, not a
general guarantee.

For JSON-only examples, copy `tokenproxy.yml` to an ignored
`tokenproxy-json.local.yml` and replace its `ornith` profile with:

```yaml
  ornith:
    <<: *endpoint
    model: ornith-1.5-35b
    features:
      streaming: true
      stream_options: true
      json_mode: true
```

Then pass `--config examples/tokenproxy-json.local.yml` to the matrix program
above. The acquisition request deliberately omits `response_format`; JSON mode
applies after acquisition and to preloaded analysis. Use it only when your
endpoint supports `response_format: {type: json_object}` and the final prose
asks for JSON. Defaults remain unchanged, no automatic retry switches modes,
and schema/source/quote admission checks still apply.

## Python embedding

### Three-document incident review

Two larger blueprints use the same synthetic timeline, metrics and investigation
notes (about 8 KiB total). They test denominator confusion, unscored correctness,
unconfirmed root cause, missing ownership, and quoted prompt-injection demands.
All source/quote checks stay enabled.

`incident-staged-review.yml` dispatches three independent bounded fragment
agents. Each must acquire its one scoped file before receiving full prose.
The controller then runs a tool-free synthesis, an independent reviewer,
bounded repair, and a human pause. The native reads have path/hash/full-coverage
receipts. Multiple required files use separate controller-owned acquisitions:
the first short phase does not rely on a model voluntarily choosing later reads.
The clean path is five invocations; repairs revisit synthesis/review, not reads
of unchanged evidence. The entire run allows ten invocations and two visits.

`incident-preloaded-review.yml` supplies all three immutable file snapshots
directly to a tool-free analyst, followed by the same independent reviewer and
human pause. Its clean path is two invocations; it grants no native tools and
allows at most six calls. A model's approval never authorizes publication.

With the development Runtime installed as above:

```sh
.venv/bin/python examples/run_workflow.py examples/incident-staged-review.yml \
  --config examples/tokenproxy.yml --checks examples/checks.py \
  --input examples/read-request.json --run-dir runs/incident-staged-first
.venv/bin/python examples/run_workflow.py examples/incident-preloaded-review.yml \
  --config examples/tokenproxy.yml --checks examples/checks.py \
  --input examples/read-request.json --run-dir runs/incident-preloaded-first
```

Inspect the accepted outputs and `run.json` before supplying a human choice.
Resume with the exact same workflow and config:

```sh
.venv/bin/python examples/run_workflow.py examples/incident-staged-review.yml \
  --config examples/tokenproxy.yml --checks examples/checks.py \
  --run-dir runs/incident-staged-first --resume --choice approve
```

Choose `reject` instead to reject; that status has exit code 1 in the embedding
program. No further inference is needed for either human choice. For your own
endpoint, configure `runtime.yml` and omit the override. `--config` is a host
choice sealed in the run fingerprint; changing it on resume is rejected.

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
