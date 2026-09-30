# Changelog

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
