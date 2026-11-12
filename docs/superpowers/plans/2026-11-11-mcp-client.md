# MCP Client Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for native implementation and obtain independent whole-branch review, following the maintainer's established workflow. Track steps with checkboxes.

**Goal:** Admit and execute approved MCP read tools in Runtime and Harness with bounded dispatch, current authorization and durable replay.

**Architecture:** Runtime builds ordinary `CustomTool` bindings from host-reviewed MCP catalogue snapshots and runs them through its existing tool loop and effect journal. Harness selects those aliases at each node or conversation and preserves binding identity during restore and receipt adoption. Lab exercises the installed SDKs against owned synthetic MCP and model-provider endpoints.

**Tech stack:** Python 3.11–3.13 SDKs, official `mcp>=2.3.0,<3` optional extra, AnyIO and httpx2 as used by SDK v2, existing JSON Schema and journal contracts. Lab Python 3.12+, PostgreSQL 16/18 and owned containers.

**Spec:** [MCP client design](../specs/2026-11-11-mcp-client-design.md). Read both documents before implementing.

## Global constraints

- Start from current released mains. Verify the baseline of Runtime 0.9.21, Harness 0.9.15, Harness PostgreSQL 0.4.4 and Lab 0.9.14. Keep Core 0.5.0 and Runtime recorder 0.3.0. Preserve user worktrees and use isolated implementation branches.
- Support explicit Streamable HTTP profiles `2026-07-28` and `2025-11-25` with JSON and request-scoped SSE. Use host-managed resource-bound bearer credentials. Loopback HTTP is credential-free and explicitly enabled for fixtures.
- New Runtime capability `mcp_client_v1`. Use an optional extra and lazy imports. Keep ordinary SDK installs and no-MCP applications compatible.
- Bound one operation to 8 list pages, 128 tools, 64 KiB catalogue, 16 KiB per selected schema, 16 KiB arguments, 128 KiB decoded transport, 64 SSE events, 32 KiB per event and 32 KiB normalized result. Discovery 10 seconds, call 20 seconds, cleanup 1 second, active operations default 4 with range 1–16. Apply the existing Runtime deadline and wire bounds.
- One authorized tool POST at most per newly claimed slot. Replays perform zero MCP I/O. Remote metadata confers no execution, display or evidence permissions. MCP registrations are read-only by host contract and serial in parallel batches.
- Preserve existing serialized formats, file and PostgreSQL store markers, receipt readers, lock/lease rules and old default bytes. MCP-bound restore requires the same sealed registration. Base and historical release manifests stay immutable during implementation.
- Sub-agents, local process launch, interactive OAuth and other MCP capabilities are separate work. Use synthetic services with no paid inference. Qualification uses exact development builds without publishing.

## Review focus

- Scope revocation while the server returns its last catalogue page must prevent the tool POST and preserve a known zero-dispatch outcome (Task 4).
- The official SDK can transparently relist/resend or drive input-required rounds. A header mismatch, input-required result and disconnect must each send exactly one tool POST and leave a fenced outcome (Tasks 3–4).
- A catalogue can drift while accepted results are already durable. A new controller must adopt and view the old receipt with the original trusted snapshot while MCP is offline (Tasks 2 and 6).
- A small tool result can arrive inside a flood of SSE events or a large chunked JSON response. Stop before the parser or projector can accumulate the response (Task 3).
- WorkflowFactory's frozen-copy path currently reconstructs tools without copying result, event and parallel fields. A frozen MCP bundle must preserve these fields and the exact MCP seal (Task 5).

## File map

