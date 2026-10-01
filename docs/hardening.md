# Hardening contracts and setup

## Prompt injection

The first adversarial boundary pass is in `tests/test_prompt_injection.py`.
These six tests simulate a model following malicious evidence or claimed
operator instructions. Forged controller fields fail schema admission; valid
model approval does not satisfy a human pause; builtin write grants are rejected;
the real Runtime/Prosaic path denies evidence-induced writes to run state.

This is containment testing, not proof that arbitrary prose is trustworthy.
Custom tools and `--checks` still execute trusted host code. Their filesystem and
network permissions require separate OS isolation. Schema-valid semantic poison
needs domain/provenance checks and human review. See the companion Runtime
[audit and threat model](https://github.com/B3Cognition/prosaic-runtime/blob/main/docs/security.md)
included with Runtime v0.5.1.

The harness owns state and admission; models supply data, not controller policy.
No Echelon imports, delivery gates or shell execution were added.

## Trusted checks

Register `Validator(version, callable)` through `Harness(..., validators={...})`.
The callable receives `(output, CheckContext)` and returns issue strings in a
list, empty on success. Agent `validators: [name]` run after schema/tool checks;
failures get bounded model repair. Validator exceptions block, never pass.
`kind: check` uses `from`, `validators`, `pass`, `fail` to check an existing
artifact without a model call. YAML names checks but cannot import or run code.

CLI `--checks examples/checks.py` explicitly executes a trusted local Python file
exporting CHECKS; its content hash supplies validator versions. This is not a
sandbox: never load untrusted/model-generated code. Python embeddings must change
their explicit validator version whenever policy/dependencies change. Imported
dependencies and closure state are not automatically fingerprinted.

The Harbor blueprint checks source membership, exact supporting quotes, and
supplied numeric calculations. These domain rules stay in `examples/checks.py`.
A quote does not prove a paraphrase follows from it. Free-text truth, missing
claims and causal interpretation still need semantic/human review. The opt-in
reviewer probe tests two known-bad drafts, not general model reliability.

## Artifact and evidence binding

`outputs` retains latest accepted values. `bindings` records invocation IDs,
digests and required input versions. A revisit creates a new version even for
identical text. Gates, checks and required inputs reject stale dependencies;
`requires` on pause/finish requires fresh artifacts. Optional inputs deliberately
allow old review feedback for repair and are not approval dependencies.

The review example independently reviews the actual final decision, then runs a
deterministic final check. Its pause and finish require fresh decision and final
review artifacts. Human choices bind to the pause's artifact snapshot.

Top-level `evidence: [evidence/pilot.md]` snapshots declared UTF-8 files and their
SHA-256 hashes: at most 64 files, 64 KiB each, 128 KiB total. Files are rechecked
before steps, result admission and resume. Undeclared files do not receive
whole-run immutability guarantees. Explicitly declared evidence may be sensitive.

`require_reads` requires successful read_file receipts covering every line of
the declared file's exact bytes. Wrong paths/hashes and partial reads fail. The
runtime requests that tool on the first turn within host/prose/runtime grants;
an endpoint ignoring it cannot pass admission. Required-read files are supplied
as source hashes, not pre-read text. Read ranges can combine within an invocation.
This proves bytes reached the model, not that its interpretation is correct.

Optional `acquisition` sends its own inspected Prosaic artifact before the full
assignment. Its digest is sealed with the workflow. Both phases share Runtime's
model, conversation, tool/byte limits and deadline. Runtime requires one explicit
granted initial tool; missing/substituted/extra calls block without execution,
failed tool results block before analysis. These transport failures do not enter
output repair. Successful acquisition still needs complete matching-byte read
receipts and final schema/source checks. No automatic preloading fallback exists.
See the [released setup and two blueprints](../examples/README.md#staged-acquisition-and-no-tool-preloading).
Harness v0.3.0 pins Runtime v0.4.0 with `acquisition_v1`; older Runtime overrides
without it are rejected before dispatch. Preloading uses the controller snapshots and needs no new
Runtime capability or tools. Tool-free outputs never satisfy native-read requirements.

## Recovery, storage and budgets

Harness v0.3.0 rechecks budgets, cancellation and the run deadline
immediately after recording completed usage and before admitting output. A
response cannot become accepted merely because it arrived before the next-step
guard. The updated companion Runtime also distinguishes missing/invalid usage
from a genuine reported zero across every HTTP/SSE turn. These fixes are included
in the pinned Runtime v0.4.0; no development override is needed.

State format is version 2: old runs must start afresh. State/receipts use content
checksums, identity/ledger/output binding checks, bounded strict JSON, and reject
duplicate keys/nonfinite values. Resume checks completed receipts and the pending
call. A saved pending receipt is adopted without another call. Unknown completion
still requires `--retry-interrupted`, consumes a call slot and retains unknown
usage. Hashes detect corruption/inconsistency, not a malicious actor recomputing
all files. Local storage remains trusted.

Storage uses pinned directory descriptors, rejects symlinks/nonregular files,
and atomically replaces and fsyncs file/directory contents. New directories and
files use private permissions; existing permissions are not silently changed.
Checkpoints/receipts are bounded at 8 MiB. History has sequence numbers and
timestamps. Receipts retain bounded structural events; token deltas are not
duplicated alongside raw stdout. Events lost before receipt creation cannot
establish a completed call.

Optional `limits.max_tokens` counts all reported usage, including failed attempts.
Unknown usage blocks under a finite budget. Accounting is retrospective: one call
can overshoot; no monetary guarantee is made. Optional `max_run_s` persists an
absolute deadline, includes human waiting and reduces invocation timeouts. It
assumes a trustworthy system clock. `Harness(..., cancelled=callable)` cooperates
with Runtime cancellation. Runtime timeouts/failures and validator bugs block
with distinct reasons; only output contract failures get automatic bounded repair.
Model calls and their tool activity have no exactly-once guarantee.

## Coordinated Runtime dependency

Harness 0.4.1 pins the immutable Runtime v0.5.1 revision, including
`read_receipts_v1`, `initial_tool_v1`, `initial_tool_enforcement_v1` and
`acquisition_v1`. A missing required capability fails before
model dispatch. Normal installation needs no sibling checkout. For development
against unreleased Runtime changes, explicitly install the sibling checkout:

```sh
.venv/bin/python -m pip install --no-deps -e ../prosaic-runtime
# For a uv-managed venv without pip:
uv pip install --python .venv/bin/python --no-deps -e ../prosaic-runtime
```

For coordinated releases, publish Runtime first, replace Harness's dependency
pin with that available immutable revision, and verify in a clean environment.

The pinned companion Runtime rejects omitted/substituted
explicit first-tool selections itself. Harness preserves `tool_choice_not_honored`
as a durable block reason, without automatic retry. Neither behavior requires
the optional development Runtime override.
