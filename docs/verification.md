# Verification

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
  --input examples/request.json --run-dir runs/live-review-new
.venv/bin/prosaic-harness resume examples/tokenproxy-review.yml \
  --run-dir runs/live-review-new --choice approve
```

Use a new directory for each new run. Limit-exhausted runs retain their original
budgets. Offline suite: 25 tests; wheel and source builds passed locally. CI
checks the same suite and build on Python 3.11, 3.12, and 3.13.
