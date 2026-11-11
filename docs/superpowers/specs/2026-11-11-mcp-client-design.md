# MCP client across Runtime, Harness and Lab

Design for review, 2026-11-11. Baseline is Runtime 0.9.21, Harness 0.9.15,
Harness PostgreSQL 0.4.4 and Lab 0.9.14. This proposal records engineering
choices for the first increment. Implementation and release require their own
instructions.

## User-facing contract

A service owner registers an MCP endpoint, chooses individual read tools,
assigns stable local aliases and supplies authorization for the current caller.
A Harness workflow node selects those aliases in its existing `tools` list.
An ordinary conversation can use the same registry under its existing
`RunPolicy`. The model sees a bounded tool schema and a host-written
description. It returns arguments through the usual provider tool call, and
the Runtime tool loop owns execution, budgets, guards, progress and citations.

Use an optional `b3-prosaic-runtime[mcp]` extra with official Python SDK
`mcp>=2.3.0,<3`. Qualify the floor and the resolved SDK version. Support
Streamable HTTP in explicit `2026-07-28` and `2025-11-25` profiles, including
JSON and request-scoped SSE responses. The modern profile pins the protocol
directly. The legacy profile negotiates with the legacy handshake and requires
the exact configured version. Other versions fail closed. Host-managed
MCP-resource bearer tokens cover service-owned deployments. Interactive OAuth,
authorization discovery, stdio launch, legacy HTTP+SSE, subscriptions,
resources, prompts, extensions, tasks, sampling, roots and elicitation are
outside this increment. Sub-agents remain a separate follow-up.

Support Runtime API `run`, `turn` and prepared turns through the
OpenAI-compatible Chat Completions and Anthropic Messages loops, including
provider streaming. Harness supports ordinary conversations and agent nodes
in YAML and native JSON workflows. MCP calls are serial barriers even in a
parallel tool batch. Reject selected MCP tools in direct `run_tool`,
`StructuredToolLoop`, native CLI providers, explicit initial-tool calls,
Harness direct tool nodes and interpretation or acquisition. Keep existing
admission paths for registries without selected MCP aliases.

A separate agent/tool loop or a generic gateway would require a second
authority and recovery model. Using generated `CustomTool` values keeps those
decisions in Runtime. The wire client stays in an optional module so the base
install and Harness import surface remain small. Listing before each actual
call adds one bounded round trip on a single-page modern server. It catches
schema drift and supplies the SDK's current header metadata without enabling
automatic resend.

## Host API and catalogue

New public module `prosaic_runtime.mcp`. Imports remain usable without the
extra. Report dependency unavailability on client entry or an explicit
capability check. Expose `mcp_client_v1` as interface support on Runtime.
Lab checks dependency availability separately.

- `McpServerV1(server_id, revision, endpoint, protocol_version, *, auth_mode="bearer", allow_loopback_http=False)` is immutable. Server IDs and revisions are bounded host references. `auth_mode` accepts `bearer` and `none`. The endpoint is a single canonical HTTPS URL with a path. Reject credentials in URLs, query strings, fragments, redirects and ambient proxy settings. An explicit fixture flag admits HTTP only to literal loopback IPs with `auth_mode="none"`. Private services use a trusted HTTPS route. The host owns deployment egress and DNS policy for that route.
- `McpClientV1(server, *, allow_destination, credentials, scope_key, authorize, limits=None)` is a synchronous context manager. `allow_destination(endpoint) -> bool` approves the exact configured route for discovery and execution. `credentials(server_id, access_scope) -> str | None` returns a bounded bearer token already issued for this MCP resource. `scope_key(context) -> str` derives an opaque authorization-domain ID from trusted invocation context. `authorize(alias, arguments, context) -> bool` checks current host permission before journal lookup or new network work. Require literal `True` for grants. Denials and callback exceptions produce fixed sanitized outcomes. The credential callback is unused for `auth_mode="none"`.
- `client.discover(*, access_scope: str) -> McpCatalogV1` explicitly performs bounded discovery. The modern profile uses `tools/list` on a pinned modern client. The legacy profile verifies negotiation before listing. Walk all pages with cache bypass, unique tool names and no repeated cursors. Scope catalogues to server revision, canonical endpoint, protocol profile, auth mode and access scope. A shared authorization-domain ID is valid only when the host has established equivalent server visibility and grants.
- `McpCatalogV1.to_dict()` exports a bounded versioned private catalogue with
  a server/scope digest and canonical name/schema records. The host persists
  this document and its approved SHA-256 in trusted configuration or owned
  storage. `client.restore_catalog(document, *, access_scope, expected_sha256)
  -> McpCatalogV1` verifies canonical hash, configured server and scope, all
  limits and record structure without importing the SDK or contacting the
  endpoint. It carries no endpoint, token, raw access scope or remote prose.
  A new process can restore the catalogue and rebuild identical bindings
  before opening a client. Use this path for offline adoption and views.