| Repository | Planned location | Ownership |
| --- | --- | --- |
| Runtime | `src/prosaic_runtime/mcp.py`, `mcp_catalog.py`, `mcp_transport.py` | Host API, immutable catalogue and schema validation, bounded SDK I/O |
| Runtime | `runtime.py`, `conversation_preparation.py`, `direct_tool.py`, `structured_tools.py` under `src/prosaic_runtime/` | Selective admission at normal entry points |
| Runtime | `pyproject.toml`, `tests/test_mcp_*.py` | Optional dependency, transport and installed contract tests |
| Harness | `src/prosaic_harness/factory.py`, `graph_admission.py`, `workflow.py`, `conversation_bindings.py` | Preserve bindings, validate existing alias and execution paths |
| Harness | `tests/test_mcp_*.py`, `adapters/postgres/tests/test_mcp_recovery.py` | Public entry-point and durable owner tests |
| Lab | `lab_runner/mcp_fixture.py`, `src/prosaic_integration_lab/mcp_client.py`, `lab_runner/blueprints/mcp_client/` | Owned server, acceptance witnesses and copyable host |
| Lab | `tests/{unit,acceptance,blueprint_acceptance}/`, `lab_runner/gates.py`, `lab_runner/__main__.py`, `scripts/`, `dependencies/` | Exact-family gates, optional dependency lock, installed/archive checks |

Existing modules own generic tool validation, journal completion, result
projection, guard validation and receipt adoption. Extend those entry points
where needed and keep protocol behavior in the MCP modules.

## Task 1. Runtime capability and selected-tool admission

**Consumes:** Existing `CustomTool`, `RunPolicy`, `ToolContractBindingsV1`,
`InvocationScope`, `ToolJournal` and `ProsaicRuntime.capabilities`.
**Produces:** Pure `is_mcp_tool(tool: CustomTool) -> bool` and internal
`admit_mcp_tools(tools, selected, *, surface, policy, scope, journal, contracts) -> None`.
Use the exact generated handler type as the predicate. A version string alone
does not classify an ordinary tool as MCP.

- [ ] Add `tests/test_mcp_admission.py`. Test importing and running a plain local tool in an environment without `mcp`. Select a generated tool fixture with no journal, unbounded budgets or missing contracts and assert zero provider and MCP requests. With a mixed registered catalogue, assert that a run selecting only a local alias keeps existing behavior.
- [ ] Prove red with `python -m pytest -q tests/test_mcp_admission.py`.
- [ ] Add the optional extra in `pyproject.toml`, declare any directly imported transport dependencies at compatible floors, and keep imports lazy. Wire admission into API `run`, prepare/restore and the unsupported surfaces listed in the spec. Reject unsupported initial-tool and acquisition combinations at admission. The helper must not resolve credentials, discover tools or invoke host callbacks.
- [ ] Run the new suite and the existing tool-contract, initial-tool, direct, structured and parallel admission tests. Confirm the installed base wheel works without the extra. Commit the Runtime admission change.

## Task 2. Runtime snapshot and alias binding

**Consumes:** Task 1 classification and existing immutable tool/schema/result
descriptors. **Produces:** `McpServerV1`, `McpCatalogV1`,
`McpToolSpecV1`, `McpClientV1.bind_tools` and
`McpClientV1.restore_catalog` with the spec signatures.

- [ ] Add `tests/test_mcp_catalog.py`. Pin tests for closed and host-narrowed open schemas, both validators on actual arguments, unsupported `$ref`, `x-mcp-header` and oversized schemas, duplicate aliases, retained schema hashes literal read-only grant, existing-registry collisions and local description ownership. Show that new credentials alone do not change the descriptor, while a different scope, endpoint, revision, schema or binding version does. Test tampered snapshot, wrong scope and rebind with no socket access.
- [ ] Run `python -m pytest -q tests/test_mcp_catalog.py` for red.
- [ ] Implement canonical bounded catalogue encoding and selected schema checks in `mcp_catalog.py`. Validate all input bounds before trusting snapshot content. Expose pure registry construction in `mcp.py` using the existing `CustomTool` constructor and operation-key convention. Persist only a host-owned versioned snapshot plus independently pinned SHA-256.
- [ ] Run the catalogue and existing descriptor/golden tests. Assert stable ordering and equal fingerprints after a private snapshot export/restore round trip. Commit the Runtime snapshot contract.

## Task 3. Runtime transport and discovery

**Consumes:** Tasks 1–2 server and catalogue types. **Produces:**
`McpClientV1.discover(*, access_scope)`, `__enter__`, `__exit__` and an
internal one-operation async transport that yields validated, size-limited
SDK responses.

