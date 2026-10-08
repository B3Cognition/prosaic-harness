# Reusable workflow blueprints

## Cross-worker PostgreSQL storage (development Harness 0.6.0)

The [PostgreSQL walkthrough](postgres/README.md) starts a human-only workflow in
one process and resumes it in another with a fresh revision. No model endpoint
is needed. A synthetic-agent fixture separately exercises real Runtime inference.
Install/initialize the optional adapter and apply the exact runtime grants in
the [setup guide](../adapters/postgres/README.md); database permissions do not
belong in Markdown. These development versions are not published releases.

## Sandboxed CLI workflow (Harness 0.4.2)

Use [cli-tool-sandboxed.yml](cli-tool-sandboxed.yml) with
[cli-tools-sandboxed-runtime.yml](cli-tools-sandboxed-runtime.yml) for required
CLI OS isolation. Harness 0.4.2 pins Runtime 0.5.2 with `cli_sandbox_v1`;
Harness 0.4.1 and earlier do not include this feature. Upgrading Prosaic or
changing agent Markdown alone does not enable it.

### 1. Install the coordinated release

Assume sibling Harness v0.4.2 and Runtime v0.5.2 checkouts and an
existing Harness virtual environment. From the Harness repository root:

```sh
source .venv/bin/activate
python -m pip install -e .
# Harness installs its immutable Runtime v0.5.2 dependency automatically.
python -m pip install ../prosaic-runtime/examples/cli-tool
```

For uv without pip, use `uv pip install --python .venv/bin/python` with each
corresponding set of install arguments. No sibling Runtime override is needed;
the sibling checkout supplies only the example executable. No global application
installation is changed by this example.

Install the analyzer into the **same environment** as Harness, without `-e`.
Editable CLI implementations or tools from another virtualenv need additional
narrow dependency/interpreter grants; the standard package install above avoids
those extra grants. For this sample's optional editable install, the config-relative
source grant would be `runtime_roots: [../../prosaic-runtime/examples/cli-tool]`.
Do not grant a whole repository, HOME or `/` as a workaround.

