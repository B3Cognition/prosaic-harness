# Verification

## Host-registered tools development verification (2026-10-01)

Stage 1 only: Runtime's public CustomTool registration, native execution and
Harness embedding/admission are implemented. Broader prompt-injection hardening
and MCP evaluation remain queued. Release versions and the immutable Runtime
dependency pin are unchanged; these checks use an explicit development override.

Source suites passed **207 Runtime tests and 101 Harness tests**, with Prosaic
on PATH and no skips. New tests exercise strict registration/argument/result
validation, schema snapshots, separate authorization copies, all permission
intersections, native HTTP/SSE tools, mixed denied builtin writes, acquisition
ordering, callback cancellation/deadlines and usage retention, redacted tool
diagnostics, adapter identity, matching-version admission, legacy fingerprints,
changed required versions and unused registrations on resume. Both shipped
programs run through real Prosaic inspection and a deterministic local server.
The Harness example rejects a schema-valid invented price and stops after the
two-attempt bound; a successful human rejection uses no additional inference.

Both source archives/wheels built into fresh temporary output directories, not
release assets. Archives contain catalogue data, trusted code, YAML, Markdown
and entrypoints, without local settings/run receipts. Development wheels were
explicitly installed together (Harness with --no-deps to avoid restoring its
published pin) into a fresh Python 3.12 environment. Both module import paths
were checked under site-packages; **207 Runtime / 101 Harness tests passed**
with pytest source paths disabled (`-o pythonpath=''`), without skips. This is a coordinated development check, not verification
that a normal released Harness can load custom tools yet.

The supplied TokenProxy returned HTTP 200 for discovery. Each model was tested
once per streaming mode in each companion, without changing mode or relaxing
admission following a failure:

| Model | Runtime HTTP / SSE | Harness HTTP / SSE |
| --- | --- | --- |
| qwen36-35b-a3b | success / tool_choice_not_honored | blocked / blocked |
| ornith-1.5-35b | success / success | waiting / waiting |
| deepseek-v4-flash | success / success | waiting / waiting |
| nemotron-3.5-lightning | success / tool_choice_not_honored | waiting / waiting |

Runtime successful cases each executed one native versioned lookup; the two
explicit-first-tool failures executed none. Qwen's Harness cases returned invented
Widget A records without a native lookup, exhausting two attempts; no output was
admitted. All six waiting cases had matching catalogue-version success events
and exact source/schema admission, then resumed with a real reject choice and
no further calls. Runtime transport success alone does not establish final-answer
truth. Receipts are ignored in runs/custom-tools-20261001 in both repositories.
This small stochastic matrix is not a reliability benchmark or tier ranking.

The fresh whole-change review found two minimum-contract defects, repaired
independently with reproduced RED→GREEN public transport tests and both full
suites after each: HTTP normalization could turn malformed arguments/type into
a valid empty custom call; callback Cancelled exception text could leak captures.
Custom raw shape now survives HTTP/SSE compatibility parsing, including invalid
SSE fragments, while builtin compatibility defaults remain unchanged. Public
cancellation uses a fixed safe message with exit 130 and known usage preserved.
Final source and refreshed installed-wheel suites pass **220 Runtime / 101 Harness
tests**, with no skips and installed-wheel pytest source paths disabled. The
post-fix Runtime source archive/wheel also rebuilt successfully.

A second full 16-case live matrix on the fixed code retained all admission rules:

| Model | Runtime HTTP / SSE | Harness HTTP / SSE |
| --- | --- | --- |
| qwen36-35b-a3b | tool_choice_not_honored / tool_choice_not_honored | blocked / blocked |
| ornith-1.5-35b | success / success | waiting / waiting |
| deepseek-v4-flash | success / success | waiting / waiting |
| nemotron-3.5-lightning | tool_choice_not_honored / success | waiting / waiting |

