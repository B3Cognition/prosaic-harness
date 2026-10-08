# Changelog

## Unreleased

## 0.6.0 — 2026-10-08

- Add optional customer accounting context with backward-compatible `default`
  attribution, frozen identity and recorder scope across workflow retry and resume,
  and validated per-invocation lineage.
- Pin immutable Runtime 0.6.0 for per-provider-call token metering and optional
  durable accounting. Unknown historical usage remains unknown; this release
  does not implement invoice charges or billing-platform export.
- Add RunStore and the separately distributed PostgreSQL adapter 0.1.0 for
  leased, cross-worker durable workflow execution, recovery and explicit
  database setup. Filesystem storage and database-free core remain supported.

## 0.5.0 — 2026-10-07

- Add schema-validated human responses at durable workflow pauses, trusted
  validators and retained feedback for downstream agents and checks.
- Pin Runtime 0.5.3 and Python Prosaic 0.3.1.

## 0.4.2 — 2026-10-07

- Pin the immutable Runtime 0.5.2 release, combining structured JSON tool
  transport and optional CLI OS sandboxing without a sibling dependency override.
- Bind non-default CLI sandbox configuration to workflow identity and verify
  exact adapter policy/capability before execution and resume. Default-off
  fingerprints remain compatible; policy changes invalidate approvals.
- Offline CLI sandbox preflight, complete sandboxed analyzer blueprint,
  installation/grant guidance and matching-version native tool admission.
- Workflow routing, validators, checkpoint format and explicit human choices
  remain unchanged; no automatic native-to-structured transport fallback.

## 0.4.1 — 2026-10-01

- Pin Runtime 0.5.1 and Python Prosaic 0.3.0; remove Node/npm installation needs.

## 0.4.0 — 2026-10-01

- Pin the immutable Runtime v0.5.0 release for host callbacks and manifest-defined
  CLI tools; no sibling Runtime override is needed after normal installation.
- Workflow load checks declared CLI availability and permissions offline. Required
  tool events retain matching-version admission and descriptor-bound resume identity.
- Runnable CLI-analysis workflow: install executable → discover → preflight → native
  execution → closed-schema report → explicit human choice, with synthetic evidence.
- Staged tool-acquisition walkthrough and executable example verification.
- Release verification: 107 tests pass, including the installed CLI workflow's
  native execution, report admission and no-inference human-choice resume.

- Python-embedded host custom-tool registry, versioned required-tool admission,
  capability/descriptor preflight and optional descriptor-bound workflow identity.
  No-custom fingerprints and checkpoint v2 are unchanged; builtin writes stay denied.
- Self-contained synthetic catalogue example: native lookup → closed-schema and
  deterministic record checks → bound human choice → finish without external effects.

## 0.3.0 — 2026-10-01

- Pin the immutable Runtime v0.4.0 release: acquisition, strict initial-tool
  enforcement, accurate unknown usage, input bounds, redirect rejection and
  bounded inspection timeouts work without a sibling development override.

- Larger synthetic three-document incident blueprints: staged independent
  file fragments or no-tool preloading, synthesis, independent review, bounded
  repair and human approval. Embedding example accepts an explicit Runtime
  config override and preserves its fingerprint on resume.

- Recheck usage budgets, cancellation and deadlines before admitting a result,
  not only before executing the next graph step.

- Optional acquisition prose on agent steps, sealed in workflow fingerprints;
  requires read requirements and Runtime `acquisition_v1` before dispatch.
  Failed acquisition is a durable block without repair/fallback. Shared Runtime
  invocation retains the existing budgets and final output admission checks.
- Staged native reading and explicit tool-free preloaded evidence blueprints,
  step-by-step setup, and an opt-in all-profile HTTP/SSE live comparison program.

- Preserve `tool_choice_not_honored` as a durable block reason when supplied by
  an updated Runtime. No model output is admitted and no automatic retry occurs.

## 0.2.0 — 2026-09-30

- Artifact-bound approval, immutable declared evidence, final-output model review
  and deterministic checks; generic trusted validation registry and CLI opt-in.
- Source/quote/calculation example checks and adversarial reviewer probe.
- Checkpoint v2 contracts, sealed receipts, ledger checks, bounded strict JSON,
  symlink-safe descriptor-pinned storage and timestamped controller history.
- Cumulative token budgets, persisted whole-run deadlines and cancellation.
- Strong required reads use the immutable Prosaic Runtime 0.3.0 pin for path,
  byte-hash and complete-file coverage receipts plus initial-tool requests.
- Breaking change: checkpoint format is version 2; start old runs afresh.
- All-model live checks distinguish tool transport from schema/source admission;
  tool success alone does not establish answer correctness.

## 0.1.0

- Generic YAML agent, gate, pause, and finish workflows around Prosaic Runtime v0.2.0.
- JSON Schema admission, bounded validation retries, explicit input artifacts,
  deterministic branching, and bounded review/repair loops.
- Optional successful-tool evidence requirements before admitting an agent result.
- Local atomic checkpoints, process locking, invocation receipts, explicit
  interrupted-call retry, and immutable-definition checks on resume.
- CLI validation/run/resume/status, streaming JSONL and stderr progress, Python API.
- Single-agent, four-tier review, read-only evidence, and embedding examples.
- Apache-2.0; Python 3.11+ on Linux and macOS (Windows through WSL).