The environment's `prosaic` must be on PATH. macOS needs `/usr/bin/sandbox-exec`;
Linux (including ARM64) needs `/usr/bin/bwrap` >= 0.12.0 and permitted unprivileged
user namespaces. See the [Runtime setup](https://github.com/B3Cognition/prosaic-runtime/blob/main/docs/cli-tools.md#opt-in-cli-sandbox).
Do not disable host security or fall back to off mode to bypass a setup failure.

### 2. Review all permission layers

The example uses the same neutral [agent](.prosaic/subagents/cli-spec-reviewer.md)
and operator-reviewed [manifest](.prosaic/tools/analyze-spec.yml) as the ordinary
CLI example. The agent frontmatter declares `tools: [analyze_spec]`; no Markdown
sandbox or filesystem permission fields are added.

| Location | Sample setting | What it does |
| --- | --- | --- |
| Runtime YAML | `tool_directories: [.prosaic/tools]` | Trust reviewed CLI manifests/executables |
| Runtime YAML | `allowed_tools: [analyze_spec]` | Operator allowlist |
| Agent step | `tools: [analyze_spec]`, `read_roots: [evidence]` | This step's tool/input grants |
| Runtime YAML | `cli_sandbox: {mode: required}` | Enforce OS confinement for CLI calls and probes |
| Agent step | `require_tools: [analyze_spec]` | Reject results without observed successful execution |
| Next step | `kind: pause` | Require an explicit human choice, not model approval |

Agent declaration, config allowlist and step grants must all agree. Installing a
tool grants nothing. Evidence roots are relative to the workflow directory;
manifest/dependency roots are relative to Runtime YAML. The CLI cannot write the
workspace or access the host IP network. It can write private HOME/scratch.
Harness itself, outside the CLI sandbox, remains the sole writer of durable run state.

### 3. Validate offline before any live run

```sh
prosaic-harness validate examples/cli-tool-sandboxed.yml
```

Expect exit code 0 and successful validation. This performs workflow validation
and sandboxed CLI version preflight without contacting the placeholder endpoint
or needing an endpoint credential. It does not execute the analysis task.
Missing grants/executable or unavailable confinement stop loading before inference.

Before running, replace `base_url` and `model` in
`examples/cli-tools-sandboxed-runtime.yml` with your tool-calling endpoint/model.
Load `LOCAL_LLM_API_KEY` securely if needed; never put keys in YAML/Git. Use a new
run directory for every new demo (the name below must not already contain a run):

```sh
prosaic-harness run examples/cli-tool-sandboxed.yml \
  --input examples/cli-tool-input.json --run-dir runs/cli-tool-sandboxed-demo --events

# Only after reviewing the admitted report, explicitly approve or reject:
prosaic-harness resume examples/cli-tool-sandboxed.yml \
  --run-dir runs/cli-tool-sandboxed-demo --choice approve --events
```

`run` contacts your model and may incur charges. A valid result has the synthetic
report `{"requirements":2,"vague_ids":["REQ-002"],"passed":false}`, observed
successful native tool execution, and workflow status `waiting` at the human
pause. `passed:false` describes the wording check, not an execution failure.
Resume without a choice keeps waiting; approval completes without another model
call. Approval acknowledges this demo report, not production readiness.

### Limits and failure behavior

Do not add HOME, `/`, or host Unix-socket directories to `read_roots` or
`runtime_roots`; add only narrowly reviewed extra dependencies. The model client's
credential stays with Runtime; CLI `pass_env` is a deliberate operator grant.
Builtin reads retain path checks, but Python callbacks/checks and native coding
providers are not isolated by this setting. Successful execution does not prove
answer truth. `require_tools` is not a builtin complete-file read receipt.

Required-mode policy is bound to workflow identity. Changing it invalidates
existing approvals/resume; start a fresh run rather than editing saved state.
Injected adapters cannot downgrade it. For `cli_sandbox_unavailable`, check the
OS backend/version/namespace restrictions. For missing grants or dependencies,
correct the narrow configuration; never broaden access just to pass validation.
See [Runtime's troubleshooting](https://github.com/B3Cognition/prosaic-runtime/blob/main/examples/README.md#scope-and-troubleshooting).

## Custom command-line tools

This example connects a normal installed executable to neutral prose,
then requires successful native execution before an explicit human pause. It does
not import a Python callback or install Echelon. Follow the root README to install
Harness v0.4.2+ (automatically installs Python Prosaic v0.3.0). Keep a sibling
Runtime v0.5.2 checkout only to install the standalone example executable. From
the Harness repository root:

**Compatibility mode:** this section uses `cli-tools-runtime.yml`, whose sandbox
defaults to off. Use the sandboxed workflow above for CLI isolation.

```sh
source .venv/bin/activate
# The Harness dependency pin already installs Runtime v0.5.2.
git clone --branch v0.5.2 https://github.com/B3Cognition/prosaic-runtime.git ../prosaic-runtime
python -m pip install -e ../prosaic-runtime/examples/cli-tool

prosaic-example-analyzer examples/evidence/requirements.md --json
prosaic tools --source examples/.prosaic   # requires updated Prosaic CLI
prosaic-harness validate examples/cli-tool.yml
```

For a uv environment without pip, use `uv pip install --python .venv/bin/python`
with the same install arguments. `validate` performs offline CLI preflight and
workflow validation; no endpoint key or inference is needed. Runtime loads only
the operator-trusted `tool_directories` in `cli-tools-runtime.yml`. Tool availability
does not grant permissions: the prose, Runtime config and workflow step must all
request/grant `analyze_spec`, with explicit read roots for its file argument.

Run the workflow against TokenProxy (real requests, may incur charges):

```sh
source ~/.zshrc
export TOKENPROXY_KEY
prosaic-harness run examples/cli-tool.yml \
  --input examples/cli-tool-input.json --run-dir runs/cli-tool-demo --events

# After reviewing the report, choose approve or reject; no additional model call.
prosaic-harness resume examples/cli-tool.yml \
  --run-dir runs/cli-tool-demo --choice approve --events
```

Choose a fresh run directory for each new run. The sample analyzes two synthetic
requirements and reports vague wording in REQ-002. `passed:false` concerns the
wording check, not whether execution succeeded. The workflow accepts only the
known synthetic report and requires a successful matching-version tool event;
fabricated JSON without execution is rejected. It then waits for the controller's
human choice. Approval acknowledges the demo report, not production readiness.

To compare models, copy the complete examples directory into an ignored
workspace, preserving source, schema and evidence paths, then change
`routes.balanced` to `ornith`, `deepseek` or `nemotron`. There is no automatic
fallback or retry after transport interruption. Custom CLI events are not builtin
read receipts and do not independently certify which source bytes were read.

See Runtime's
[complete CLI-tool contract](https://github.com/B3Cognition/prosaic-runtime/blob/main/docs/cli-tools.md)
for environment isolation, manifest versions, exit codes, timeout/output limits,
an optional Understanding adapter and security boundaries. CLI tools execute
trusted host code with sandboxing off in this compatibility example. Fixed argv is not complete prompt-injection
prevention; consequential tools require separate approval/isolation.

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
for another endpoint. The pinned Runtime v0.5.0 provides read provenance; see
[hardening setup](../docs/hardening.md).
The step requires successful read receipts covering the complete declared file
with its matching path and byte hash, then checks source IDs and supporting quotes.
This verifies which bytes reached the model, not its interpretation of them.

## Staged acquisition and no-tool preloading

For a runnable problem/resolution pair, see
[read evidence before producing a structured answer](tool-acquisition.md).
It contrasts premature JSON answers in direct mode with verified staged
acquisition, including expected receipts and deterministic assertions.

Harness v0.4.2 pins Runtime v0.5.2, which includes acquisition support. Install
Harness using the root README; no sibling checkout or dependency override is
needed. In the same environment:

```sh
export PATH="$PWD/.venv/bin:$PATH"
export TOKENPROXY_KEY  # after loading the value from your shell configuration
.venv/bin/prosaic-harness validate examples/tokenproxy-staged-read.yml --checks examples/checks.py
.venv/bin/prosaic-harness run examples/tokenproxy-staged-read.yml \
  --checks examples/checks.py --input examples/read-request.json --run-dir runs/staged-first --events
.venv/bin/prosaic-harness run examples/tokenproxy-preloaded-evidence.yml \
  --checks examples/checks.py --input examples/read-request.json --run-dir runs/preloaded-first --events
```

Use new run directories each time.
For another endpoint, configure `runtime.yml` and substitute `staged-read.yml`
or `preloaded-evidence.yml` respectively. Staging fails preflight when
`acquisition_v1` is unavailable, for example with an older Runtime override.

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

With Harness installed as above:

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
for an execution adapter. The default adapter is Prosaic Runtime v0.5.0.
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
## Host-registered custom tools

This example requires Harness v0.4.0+ and its pinned Runtime v0.5.0. Follow the
root guide for Python/Prosaic prerequisites. From this Harness repository root:

```sh
source .venv/bin/activate
python -m pip install -e .
source ~/.zshrc
export TOKENPROXY_KEY
python examples/run_custom_tool.py --live --run-dir runs/catalog-demo --sku SKU-001
python -m json.tool runs/catalog-demo/run.json
ls runs/catalog-demo/attempts
python examples/run_custom_tool.py --live --run-dir runs/catalog-demo --resume --choice reject
```

Use `approve` instead of `reject` to finish as completed. Neither choice performs
an external action. Use a fresh run directory for every new run. The pending
choice binds the admitted lookup output; a model/tool cannot create human approval.
To use another model/endpoint, copy `custom-tools-runtime.yml` to an ignored
`catalog.local.yml`, change `routes.fast` to `ornith`, `deepseek` or `nemotron`
(and `features.streaming` if needed), then supply the same `--config
catalog.local.yml` on both run and resume. Credentials stay in the named
environment variable. Do not mutate a run's configuration to repair it.

The [Python embedding](run_custom_tool.py) explicitly imports trusted
[catalog_tools.py](catalog_tools.py); YAML/prose never load modules. Registration
grants nothing: neutral prose must request lookup_catalog, Runtime YAML must
allow it, and the workflow step's tools become the host policy grant. Builtin
reads still require read_roots; this fixed-data callback does not. Builtin writes
remain unsupported. Generic `prosaic-harness run` does not import custom code;
use this embedding entrypoint for the example.

The lookup step requires a successful version-matched native tool event, a closed
[JSON schema](schemas/catalog-result.json), and the deterministic catalogue check.
A schema-valid invented price/record is rejected, with at most two invocations.
The version hashes exact catalogue bytes. Required descriptor/version changes
block resume before dispatch; unrelated registrations do not change identity.
Existing workflows without custom tools preserve their fingerprints/checkpoint v2.
An injected Runtime must advertise custom_tools_v1 and matching descriptors.

`--live` is required for new runs and conservatively for all resumes, since a
resume can dispatch inference; resolving an ordinary waiting choice uses no model
call. Final Runtime success/tool evidence does not itself prove answer truth.
Callbacks are trusted synchronous Python, not sandboxed or forcibly preemptible;
they cannot be rolled back or promised exactly-once. A consequential tool needs
an authorization predicate checking real host approval, never model-supplied fields.
Tool versions are honest host assertions, not automatic callback-source hashing.
Broader prompt-injection hardening and MCP evaluation remain separate queued work.