All three Runtime failures observed zero native calls, not a successful callback
discarded by the new validation. All five successful Runtime cases executed a
versioned lookup. All six Harness waiting cases passed exact catalogue admission,
then real reject without new inference; Ornith HTTP needed its bounded second
attempt. Qwen again fabricated schema-invalid records without a lookup. Receipts
for this second run are under runs/custom-tools-20261001/post-review in Harness
and matrix-post-review.jsonl in Runtime. Model/transport outcomes vary between
runs; these results do not justify weakening initial-tool or admission rules.

Trusted callbacks are synchronous in-process code: no sandbox, forced preemption,
rollback or exactly-once guarantee. A round cap is not an individual-call cap.
Versions identify host-declared semantics/data; they cannot detect a dishonest
host swapping callback code under the same version. Human approval is controller
input, never a model-supplied approved field. These are documented boundaries,
not a claim to eliminate prompt injection or protect against malicious host code.

## Coordinated releases (2026-10-01)

Harness v0.3.0 pins Runtime v0.4.0. Acquisition, initial-tool enforcement and the
extended campaign fixes below are now included in a normal released install.
The following development sections describe their historical verification;
their older dependency pins and override instructions do not describe v0.3.0.

Release verification reran all 138 Runtime tests and 85 Harness tests with no
skips, built both source archives and wheels, and checked packaged examples and
Apache-2.0 metadata. Runtime's release wheel also passed all 138 tests with source
imports disabled. A clean Harness wheel installation resolved Runtime directly
from the published immutable commit
`f2e870fa5f02e99125539428972c40bc42996e1a`; both installed import paths were checked
under `site-packages`. All 85 Harness tests passed there without editable
overrides or skipped acquisition integrations. Both incident blueprints validated
through the installed CLI. Runtime release CI passed on Python 3.11–3.13.

## Extended development campaign (2026-09-30)

The subsequent full-suite, edge-case, packaging, and live campaign is recorded in
[overnight-verification.md](overnight-verification.md). It supersedes the initial
development test counts below without changing the published dependency pin.

## Unreleased acquisition staging (2026-09-30)

The opt-in acquisition path and explicit no-tool preloading blueprint are now
implemented. Using the local companion Runtime, all 115 Runtime tests and 75
Harness tests passed with no skips; both sdist/wheel builds passed. Real local
HTTP/SSE tests verify acquisition-before-final-prose/arguments/resources,
JSON-format deferral, permission intersection, failed acquisition blocks,
shared deadlines/tool/input budgets, reported-usage retention, capability
preflight, workflow fingerprint binding, and runnable examples. The public
Runtime dependency pin remains v0.3.0; four staged transport integration cases
require the development override and skip when that capability is absent.
Preloaded evidence and capability-rejection tests do not require the override.
An isolated environment using the immutable published Runtime v0.3.0 pin passed
71 Harness tests and explicitly skipped those four staged integrations. The
live matrix script also preflights staging capability before starting either
mode, so a missing capability cannot start unrelated preloaded model requests.

Two live matrices exercised all four TokenProxy models, each with streaming
on/off and staged/preloaded evidence. In the first matrix all staged cases
performed native reads, but only Qwen's four outputs passed admission. Other
models used filenames as source IDs, invented IDs, or violated JSON formatting.
The example prose was clarified: source_id means the original S1–S4 label,
not the file path; unlabelled stakeholder text is not a new source. No schema,
validator, quote rule or retry limit was relaxed.

The second matrix admitted 14/16 cases:

| Model | Staged, nonstream / stream | Preloaded, nonstream / stream |
| --- | --- | --- |
| qwen36-35b-a3b | completed / completed (one invocation each) | completed / completed (one each) |
| ornith-1.5-35b | blocked / blocked | completed / completed (two each) |
| deepseek-v4-flash | completed / completed (one / two) | completed / completed (one each) |
| nemotron-3.5-lightning | completed / completed (one each) | completed / completed (two each) |

Every staged case acquired native read receipts. Ornith then prefixed its JSON
fence with explanatory text and exhausted the two-attempt limit; no output was
accepted. DeepSeek made additional reads in analysis under the shared grant and
budget. Every preloaded case produced zero native read events. Full source/path/
hash/coverage checks still apply to staged admission. Local receipts are ignored
under `runs/acquisition-matrix-20260930-r1` and `-r2`. Matrix exit 1 is expected
when any case is blocked. This is a small stochastic diagnostic, not proof of
general reliability, truth or model-tier rankings. The standalone Runtime
`run_acquisition.py` also completed both modes on streaming Qwen; it demonstrates
execution, not Harness admission.

