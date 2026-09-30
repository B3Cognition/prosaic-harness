# Working on Prosaic Harness

This repository is generic infrastructure. Keep product-specific prose, gates,
Git operations, and publication rules in consuming applications or blueprints.
No imports from Echelon. Prosaic parses prose; Prosaic Runtime owns model calls.

The harness is the sole writer of run state. Preserve pending-call recovery,
schema admission before advancement, bounded loops, and explicit human choices.
Do not add automatic retries for interrupted requests without acknowledging the
possibility that the endpoint already completed the request.

Use `.venv/bin/python -m pytest` and `.venv/bin/python -m build`.
Prosaic must be on PATH for transport/inspection integration tests. Tests use a
local HTTP server and synthetic inputs; live examples require explicit opt-in.
Run directories may contain private data and must stay ignored. Never commit keys.

New neutral prose should use paired ALWAYS/NEVER behavioral rules. Model IDs and
endpoint credentials belong in runtime configuration, not agent Markdown.
