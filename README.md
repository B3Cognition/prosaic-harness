# Prosaic Harness

Development **0.6.0** adds RunStore and a separately installed PostgreSQL adapter
(development **0.1.0**) for cross-worker durable workflows. Neither is published
yet. Core remains database-free; filesystem constructors/CLI remain supported.
See [explicit database setup/grants](adapters/postgres/README.md) and the
[zero-model-call two-worker example](examples/postgres/README.md). Prose tools
do not grant database access; applications retain tenant authorization and
filter private run state.

The [RunStore ruling register](docs/decisions/2026-10-08-run-store-postgres-rulings.md)
preserves implementation/review decisions, reasons and risks with stable IDs.

Version 0.5.0 adds schema-validated human responses at durable workflow pauses,
with trusted validators and retained feedback for downstream agents and checks.
It pins Runtime v0.5.3 and automatically installs Python Prosaic v0.3.1.
Installation and CI no longer require Node.js or npm.

Version 0.4.0 adds [manifest-defined CLI tools](examples/README.md#custom-command-line-tools)
through the normal workflow CLI, with offline availability checks and required
native execution evidence. The current immutable dependency pin installs Runtime v0.5.3.

## CLI permissions and sandboxing

Harness **0.5.0** retains CLI sandbox policy enforcement and pins Runtime
**0.5.3**, which provides `cli_sandbox_v1`. Follow the
[sandboxed workflow walkthrough](examples/README.md#sandboxed-cli-workflow-harness-042)
for installation, offline validation and live execution.
The complete blueprint is [cli-tool-sandboxed.yml](examples/cli-tool-sandboxed.yml).

Permissions are operator-owned, not granted by prose:

| Location | Setting | Meaning |
| --- | --- | --- |
| Agent Markdown | `tools: [analyze_spec]` | Request the tool; not authorization |
| Runtime YAML | `allowed_tools: [analyze_spec]` and reviewed `tool_directories` | Allow the tool and trust its manifest/executable |
| Workflow agent step | `tools: [analyze_spec]`, `read_roots: [evidence]` | Grant that step the tool and narrow readable inputs |
| Runtime YAML | `cli_sandbox: {mode: required}` | Enforce OS isolation for CLI execution and probes |
| Workflow agent step | `require_tools: [analyze_spec]` | Require observed successful execution; grants nothing extra |

All tool permission layers must agree. `validate` loads the workflow and runs
offline CLI preflight; it does not contact a model or need an endpoint key.
The sandbox is off by default. Required mode fails closed if unavailable;
Linux needs Bubblewrap >= 0.12.0 and permitted user namespaces, while macOS needs
Seatbelt's `sandbox-exec`. See [Runtime's setup](https://github.com/B3Cognition/prosaic-runtime/blob/main/docs/cli-tools.md).

Sandboxed CLIs can read granted evidence and write private scratch, but cannot
write the workspace or reach the host IP network. Keep host Unix sockets outside
granted directories. Extra dependencies need narrow `runtime_roots`, not HOME or
`/`. This does not sandbox Python callbacks, validators or native coding providers;
builtin read tools retain their existing path checks. Harness itself still writes
durable run state on the host. Required-mode policy is sealed into workflow
identity: changes invalidate existing approvals/resume, and injected adapters
cannot silently downgrade it. Use a fresh run directory when changing policy.

## Overview

The [custom-tool embedding example](examples/README.md#host-registered-custom-tools)
adds catalogue lookup, version-bound native execution evidence, deterministic
answer admission and a human pause. It requires Harness v0.4.0+ / Runtime v0.5.0+.

A small Python harness for durable workflows built from neutral Prosaic agents.
Define a graph in YAML, execute agents through Prosaic Runtime, validate their
JSON outputs, and resume from local checkpoints. Apache-2.0.

| Component | Owns |
| --- | --- |
| [Prosaic](https://github.com/B3Cognition/prosaic) | Markdown agents and resource inspection |
| [Prosaic Runtime](https://github.com/B3Cognition/prosaic-runtime) | One model invocation, model tiers, tools, streaming, permissions |
| Prosaic Harness | Steps, validation, transitions, review loops, human pauses, run evidence |

The initial release supports Linux and macOS with Python 3.11+. It needs an
existing OpenAI-compatible endpoint and the Python Prosaic CLI. Windows
users can use WSL. The library imports no Echelon code.

Version 0.2.0 adds versioned approvals, trusted checks and final-output validation,
and hash-bound read provenance. Version 0.3.0 pins Prosaic Runtime 0.4.0, adding
opt-in acquisition, strict initial-tool enforcement, admission-time resource
checks and larger incident-review examples. State format is
version 2; existing 0.1 runs must start afresh. See
[hardening setup and contracts](docs/hardening.md).

## First run

Install Git and Python 3.11+ before starting. Use an explicit Python
environment so another application's older runtime cannot be picked up by accident.

```sh
git clone https://github.com/B3Cognition/prosaic-harness.git
cd prosaic-harness
git checkout v0.5.0
python3 -m venv .venv
.venv/bin/python -m pip install .

export PATH="$PWD/.venv/bin:$PATH"
prosaic --help
.venv/bin/prosaic-harness --help
```

In a future terminal, return to the repository and add its `.venv/bin` to PATH
again. Node.js and npm are not required. The dependency pin installs Prosaic
Runtime v0.5.3, Python Prosaic v0.3.1, PyYAML and jsonschema automatically.
No sibling checkout or manual Prosaic installation is needed. Older Harness
tags retain their historical installation docs.

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
.venv/bin/prosaic-harness validate examples/single.yml --checks examples/checks.py
.venv/bin/prosaic-harness run examples/single.yml \
  --checks examples/checks.py --input examples/request.json --run-dir runs/first-note
.venv/bin/prosaic-harness status --run-dir runs/first-note
```

For TokenProxy, substitute `examples/tokenproxy-single.yml`. This makes a real
model request. The briefer must return JSON matching `examples/schemas/brief.json`;
invalid output triggers bounded retries with validation feedback. Completion
prints the accepted object. Use a fresh run directory for another input.

### Run a review and repair workflow

```sh
.venv/bin/prosaic-harness run examples/tokenproxy-review.yml \
  --checks examples/checks.py --input examples/request.json --run-dir runs/launch-review
```

This exercises four tiers: Ornith briefs the request, Qwen drafts a recommendation,
DeepSeek reviews it, and Nemotron creates a final decision. A gate routes an
unapproved review back to the author. The author receives the previous review
as an identified input artifact. The actual final decision gets its own model
review and deterministic evidence check before pausing for human approval:

```sh
.venv/bin/prosaic-harness resume examples/tokenproxy-review.yml \
  --checks examples/checks.py --run-dir runs/launch-review --choice approve
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
is retained in receipts and approvals bind to exact required-input versions.
Optional inputs can carry stale feedback, not required approval dependencies.
Arguments also include `artifact_bindings` and declared file `sources`.
Raw transport stdout must be one JSON value; a single
JSON Markdown fence is also accepted. Schema failures do not advance the graph.

| Step kind | Fields and behavior |
| --- | --- |
| `agent` | `agent`, `schema`, `next`; optional `acquisition` prose ID, input IDs, tools/read roots, required successful tools, attempts, visits |
| `gate` | `from`, `field` (list of keys), `equals`, `pass`, `fail`; missing data blocks |
| `check` | `from`, trusted `validators`, `pass`, `fail`; no model call |
| `pause` | `question`, `choices` mapping named answers to next steps |
| `finish` | Optional `outcome: completed` or `rejected` |

A pause can optionally declare `response_schema: schemas/feedback.json` and
host-registered `validators`. Submit `resume(choice="refine", response={"text": "..."})`
or CLI `resume ... --choice refine --response feedback.json`. The schema validates
the payload; trusted pause validators receive `{"choice": ..., "response": ...}`
with the original request and accepted artifacts in their check context. Applications
can verify dynamic candidate membership there without encoding product IDs into the
workflow graph. Invalid responses leave the pause untouched. Accepted responses are
sealed into history and subsequent agent arguments include `human_responses`, keyed
by pause step with its latest `choice` and `response`. They are user data, never tool
permissions. Existing choice-only pauses retain their original behavior and reject
payloads. A completed response cannot be submitted again.
Trusted downstream validators also receive these accepted values through
`CheckContext.human_responses`; they can enforce that a proposal matches the user's
selection rather than trusting a model's account of that selection.

`max_run_s` includes human waiting. Interactive applications should use an explicit
human expiry for a decision workflow and a separate bounded workflow for each model
turn; do not reuse a short model request timeout as a human response deadline.

Each step may override `max_visits`. Agent attempts bound validation/transport
retries within a visit; visits bound graph loops; `max_calls` bounds invocations
across the whole run, including authorized interrupted retries. `timeout_s` is
per invocation. Optional `max_tokens` counts all reported tokens and blocks on
unknown usage; `max_run_s` persists a whole-run deadline including human waiting.
There is no monetary guarantee. Finite graph visits also bound
non-agent loops. There is no automatic model escalation.

## Permissions and evidence

Default agent permissions are empty. A workflow step may declare read tools and
explicit `read_roots`; the runtime also intersects those with the prose's tools
and runtime configuration grants. Optional `require_tools: [read_file]` rejects
an output unless the invocation produced a successful tool event for that name;
it does not prove which file was read or whether the answer interpreted it correctly.
Declare `evidence` and `require_reads` for hash-bound complete-file read evidence.
Development-only `acquisition: subagents/evidence-acquisition.md` sends a short
Prosaic artifact before the full agent assignment. It requires `require_reads`
and Runtime `acquisition_v1`; both prose digests are part of the sealed workflow
fingerprint. One Runtime invocation owns both phases, their shared deadline,
usage and tool budget. Failed acquisition blocks without automatic repair or
fallback. Final JSON/schema/source checks still apply after successful reads.
Acquisition gets no final arguments; its own prose specifies the evidence path.
For model-independent acquisition, explicitly choose the no-tool
`preloaded-evidence.yml` blueprint instead: the controller supplies immutable
evidence text in `sources`. This is snapshot evidence, not a native tool receipt.
See the [step-by-step examples](examples/README.md#staged-acquisition-and-no-tool-preloading).
The [direct-read problem and staged-acquisition resolution](examples/tool-acquisition.md)
show how to keep a detailed answer contract out of the initial read phase and
verify the native receipt before analysis.
Trusted checks are explicitly supplied by the host through `validators=` or CLI
`--checks`. They execute Python with host permissions and are not sandboxed.
V0.2 has no shell checks, agent file writes,
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
.venv/bin/prosaic-harness resume examples/review.yml --checks examples/checks.py --run-dir runs/launch-review
```

The harness saves a pending invocation before contacting the runtime, then saves
its receipt before committing the accepted output and transition. If a receipt
survived, resume adopts it without making another request. If no receipt survived,
the run blocks with `interrupted_call`: the endpoint may already have processed
the request. Explicitly authorize another billable call with:

```sh
.venv/bin/prosaic-harness resume examples/review.yml \
  --checks examples/checks.py --run-dir runs/launch-review --retry-interrupted
```

This consumes another call slot. There is no exactly-once guarantee for model
calls or their tool activity. Definitions, schemas, inspected prose, and runtime
configuration and validator versions are fingerprinted; changes require a new
run. Declared evidence changes also reject resume. Credential rotation
through the same environment-variable name does not change the fingerprint.
Limit-exhausted runs remain blocked; start a new run with revised limits rather
than modifying stored state. State assumes trusted local storage, not adversarial
tampering. Checksums and structural checks detect corruption, not coordinated
forgery. New checkpoints are version 2; old runs need a new directory.
CLI exit codes: 0 completed/waiting, 1 blocked/rejected, 2 configuration
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

## Structured JSON tools

This revision pins Prosaic Runtime 0.5.3, which supplies `StructuredToolLoop` for
explicit JSON tool-request transport. Product adapters can yield one Runtime
turn per Harness invocation while retaining application-owned result validators.
Register the same `CustomTool` descriptors with the workflow and adapter so
Harness fingerprints and checks their contracts. Harness retains routing and
checkpoint ownership; Runtime owns parsing, dispatch, bounds and repeat detection.
