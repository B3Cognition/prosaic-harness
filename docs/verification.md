# Verification

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