## Unreleased initial-tool enforcement follow-up (2026-09-30)

Development Runtime now rejects absent, substituted or additional explicit
first-tool calls before executing them. Harness preserves the distinct
`tool_choice_not_honored` block reason without retry or accepted output. The
published v0.3.0 Runtime pin is unchanged; this follow-up needs the development
Runtime override described in [hardening.md](hardening.md).

Fresh suites passed 99 Runtime tests and 66 Harness tests; both package builds
passed. Harness's 66 tests also passed with the released v0.3.0 Runtime pin in an
isolated environment. Eight basic live probes (four TokenProxy model IDs,
streaming on/off, explicit first-tool selection) still executed native reads
with matching hashes and complete coverage. The original Qwen reader case now
blocks after one call, with zero accepted outputs and its reported usage kept:
`runs/initial-tool-enforcement-20260930-214333` (ignored local evidence).
This fixes false-success reporting, not the endpoint's omission. The subsequent
acquisition/preloading implementation and its live results are documented above.

## Version 0.2.0 hardening verification (2026-09-30)

Using the updated local companion Runtime, the full Harness suite passed 65
tests and Runtime passed 90 tests; source/wheel builds succeeded for both.
Regression coverage includes stale review versions, changed evidence, malformed
and resealed inconsistent checkpoints, altered receipts, crashes at durable
edges, validator failures/version changes, budgets/deadlines/cancellation, and
wrong-file/partial/mismatched-byte read requirements. Local HTTP tests exercise
the final review/check path, repair, human rejection and real read provenance.

TokenProxy discovery passed. `runs/hardening-review-r3-20260930` reached human
waiting after five calls across all four tiers, with an independent final review
and deterministic final evidence check. It was not human-approved. The live
adversarial probe rejected both checklist-as-factual-accuracy and
timeouts-excluded-as-overall-reliability drafts. Earlier probes hit bounded
repair limits; another run correctly rejected changed supporting quotations.
Successful admission in one stochastic run does not establish general quality.

The earlier stricter live read probes did not pass: Qwen returned text without
native tool calls, including with explicit initial tool choice and with streaming
off. The controller blocked them and accepted no reader artifact. The additional
all-model checks below distinguish this reader failure from basic transport
capability; no prompt-only exception was added.

### All-model native tool checks (2026-09-30)

At the configured TokenProxy endpoint, all **16 basic native-tool probes passed**:
four model IDs, streaming on/off, and automatic/explicit first `read_file` choice.
Each invocation executed one successful scoped read of `evidence/pilot.md`,
produced a matching byte hash and full-file coverage receipt, and completed the
tool-result follow-up. The simple prompt supplied the expected final answer;
this checks transport and execution, not independent factual reasoning.

The actual `tokenproxy-read-only.yml` blueprint was then run with each model
routed to its balanced reader, retaining its prose, schema, source checks,
required full-file read, explicit initial tool choice, and two-attempt budget.
Only the selected model and streaming setting changed:

| Model | Basic probe | Reader: streaming | Reader: non-streaming |
| --- | --- | --- | --- |
| qwen36-35b-a3b | 4/4 passed | Blocked; no native read | Blocked; no native read |
| ornith-1.5-35b | 4/4 passed | Blocked; source-ID/quote checks | Completed on second attempt |
| deepseek-v4-flash | 4/4 passed | Blocked; quote/invented-ID checks | Blocked; quote/invented-ID checks |
| nemotron-3.5-lightning | 4/4 passed | Blocked; quote/schema checks | Completed on first attempt |

Every reader attempt for Ornith, DeepSeek and Nemotron performed a successful
full-file read with the expected hash. Those blocked runs failed output
admission, not tool transport. Qwen performed no native read in either reader
run; it returned unsupported descriptions despite receiving `read_file` and
explicit `tool_choice`. Receipts are retained locally in ignored directories
`runs/tool-matrix-20260930-211224-{qwen,ornith,deepseek,nemotron}-{stream,json}`.
One run per setting is not a reliability benchmark.