- [ ] Add `tests/test_mcp_transport.py` using actual SDK servers and loopback HTTP. Assert both explicit protocol profiles, legacy wrong-version refusal, multi-page discovery and repeated-cursor refusal. Assert that 3xx, userinfo, ambient proxy, unapproved destination, server callback requests and unsupported GET/resumption cannot create unintended outbound requests. Assert cap enforcement for oversized JSON delivered chunked, notification flood, SSE event overflow and compressed bodies. Count actual HTTP method/target and tools/call attempts.
- [ ] Run `python -m pytest -q tests/test_mcp_transport.py` for red.
- [ ] In `mcp_transport.py` wrap the SDK's Streamable HTTP client with byte/event limits and a single-endpoint, one-tool-POST boundary. Use the SDK low-level session call, cache-bypassed listing, and explicit legacy compatibility. Prove against SDK 2.3.0 and the resolved lock that header generation, auth and cancellation work without hidden relists, resends, GET or cross-origin access. Verify bounded legacy DELETE separately.
- [ ] Run the transport suite on Python 3.11 and 3.13, at the SDK floor and resolved version. Verify no leaked task or thread after timeout or close. Commit the Runtime transport.

## Task 4. Runtime dispatch, outcome and evidence

**Consumes:** Tasks 1–3 and `ToolExecutionContext.remaining_timeout`,
`ToolFailure`, `ToolResultV1` and the existing journal settlement path.
**Produces:** Contextual handler for a generated `CustomTool` with no new
tool loop, outcome record type or public event fields.

- [ ] Add `tests/test_mcp_dispatch.py` and `tests/test_mcp_installed.py`. Count zero POSTs for invalid arguments, authorization failure, revocation during listing, schema drift and exhausted budgets. Verify one POST for header mismatch, input-required, disconnect, timeout and cancellation after send. Assert no resend on same slot, and zero network on completed replay under current grant. Assert different aliases, versions and arguments under the same operation key fail before send. Replaying a committed pre-POST failure returns the fixed failure.
- [ ] Test JSON structured output and text-block framing, oversized/invalid results, guard-visible facts, authorized citation delivery and denial, no raw error/URI/credential leakage in events or observation, owner-thread callbacks, and an MCP serial barrier between independent local read windows. Test known terminal response winning a cancellation race before any follow-up model request, owner-only cancel callbacks, and concurrent client close draining active I/O without admitting new operations.
- [ ] Run `python -m pytest -q tests/test_mcp_dispatch.py` for red. Implement in `mcp.py` using the bounded worker and owner permit from Task 3. Keep the scope/route/grant recheck on the owner after listing. Use existing normalization and journal settlement. A deterministic failure before the POST returns a safe controlled code. Ambiguous post-send failures enter existing uncertain-effect handling.
- [ ] Run the new and existing result, journal, cancellation, parallel and citation tests. In a clean wheel consumer run `python -I -m pytest -o pythonpath=tests tests/test_mcp_installed.py -q`. Qualify zero required skips. Commit Runtime dispatch.

## Task 5. Harness workflow and conversation authority

**Consumes:** Runtime capability, generated tools, `is_mcp_tool`, existing
`WorkflowBindings`, `Workflow.load`, `ConversationBindings` and
`ToolContracts`. **Produces:** Existing APIs accept and seal MCP aliases
only on the supported node and conversation surfaces.

- [ ] Add `tests/test_mcp_bindings.py`. Build two agent nodes with different MCP aliases and prove exact provider-visible tool lists. Test YAML and JSON proposals with invalid alias, direct node, initial tool, acquisition and interpreter leakage. Freeze a mixed MCP and local registry and compare all tool descriptors before and after. Verify old non-MCP frozen bundles keep their existing copy identity. Count zero sockets and host authorization calls during pure graph admission.
- [ ] Run `python -m pytest -q tests/test_mcp_bindings.py` for red.
- [ ] Update graph and conversation admission to require compatible Runtime and explicit trusted bindings when an MCP alias is selected. Preserve `result_contract`, `event_policy` and `parallel_read` in `WorkflowFactory._frozen_copy` when the registry contains a generated MCP tool. Preserve the existing copy path for other registries. Use existing alias and scope checks. Keep the optional dependency out of Harness metadata.
- [ ] Run the new tests plus existing factory, frozen bundle, context pack, guarded workflow and parallel-tool suites. Commit Harness binding support.

## Task 6. Harness durable replay and downgrade

