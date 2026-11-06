# Harness 0.9.10 — visible conversation input caps

Adds two read-only properties on admitted `ConversationBindings`:
`effective_max_input_bytes` for ordinary requests and
`effective_interpretation_max_input_bytes` for a registered interpreter (`None`
without one). Each reports the smaller of the conversation cap and that phase's
run cap. Explicit tighter ordinary and interpretation caps remain supported.

The [input-cap guide](conversations.md#input-request-caps) shows both defaults,
configuring a shared value for new sessions and handling explicit
`contextLimit` / `maxInputBytes` errors. The byte cap includes the encoded
request and history; it is independent of the provider's token window.

Binding identity material, policy defaults, admission/error behavior, session
schemas, immutable receipts and pending-call recovery remain unchanged. No
limits are raised automatically. Session policy migration is out of scope;
existing sessions continue using their original admitted bindings.

Dependencies stay Core 0.5.0 and Runtime 0.9.14. PostgreSQL store 0.4.1 remains an
unchanged qualification witness; this release publishes only
`b3-prosaic-harness==0.9.10` to the package index.

Qualify the final source through the complete ordinary CI matrix before merge.
Then qualify the version tag through Publish SDK on Linux AMD64/ARM64 and macOS,
Python 3.11–3.13, PostgreSQL 16/18, installed wheels and minimum dependencies.
Promotion must consume the successful exact-source candidate's original bytes;
verify public index and GitHub downloads and fresh installed cap regressions
before reporting completion. Preserve previous tags/releases and unrelated edits.