- `McpToolSpecV1(alias, remote_name, description, binding_version, result_mode, projector, result_contract, *, read_only, argument_schema=None, event_policy=None)` binds one discovered tool. The host must supply literal `read_only=True` for a reviewed tool. Require `result_mode` of `structured` or `text`. `projector(data, context) -> ToolResultV1` runs on the Runtime owner and must be pure. It selects the permitted data and can supply host-defined evidence declarations. `result_contract` and optional `event_policy` reuse the existing typed result and display contracts. Change `binding_version` when the projector or host authorization semantics change.
- `client.bind_tools(catalog, specs, *, existing=None) -> dict[str, CustomTool]` performs pure admission of this explicit selection. Validate the optional existing registry and reject collisions before returning the merged registry. Return exact `CustomTool` instances. A private adapter handler type identifies generated registrations. The existing descriptor `version` is `mcp-v1.<sha256>` over canonical binding identity. Hash server route, revision, protocol and auth mode, access scope, remote name, selected input/output schema, local argument schema, result mode, result and event descriptors, and host binding version. Keep the endpoint, tokens, SDK objects and remote metadata out of the descriptor and provider request. The local alias and host description remain ordinary descriptor fields.

Admit bounded, reference-free Draft 2020-12 object input schemas. Allow
`type`, `properties`, `required`, `additionalProperties` (boolean only),
`items` (single schema), `enum`, `const`, simple numeric bounds and
string/array size bounds, plus harmless title/description annotations.
Reject unsupported validation keywords, alternate dialects, and
`x-mcp-header` anywhere in a selected schema. Use the same bounded validation
profile for remote output schemas when present. A closed remote input schema can
be used directly after stripping remote prose annotations. For an open root,
require a host-authored closed local schema. The actual arguments must pass both
schemas before dispatch. Never coerce, fill defaults or project tool arguments
into arbitrary HTTP headers. Canonical validation-schema changes require readmission,
even if the new schema also accepts the current arguments.

### Workflow authoring example

The host can bind the remote `lookup_dependents` tool under the local alias
`cerebro_dependents`. Set its reviewed description, schema, result projector
and per-caller grant when building the registry. Pass the registry and
`ToolContracts` to `Workflow.load` or `WorkflowBindings`, with an operation
namespace and journal for execution. The node only needs the local alias.

```yaml
steps:
  impact:
    kind: agent
    agent: impact-analyst.md
    tools: [cerebro_dependents]
    next: done
  done:
    kind: finish
    requires: [impact]
```

Use the same alias in an ordinary conversation's `RunPolicy.allowed_tools`.
For a cold start, restore the host-approved snapshot and build the same registry.
Open the client before new MCP dispatch. Existing receipt adoption and captured
citation views can run with the client closed.

## Dispatch, bounds and recovery

Require contextual, nonterminal, journaled registrations with finite
`max_provider_requests` and `max_tool_calls`, an explicit operation namespace
and `ToolContractBindingsV1`. Set `parallel_read=False`. Require a current
scope and grant before journal replay and at entry to new handler work.
Construct `mcp-v1.<sha256>` as the operation key from the canonical JSON pair
of invocation ID and Runtime invocation-wide call index under the existing
journal namespace. Keep the key independent of alias, version and arguments.
The existing signature includes all three and catches any mismatch at the same
slot before another POST. A committed pre-POST failure also stays fixed for
that slot. A separately admitted slot can request the same read under the
existing budgets. Retain the existing Harness policy for new retry
epochs and uncertain effects.

