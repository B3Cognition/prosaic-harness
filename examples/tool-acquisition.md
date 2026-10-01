# Problem and resolution: read evidence before producing a structured answer

Use staged acquisition when a required native read competes with a detailed
final-answer contract. This example compares two existing runnable workflows:
[direct read](read-only.yml) and [staged read](staged-read.yml). Both use the
same [analysis prose](.prosaic/subagents/evidence-reader.md), synthetic
[evidence](evidence/pilot.md), [schema](schemas/brief.json), and
[source/quote checks](checks.py). Neither can approve or publish anything.

## Problem: an answer arrives without the required read

The direct workflow supplies the complete assignment at once: call `read_file`,
then produce a detailed JSON brief. It explicitly requires that first native
call and a hash-bound, complete-file receipt. Some endpoint/model combinations
still return a JSON answer describing the unread file instead of calling the
tool. Merely writing that the file should be read is not tool execution.

Harness must block this response with `tool_choice_not_honored`, not accept it
as evidence or silently supply the missing file. Direct mode is not universally
broken: compliant endpoints can complete it, and the offline tests cover both
successful direct execution and rejection of a missing call.

On TokenProxy/Qwen (`qwen36-35b-a3b`, 2026-10-01), controlled first-turn probes
reproduced the failure twice with streaming and twice without streaming. Both
named and `required` tool choice failed to enforce a native call. Removing the
detailed output contract or using acquisition-only prose produced native calls
in both repeats. Raw responses confirmed that the call was absent, not lost by
the stream decoder. These small observations are not a reliability benchmark
or proof that every local model behaves this way. Whether the proxy or inference
backend fails to enforce tool choice needs server-side investigation.

## Resolution: acquire first, introduce the answer contract second

The staged workflow adds this field to the evidence step:

```yaml
acquisition: subagents/evidence-acquisition.md
```

Its [acquisition prose](.prosaic/subagents/evidence-acquisition.md) is deliberately
narrow: call `read_file` for `evidence/pilot.md`, read the whole file, and never
substitute a description or guessed contents. It contains no final JSON schema.
Keep the evidence path in acquisition prose: final caller arguments are withheld
until acquisition succeeds. For another file, change the prose and the workflow's
declared evidence/scope together.

One Runtime invocation owns this sequence:

```text
acquisition-only prose → successful scoped native read → analysis prose + arguments + JSON contract → admitted brief
```

The tool result remains in the conversation before analysis. The final output
must still pass JSON Schema and source/quote checks. The workflow retains
`tools`, `read_roots`, `require_tools`, and `require_reads`; staging does not
weaken permissions or receipts. Both phases share the invocation's timeout,
usage and tool budget. Failed acquisition blocks without automatic retry or
fallback. This phase separation passed the observed live trial but cannot
guarantee that every endpoint will make the acquisition call.

## Run the comparison

Install Harness and Runtime using the [first-run guide](../README.md). Runtime
must expose `acquisition_v1`, and `prosaic` must be on PATH. To test Python
Prosaic, prepend the directory containing its installed executable before the
Harness environment's bin directory. Do not replace a global installation.

Run from the Harness repository root. The following commands make real model
requests using only synthetic examples and may incur provider charges. Load
`TOKENPROXY_KEY` into the environment without displaying it; the supplied config
selects profiles by tier. For your own endpoint, replace the config argument
with a configured copy of `examples/runtime.yml`. Use fresh run directories
each time; never delete or edit a blocked run to make it pass.

```sh
export PATH="$PWD/.venv/bin:$PATH"
# Optional: select an installed Python Prosaic explicitly:
# export PATH="/path/to/prosaic-py/.wheel-test/bin:$PATH"
export TOKENPROXY_KEY  # after loading it from your shell configuration

.venv/bin/python examples/run_workflow.py examples/read-only.yml \
  --config examples/tokenproxy.yml --checks examples/checks.py \
  --input examples/read-request.json --run-dir runs/direct-read-first
.venv/bin/prosaic-harness status --run-dir runs/direct-read-first --json

.venv/bin/python examples/run_workflow.py examples/staged-read.yml \
  --config examples/tokenproxy.yml --checks examples/checks.py \
  --input examples/read-request.json --run-dir runs/staged-read-first
.venv/bin/prosaic-harness status --run-dir runs/staged-read-first --json
```

These workflows declare `balanced`, selecting Qwen in the supplied config.
The direct case may complete or block; do not force a failure for demonstration.
For a staged success, inspect `run.json` and its `attempts/*.json` receipts:

- State is `completed`; a clean run has one Harness invocation, with two model
  turns rather than two workflow agents.
- A successful `tool_completed` event for `read_file` precedes
  `acquisition_completed`. Its read receipt identifies `evidence/pilot.md`,
  matches the evidence byte hash, starts at offset zero, and covers all lines.
- The admitted brief satisfies the schema and source/quote validator. A receipt
  proves bytes were acquired, not that every interpretation is correct.

## Deterministic assertions without live inference

```sh
export PATH="$PWD/.venv/bin:$PATH"
# Prepend the Python Prosaic bin directory here when testing the migration.
.venv/bin/python -m pytest -q tests/test_tool_acquisition_example.py
```

These tests use real Prosaic inspection, Runtime, and Harness with a local
synthetic HTTP server. They assert that a direct answer without a tool blocks
with no accepted output; staged phase one contains neither final arguments nor
the answer contract; phase two follows the tool result and contains the final
assignment; and the full-file/hash receipt and acquisition event precede
successful admission. They verify wiring and guards, not model compliance.

For model-independent acquisition, explicitly choose
[controller preloading](preloaded-evidence.yml). It provides immutable source
text without native tools; it is a different mode, not an automatic fallback
from failed native acquisition.
