# Prosaic Harness

A small Python harness for durable workflows built from neutral Prosaic agents.
Define a graph in YAML, execute agents through Prosaic Runtime, validate their
JSON outputs, and resume from local checkpoints. Apache-2.0.

| Component | Owns |
| --- | --- |
| [Prosaic](https://github.com/B3Cognition/prosaic) | Markdown agents and resource inspection |
| [Prosaic Runtime](https://github.com/B3Cognition/prosaic-runtime) | One model invocation, model tiers, tools, streaming, permissions |
| Prosaic Harness | Steps, validation, transitions, review loops, human pauses, run evidence |

The initial release supports Linux and macOS with Python 3.11+. It needs an
existing OpenAI-compatible endpoint and the Prosaic CLI (Node.js 20+). Windows
users can use WSL. The library imports no Echelon code.

## First run

Install Git, Python 3.11+, and Node.js 20+ before starting. Use an explicit Python
environment so another application's older runtime cannot be picked up by accident.

```sh
git clone https://github.com/B3Cognition/prosaic-harness.git
cd prosaic-harness
python3 -m venv .venv
.venv/bin/python -m pip install .

# Install the tested Prosaic revision inside this checkout.
mkdir -p .tools
git clone https://github.com/B3Cognition/prosaic.git .tools/prosaic
git -C .tools/prosaic checkout 0f7e187
npm --prefix .tools/prosaic ci
npm install --global --prefix "$PWD/.venv" "$PWD/.tools/prosaic"
export PATH="$PWD/.venv/bin:$PATH"
prosaic --help
.venv/bin/prosaic-harness --help
```

Keep `.tools/prosaic` in place; npm links the CLI to that checkout. In a future
terminal, return to the repository and add its `.venv/bin` to PATH again. The
dependency pin installs Prosaic Runtime v0.2.0 and PyYAML automatically.

### Configure an endpoint

Edit `examples/runtime.yml`: replace the localhost URL and `your-model` with your
operator's values. Each profile names an endpoint, model, credential environment
variable, and optional transport features. Prose `model_tier` selects a profile
through `routes`. Set the key without putting it into YAML:

```sh
export LOCAL_LLM_API_KEY="$(.venv/bin/python -c 'import getpass; print(getpass.getpass("Endpoint key: "))')"
```

An unauthenticated endpoint may omit `api_key_env`. If your endpoint rejects
streaming usage reporting, set `stream_options: false`. Diagnostics do not
generate text unless you explicitly request inference:

```sh
.venv/bin/prosaic-runtime doctor --config examples/runtime.yml --output text
```

For the private TokenProxy demo, `examples/tokenproxy.yml` supplies the four model
profiles. `examples/tokenproxy-single.yml` and `examples/tokenproxy-review.yml`
select that configuration. They require access to `10.16.81.27:8080`:

```sh
source ~/.zshrc
export TOKENPROXY_KEY
.venv/bin/prosaic-runtime doctor --config examples/tokenproxy.yml --output text
```

### Run one agent with validation

```sh
.venv/bin/prosaic-harness validate examples/single.yml
.venv/bin/prosaic-harness run examples/single.yml \
  --input examples/request.json --run-dir runs/first-note
.venv/bin/prosaic-harness status --run-dir runs/first-note
```

For TokenProxy, substitute `examples/tokenproxy-single.yml`. This makes a real
model request. The briefer must return JSON matching `examples/schemas/brief.json`;
invalid output triggers bounded retries with validation feedback. Completion
prints the accepted object. Use a fresh run directory for another input.

### Run a review and repair workflow

```sh
.venv/bin/prosaic-harness run examples/tokenproxy-review.yml \
  --input examples/request.json --run-dir runs/launch-review
```

This exercises four tiers: Ornith briefs the request, Qwen drafts a recommendation,
DeepSeek reviews it, and Nemotron creates a final decision. A gate routes an
unapproved review back to the author. The author receives the previous review
as an identified input artifact. The final decision pauses for human approval:

```sh
.venv/bin/prosaic-harness resume examples/tokenproxy-review.yml \
  --run-dir runs/launch-review --choice approve
```

Choose `reject` to finish with a rejected outcome. Approval records a decision;
it does not publish files or send messages. Use `examples/review.yml` for your
own configured endpoint. See [examples/README.md](examples/README.md) for the
graph, contracts, tool example, and a complete Python embedding program.

## Workflow format

All paths in a workflow are relative to its directory and confined to it. The
workflow can be launched from any working directory. Schema references are
internal to their document. Arbitrary expressions and remote schema fetching
are not supported.

```yaml
version: 1
source: .prosaic
runtime: runtime.yml
start: draft
limits:
  max_calls: 8
  max_visits: 3
  timeout_s: 180
steps:
  draft:
    kind: agent
    agent: subagents/author.md
    schema: schemas/draft.json
    optional_inputs: [review]
    max_attempts: 2
    next: review
  review:
    kind: agent
    agent: subagents/reviewer.md
    schema: schemas/review.json
    inputs: [draft]
    next: gate
  gate:
    kind: gate
    from: review
    field: [approved]
    equals: true
    pass: done
    fail: draft
  done:
    kind: finish
```

Agent `arguments` are a JSON object with `request` (the run input), `artifacts`
(selected prior accepted outputs, keyed by step ID), and `validation_feedback`
(the last validation error, if any). `inputs` are required; `optional_inputs`
include an output only when it exists, allowing first-pass review loops.
Outputs replace a step's latest accepted value on revisits, while every attempt
is retained in receipts. Raw transport stdout must be one JSON value; a single
JSON Markdown fence is also accepted. Schema failures do not advance the graph.

| Step kind | Fields and behavior |
| --- | --- |
| `agent` | `agent`, `schema`, `next`; optional input IDs, tools/read roots, required successful tools, attempts, visits |
| `gate` | `from`, `field` (list of keys), `equals`, `pass`, `fail`; missing data blocks |
| `pause` | `question`, `choices` mapping named answers to next steps |
| `finish` | Optional `outcome: completed` or `rejected` |

Each step may override `max_visits`. Agent attempts bound validation/transport
retries within a visit; visits bound graph loops; `max_calls` bounds invocations
across the whole run, including authorized interrupted retries. `timeout_s` is
per invocation. There is no whole-run monetary or token budget in v0.1: missing
provider accounting is preserved as unavailable. Finite graph visits also bound
non-agent loops. There is no automatic model escalation.

## Permissions and evidence

Default agent permissions are empty. A workflow step may declare read tools and
explicit `read_roots`; the runtime also intersects those with the prose's tools
and runtime configuration grants. Optional `require_tools: [read_file]` rejects
an output unless the invocation produced a successful tool event for that name;
it does not prove which file was read or whether the answer interpreted it correctly.
V0.1 has no shell checks, agent file writes,
publication effects, remote workers, or recursive agent dispatch. Application
integrations can be added through an explicit boundary in a later release.

Run evidence is local:

```text
runs/launch-review/
  run.json                 # sole durable state authority, accepted outputs, history
  run.lock                 # OS-backed lock prevents concurrent writers
  attempts/<id>.json       # arguments, raw result, token usage, model/tool events
```

`--events` emits JSONL events and a final status report to stdout. Normal mode
prints status and a five-second heartbeat to stderr and accepted results to stdout.
Credentials remain in environment/secret files; run evidence contains supplied
inputs and model output, so give its directory the same protection as the inputs.
The harness does not redact arbitrary sensitive information supplied by users.

## Resume and interruption

```sh
.venv/bin/prosaic-harness resume examples/review.yml --run-dir runs/launch-review
```

The harness saves a pending invocation before contacting the runtime, then saves
its receipt before committing the accepted output and transition. If a receipt
survived, resume adopts it without making another request. If no receipt survived,
the run blocks with `interrupted_call`: the endpoint may already have processed
the request. Explicitly authorize another billable call with:

```sh
.venv/bin/prosaic-harness resume examples/review.yml \
  --run-dir runs/launch-review --retry-interrupted
```

This consumes another call slot. There is no exactly-once guarantee for model
calls or their tool activity. Definitions, schemas, inspected prose, and runtime
configuration are fingerprinted; changes require a new run. Credential rotation
through the same environment-variable name does not change the fingerprint.
Limit-exhausted runs remain blocked; start a new run with revised limits rather
than modifying stored state. State assumes trusted local storage, not adversarial
tampering. CLI exit codes: 0 completed/waiting, 1 blocked/rejected, 2 configuration
or usage error, 130 interrupted. Waiting is explicit, not final acceptance.

## Development

```sh
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest
.venv/bin/python -m build
```

Tests cover schema retries, branching/repair, human choices, bounds, interrupted
calls, receipt recovery, definition changes, locking, tool scope, and transport
integration. Live runs are opt-in examples, not part of the offline suite.