For a historical control, the pre-extraction Echelon adapter at commit
`7a63e727285d4ba52397c5b46d75f9d657158762` was loaded without changing the checkout.
Its advertised and executable tools were restricted to `read_file`, with the
same evidence scope. With Qwen, the identical rendered reader prompt and
automatic tool choice also returned text without a native call. Current Runtime
reproduced that behavior with both automatic and explicit choice. The diagnostic
observed the outgoing tool declaration and parsed endpoint completion directly;
the Harness was not discarding successful calls. This does not reproduce every
historical Echelon prompt/configuration, but this failing request is not unique
to the extracted adapter. Its endpoint/model/prompt interaction remains to be
isolated, potentially against another endpoint.

These live results used the companion Runtime changes now released in v0.3.0.
The pre-release v0.2.0 dependency environment passed 63 tests with two strong-read
integration skips. Harness 0.2.0 pins Runtime v0.3.0 and those integration tests
no longer skip for missing Runtime capabilities. Missing capability is separately
tested as a pre-dispatch error. Setup details and remaining guarantees are in
[hardening.md](hardening.md).

The following sections describe the original v0.1 verification, not a guarantee
that its live tool result still reproduces with the hardened prompts/endpoint.

Local verification on 2026-09-30 covered controller behavior and real Prosaic
inspection plus Prosaic Runtime HTTP/tool transport against deterministic local
responses. The review integration test exercises all four configured model IDs,
an actual repair edge, and human rejection without another model call. The read
example test executes read_file and saves its successful event in a receipt.

The documented isolated-environment installation was executed locally with
Prosaic revision 0f7e187 and immutable Prosaic Runtime v0.2.0. Wheel and source
builds were checked. The example definitions were validated through Prosaic.

## Live TokenProxy checks

After the network became reachable, discovery passed at
http://10.16.81.27:8080/v1 using credentials from TOKENPROXY_KEY. The final review
workflow accepted one schema-valid output from each tier:

| Step | Model | Result |
| --- | --- | --- |
| brief | ornith-1.5-35b | Accepted brief |
| draft | qwen36-35b-a3b | Accepted decision proposal |
| review | deepseek-v4-flash | Accepted approved verdict |
| decision | nemotron-3.5-lightning | Accepted final proposal |

The run paused after four calls. A sample `reject` choice finalized it as rejected
without another model call. This tests the human-resolution branch, not acceptance
of the fictional launch proposal. A prior live run exercised a repair edge and
schema retry, then correctly blocked at three draft visits after eight calls.

The final read-only workflow initially rejected a response without a successful
read_file event. On its second invocation, Qwen executed read_file successfully,
returned the actual 120-request pilot observations, and completed the workflow.
The standard Prosaic Runtime smoke test also passed both no-tool and tool probes.

Semantic limitations remain: the reviewer accepted a draft with an overbroad
description of checklist completeness as factual accuracy and a questionable
interpretation of the 99% reliability headline. The reader reassigned some source
IDs incorrectly. Schema and tool-event admission do not verify these claims.
Human review remains useful even after the model review gate passes.

Earlier connection timeouts were recorded as failed attempts and did not advance
the graph. No token, authorization header, or input from unrelated repositories
was saved in tracked files. Local run evidence is ignored.

Reproduce a live workflow with:

```sh
export PATH="$PWD/.venv/bin:$PATH"
export TOKENPROXY_KEY
.venv/bin/prosaic-harness run examples/tokenproxy-review.yml \
  --checks examples/checks.py --input examples/request.json --run-dir runs/live-review-new
.venv/bin/prosaic-harness resume examples/tokenproxy-review.yml \
  --checks examples/checks.py --run-dir runs/live-review-new --choice approve
```

Use a new directory for each new run. Limit-exhausted runs retain their original
budgets. Offline suite: 25 tests; wheel and source builds passed locally. CI
checks the same suite and build on Python 3.11, 3.12, and 3.13.
