# Safe tool events and captured citations

This opt-in contract requires Runtime 0.9.20,
Harness 0.9.14, and Harness PostgreSQL 0.4.3 when using PostgreSQL.
See the versioned release notes for publication and migration details.

Runtime owns `ToolResultV1`, producer declarations, safe scalar event projections,
actual HTTP delivery evidence and final-answer citation validation. Harness owns
host bindings, context-pack permission adapters and durable receipt adoption.
Citations prove captured provenance; they do not establish semantic entailment.

Pass `ToolContracts` to `WorkflowBindings`, `Workflow.load`, or
`ConversationBindings`. Register typed outputs with a `ToolResultContractV1`.
Existing dictionaries retain their existing framing. Events alone can be enabled
without changing callback return types. An explicit `ToolEventPolicyV1` selects
argument/result scalars, and a separate `ToolDisplayAuthorizerV1` grants display.
No argument/result body is added to general telemetry. Treat live events as
provisional; completion and delivery authority come from the private receipt.

Bind an `EvidenceAuthorizerV1` and `CitationPolicyV1` to request checked answers.
The model uses `[cite:ev_…]` or an eligible selected `[cite:ctx_…]` reference.
Only exact selected inline content or an actual deferred read can be cited.
Index descriptions and private neighboring fields confer no citation authority.
Use `ContextPackReader(tool_contracts=True)` for the typed reader contract.
Both the generic evidence grant and pack invocation/citation grants must allow use.
Guards retain complete private facts independently of selected model context.
Checked answers are withheld until ordinary guards and citations accept them;
existing explicitly configured retry allowances apply, and authorization denial
cannot be repaired through additional model requests.

Enabled workflows use state v4 / invocation receipt v3. Enabled conversations
use session v4 / receipt v4, Runtime prepared input v4 and evidence v3. When the
feature is absent, existing descriptors, identities, record versions and return
values remain on their old paths. Internal conversation interpretation remains
separately classified and does not inherit ordinary-agent evidence authority.
Unknown delivery after a crash remains fenced; saved receipts are adopted before
considering new work, without repeating tools, providers or Runtime guards.

Provision a new file/memory/PostgreSQL namespace explicitly with
`initialize(tool_contracts=True)`. For existing namespaces, drain writers and call
`migrate_tool_contract_storage()` as the namespace/schema owner. PostgreSQL uses
the existing JSON tables and an explicit version marker update. Worker startup
and readiness never create or migrate storage. Older readers refuse the new marker.
These are namespace transitions; existing sessions and receipts are not rewritten.

`Conversation.retain_citation(session_id, invocation_id, evidence_id)` produces a
host-owned `RetainedCitationReference` from an adopted stored receipt. Pass a tuple
of these to `send(..., retained_evidence=(reference,))` to import captured content
explicitly. The new turn receives a fresh ID and must actually submit it to the
provider under current permission. IDs copied into text/history grant nothing.
No JSON constructor turns arbitrary model data into a retained reference.

`Conversation.citation_view(...)`, or `resolve_citation_view` with a
`VerifiedToolReceipt` and `ToolContractViewBindings`, rechecks current retained-read
permission and returns captured content without fetching a locator or URL.
Revocation hides a source while leaving the original accepted answer unchanged.
`project_retained_tool_event` separately rechecks the current display grant.
Retained reference chains are bounded to 16 owned receipts and depth 8; unavailable,
denied and unknown sources have the same unavailable view shape.

All existing turn, event, JSON, registry and receipt limits still apply. Imported
contexts are host attestations of captured content; only the Runtime transport
can establish its delivery in the new turn. Automatic citations are supported by
API surfaces with actual delivery evidence. Native/Unified and external structured
execution refuse unsupported automatic citation combinations before dispatch.
Parallel tool execution, MCP clients and sub-agent orchestration remain separate
follow-ups in [Cerebro requests](cerebro-requests.md).

This release also applies current `retainedRead` grants before
returning generic tool history, and current `modelUse` grants before submitting
its actually retained historical turns. Context omitted by fitting is not
authorized or submitted. A denied reuse becomes a durable no-effect
`evidenceUseDenied` receipt before dispatch; accepted earlier answers remain intact.