**Consumes:** Tasks 2, 4 and 5 and existing invocation namespaces, receipts
and owner migrations. **Produces:** Same-format MCP receipt adoption and
binding mismatch refusal across Memory, File and PostgreSQL.

- [ ] Add `tests/test_mcp_recovery.py`, `tests/test_mcp_installed.py` and `adapters/postgres/tests/test_mcp_recovery.py`. Prove same-scope, fresh-controller adoption from a restored catalogue with the MCP server offline. Test scoped journal replay, changed seal before provider work, retained citation revocation, persisted unknown-effect refusal and stale lease takeover after POST. Test the mixed local parallel case with existing enabled-store versions.
- [ ] Assert older fixtures retain exact disabled-feature bytes, versions and hashes, including tool-contract and parallel records. Test absent MCP extra on a non-MCP application and capability mismatch on MCP resume.
- [ ] Run the new source tests for red. Reuse current runtime constructors, claims and receipt checks. Correct any binding or scope propagation loss in the owning workflow/session path. Keep existing store markers and DDL.
- [ ] Run Memory/File and the existing owned PostgreSQL 16 and 18 lanes with zero required skips and verified cleanup. Run isolated Harness wheel MCP tests against the exact qualified Runtime wheel. Commit Harness recovery verification.

## Task 7. Lab blueprint and required matrix

**Consumes:** Qualified Runtime and Harness development wheels and existing
published adapter/Core/recorder artifacts. **Produces:** Public sample,
`mcp-client` acceptance mode and a coherent exact-family gate.

- [ ] Create owned synthetic servers in `lab_runner/mcp_fixture.py` and a copyable host under `lab_runner/blueprints/mcp_client/`. Use the installed SDK for modern/legacy happy paths and a narrow deterministic HTTP fixture for fault cases. Bind on loopback and assert teardown. Reuse existing provider fixtures and public Harness APIs.
- [ ] In `tests/acceptance/test_mcp_client.py`, enumerate these 12 cases on both provider wires: approved structured call, approved text call, legacy negotiation, scoped authorization denial, revocation during listing, catalogue drift, captured citation and retained-read authorization, mixed parallel barrier, budget exhaustion, uncertain dispatch and replay refusal, completed journal replay, fresh receipt adoption. Verify exact outbound counts and real stack cleanup.
- [ ] Add `tests/unit/test_mcp_hosted.py` and `tests/blueprint_acceptance/test_mcp_client.py`. Assert 13 lanes and 426 required cases for the coherent candidate, and 12 lanes and 402 for the current released family. Reject mixed manifests, missing MCP extra, missing qualification and required skips. Make the copied blueprint execute a real synthetic request and exercise authorized and denied paths.
- [ ] Extend existing gates, `scripts/prepare_sdk_candidates.py`, `scripts/required_acceptance.py`, `scripts/conversation_distribution_smoke.py`, `scripts/build_consumer.py` and the existing hosted acceptance workflow. Keep MCP dependencies in a separate hash-locked optional input and include them in both installed consumers. Select exact SDK receipts and original retained wheel hashes. Keep old published/candidate gate branches and archive histories unchanged.
- [ ] Run the focused source and blueprint tests, verify the exact candidate wheel and rebuilt sdist, and run the owned PostgreSQL 16/18 MCP lanes. Record which AMD64/ARM64 hosted cells remain pending until CI authorization. Commit Lab integration.

## Task 8. Documentation and independent review

- [ ] Update each README and public guide with setup, example tool aliases, auth scope, backwards compatibility, catalog readmission, controlled errors, reconciliation and supported transport profiles. Update the Cerebro backlog with candidate status after qualification. Preserve sub-agent follow-up status.
- [ ] Verify exact SDK dependency floors, clean base installs, source and isolated consumers, old fixture bytes, checked citations, both MCP profiles, both provider wires and both database majors. Preserve archive hashes, test counts and cleanup receipts.
- [ ] Obtain independent whole-branch review across Runtime, Harness and Lab. Ask the reviewer to check the five review-focus cases and whether the SDK can issue a second tool POST through any code path. Reproduce and correct material findings before completing implementation.

The plan stops at an independently reviewed development candidate. Stable
version selection, public pins, deployment rules and publication belong to
a separate release task.
