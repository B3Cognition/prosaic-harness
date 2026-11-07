# Versioned cross-step review — V1

Current published release: **0.9.11**. See [release notes and compatible SDK versions](../../docs/releases.md).

The wheel supplies the Harness APIs; the blueprint files ship in the source
archive and the [immutable v0.9.11 source tag](https://github.com/B3Cognition/prosaic-harness/tree/v0.9.11/examples/revision-review).
Obtain the source archive with `python -m pip download --no-deps --no-binary=:all: b3-prosaic-harness==0.9.11`,
verify it against the GitHub release's SHA256SUMS, and extract
`b3_prosaic_harness-0.9.11/examples/revision-review`. Copy that directory into
the consuming application before tailoring its policy.
It uses the existing public `Validator`, `CheckContext`, `Workflow` and `Harness`
APIs. No enforcement tags or copied Runtime engines are involved.

The trusted host supplies `request.insights`: a list of unique stable `id` and
`text` pairs. `first_review` returns findings (`insight_id`, `text`); `revision`
returns the complete revised insight list. The `revised_review` step declares
both as required `inputs` and applies the trusted `review_scope` validator.

A final finding is allowed only when its ID is present in the revision and was
flagged in the first review or its text is new/different from the original host
input. Whitespace/text changes count as changes in this deliberately simple
application policy. Metadata changes and model-supplied `changed_ids` do not.
Removed IDs, unknown IDs, malformed dependencies and duplicate IDs refuse.
Cerebro can replace this predicate with its authoritative structured diff; the
SDK supplies facts and enforces the verdict, not the meaning of an insight.

`CheckContext.artifacts` supplies earlier accepted outputs. Required workflow
`inputs` additionally bind their receipts and enforce freshness. Do not replace
those declarations with optional inputs or model-claimed provenance. Original
host inputs and accepted step outputs remain owned by Harness. Validators must
be deterministic and should not mutate their private input copies.

`checks.validators()` creates public `Validator` registrations with the semantic
V1 label plus SHA256 of the actual checks file. This version is persisted in the
run checkpoint; editing the check refuses old-run resume. Keep the copied file
and registration stable throughout a run. The workflow uses two final-review
attempts and four total calls: one unrelated finding can be repaired. Exhaustion
blocks before accepting it. Interrupted/pending provider calls are not permission
to retry automatically; use Harness's existing explicit recovery.

The default config is inert loopback, tools are disabled and all data is synthetic.
Tests execute the real Core/Runtime/Harness chain against a local fixture, including
refusal, feedback/correction, exhaustion, stale dependencies, version mismatch and
resume without duplicate requests. This is not live-provider certification.

To run a copied blueprint after configuring its endpoint/model and credentials:

```sh
python run.py --live --run-dir /a/private/new-run-directory --request request.json
```

`--live` explicitly authorizes model calls; it is never used by the synthetic tests.
The run stops for human acceptance. Continue with the same workflow and
`checks.validators()` registration using `Harness.resume(choice='accept')` or
`choice='reject'`. No external publishing or tool effect occurs in this blueprint.
Never commit run directories, endpoint secrets or real user input/output.

V2 will add Runtime enforcement-tag admission inside workflow agent steps while
retaining this versioned validator API and explicit dependency facts. Other
[Cerebro requests](../../docs/cerebro-requests.md) are tracked separately.