For a newly claimed call, reacquire credentials and list the tools in the same
scoped client that will send the call. Compare the selected descriptor to the
admitted snapshot. Drift or a failed list stops before `tools/call`. A fresh
snapshot and new bindings are explicit host actions. There is no background
refresh or shared SDK response cache. A valid journal replay uses the captured
outcome with current local grants and performs no MCP network work. Changes the
server makes after the last list, or semantic changes that leave schemas and
server revision unchanged, are outside the client's attestation. Host
deployment revision management and server-side authorization remain necessary.

Use the SDK's low-level session call with input-required and claimed results
disabled. Use the SDK listing path that registers header metadata. High-level
SDK retries for multi-round-trip input or header mismatch are incompatible with
the single-dispatch guarantee. A transport guard permits at most one
`tools/call` POST per dispatch attempt, on the admitted route. Disable retries,
redirects, stream resumption and ambient credentials. Refuse standalone GET
streams locally with the protocol's unsupported-method response and allow one
bounded legacy session DELETE during cleanup. Support terminal responses on the
original POST. The transport checks the permit and an invocation-local cancellation flag
immediately before the POST. A lost permit or changed route blocks the send.
A response requiring client input, a protocol mismatch or lost response
does not trigger a second POST.

Use a client-owned AnyIO blocking portal. Trusted grant, scope, credential
and result projection callbacks run on the caller's Runtime owner thread.
The async worker owns SDK I/O and returns bounded data. Each dispatch uses a
fresh HTTP client and protocol session so cookies and auth cannot cross caller
domains. Count active discovery and calls against a client-local cap. A full
client returns a fixed busy failure before the tool POST, without queueing.
Only the owner calls `context.cancelled()`. It signals a worker-safe latch
that shares a fence with the one-POST permit and terminal response handoff.
If a complete SDK result was handed off before that latch won, the owner
projects and validates it and preserves known journal completion before the
Runtime boundary stops follow-up. If the latch wins, cancel and drain the async
task. The one-second cleanup budget bounds graceful transport close, then
force-close local streams and join the task. The budget is not a promise of
handler return time. A future marked cancelled alone is insufficient. Closing
the client atomically rejects new operations and drains active operations
without holding the admission lock. The host
owns bounded synchronous callbacks and service-wide concurrency.

Expose `McpLimitsV1` with the following keyword fields and defaults:
`max_inflight=4`, `discovery_timeout_s=10`, `call_timeout_s=20`,
`cleanup_timeout_s=1`, `max_list_pages=8`, `max_catalog_tools=128`,
`max_catalog_bytes=65536`, `max_schema_bytes=16384`,
`max_argument_bytes=16384`, `max_transport_bytes=131072`,
`max_sse_events=64`, `max_sse_event_bytes=32768`,
and `max_result_bytes=32768`. Require finite positive time values and
positive integer counts and bytes. Allow `max_inflight` from 1 through 16.
Other defaults are hard ceilings and may be narrowed. The call budget includes
listing and is shortened by the Runtime deadline. Enforce decoded transport
limits while streaming, before SDK parsing, for JSON and SSE, including
chunked responses. Require identity content encoding and count both listing
and call responses in the operation cap. Runtime's canonical and provider-wire
limits still apply. Error, cancellation and cleanup code paths retain the
existing journal fencing even if an SDK task requires a bounded cleanup grace.

## Results, events and evidence

For `structured`, take the owned JSON object from `structuredContent`,
validate against the pinned remote output schema when present, and ignore
adjacent content and metadata. For `text`, accept only 1–16 text blocks and
present them to the projector as `{"text": [ ... ]}`, preserving boundaries.
Reject conflicting structured content in text mode. Reject unsupported block
types in text mode. Neither mode follows links, reads resources, forwards raw
errors or interprets the result as instructions. The projector validates or
selects data before returning `ToolResultV1`. The existing result contract
checks the private and wire sizes. Only a host producer can declare evidence,
and existing model-use, citation-use and retained-read checks still apply.
A server-provided citation ID, annotation, locator, URL or progress message
grants no display, citation or retrieval authority.

