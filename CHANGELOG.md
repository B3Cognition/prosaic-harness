# Changelog

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