A deterministic pre-POST refusal can return a fixed `ToolFailure` code. After
POST, only a fully validated, normalized terminal success is recorded as known
success. Treat `isError`, invalid content, transport loss, unsafe responses and
unresolved cancellation conservatively as uncertain. Reuse the existing
`tool_effect_uncertain` path to stop automated model repair and redispatch.
An operator's existing reconciliation path can resolve an uncertain operation.
The server may continue work after client cancellation and local fencing
cannot guarantee exactly-once remote effects. Keep Runtime tool lifecycle and
approved scalar projections as the progress stream. No server notifications,
credentials, raw response, headers, addresses or SDK exception text enter
events, public status or logs.

## Harness and backward compatibility

Expose aliases via existing `custom_tools`, `WorkflowPolicy.allowed_tools`,
node `tools` and `RunPolicy.allowed_tools`. Require host policy ceilings
and existing `ToolContracts` and operation bindings. Registry construction,
YAML/JSON admission, workflow proposal compilation, freeze and receipt
adoption perform no MCP I/O. Only approved alias/schema/description enter a
model-facing catalogue. When a factory has an MCP registration, harden
`WorkflowFactory._frozen_copy` to preserve generated handlers and the result,
event and parallel fields on every copied tool. This also preserves local
parallel neighbors in a mixed registry. Retain the existing copy path for
factories with no MCP registrations and preserve previously sealed bundles.

The existing custom descriptor, operation signature, result, prepared turn
and receipt formats already carry the necessary version identity. Introduce no
MCP-only document or storage marker. Use existing tool-contract and parallel
migrations only when the host enables those features. Existing readers can
read compatible documents under their current rules. MCP execution requires a
matching generated registry and Runtime capability. An older deployment can
continue serving unchanged local bindings, but MCP execution and MCP-bound
resume require the new Runtime and the identical sealed host registration.
Resuming under a changed seal fails before provider/MCP work. Adopting an
already accepted receipt and opening a captured citation require current
existing local authorization and no live MCP connection. Preserve the
published Core, Runtime recorder and Harness PostgreSQL adapter bytes unless
a demonstrated compatibility failure requires a separately scoped change.

| Situation | Expected behavior |
| --- | --- |
| Current or historical local-only deployment | Existing SDK imports, local execution and stored bytes are preserved. |
| New Runtime with a registered but unselected MCP alias | Existing execution path. No SDK import, connection or grant callback is required for that alias. |
| New MCP run or turn | Extra and matching host registration required. Existing tool-contract formats apply, including parallel formats when the host separately enables parallel policy. |
| Same-binding cold restore | Verify the private catalogue and rebuild locally. A fresh remote dispatch still needs a live client and current grants. |
| Existing accepted receipt or captured citation | Use stored content under current grants. No remote lookup. |
| Missing capability or changed execution binding | Refuse MCP execution or resume before provider or MCP dispatch. Older readers can still decode their supported existing formats. |

## Lab and qualification

Use the official SDK to run owned synthetic modern and legacy HTTP MCP
fixtures, plus narrowly controlled response fixtures for transport failures.
Reuse both synthetic provider wires and public Runtime/Harness APIs. Include
an installed blueprint for an authorized service lookup, a denied lookup and
a captured citation view. Test tool aliases selected per workflow node, native
and YAML restore, current permissions, a mixed parallel window with an MCP
barrier, and both PostgreSQL majors using existing restricted roles.

The current published family keeps its 12 lanes and 402 required cases per
cell. The MCP-qualified family adds one lane with 12 logical cases × two
provider wires, totaling 13 lanes and 426 cases per cell. Modern mode is the
default fixture. Exercise legacy negotiation on both provider wires in its own
logical case and cover legacy faults separately in Runtime tests. Check AMD64
and ARM64 against PostgreSQL 16/18, plus source, isolated wheel and rebuilt
sdist. Record exact candidate Runtime/Harness hashes, retained SDK bytes,
locked MCP dependencies and capability proof. Keep public manifests and
historical baselines immutable in the implementation increment.

## References

- [MCP 2026-07-28 tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [Streamable HTTP and compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- [MCP authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [Official Python SDK protocol versions](https://py.sdk.modelcontextprotocol.io/protocol-versions/)
- [Python SDK transport controls](https://py.sdk.modelcontextprotocol.io/client/transports/)
- [Python SDK client API](https://py.sdk.modelcontextprotocol.io/api/mcp/client/)
- [Python SDK releases](https://pypi.org/project/mcp/)
