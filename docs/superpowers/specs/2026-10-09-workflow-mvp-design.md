# Validated in-memory workflow factory: production MVP

Date: 2026-10-09. This normative revision supersedes the initial factory design and preliminary resolution recommendations. The user authorized implementing the revised design after the production review. Production readiness requires the verification gates below.

## Goal and ownership

Harness provides supported validation and sealing for trusted in-memory assembly and client/LLM-generated graphs. Proposals contain logical references and optional inline agent instructions. Private host bindings contain configuration, native implementations and validators. No proposal supplies a base_dir, physical workspace, endpoint, credentials or executable binding.

Prosaic owns canonical prose validation; Runtime owns execution metadata, model transports and native tools; Harness owns graph admission, durable orchestration and recovery. Consumers own authentication, request-specific policy selection, domain authorization, safe response projection and versioned asset persistence. Trusted callbacks are not sandboxed.

## Public API

Export WorkflowCatalog, WorkflowBindings, WorkflowPolicy, WorkflowFactory and WorkflowAdmissionError from prosaic_harness.

```python
catalog = WorkflowCatalog(agents={"finder": inspected_agent}, schemas={"result": result_schema})
bindings = WorkflowBindings(config=runtime_config, custom_tools=native_tools, validators=validators)
policy = WorkflowPolicy(
    allowed_agents=frozenset({"finder"}),
    allowed_schemas=frozenset({"result"}),
    allowed_tools=frozenset({"lookup_entity"}),
    allowed_validators=frozenset(),
    allowed_model_tiers=frozenset({"fast"}),
    allow_agent_composition=True,
    allow_inline_agents=False,
)
factory = WorkflowFactory(catalog=catalog, bindings=bindings, policy=policy)
workflow = factory.build(definition)
workflow2 = factory.build_json(json_envelope)
harness = Harness(workflow, store=store, run_id=run_id)
```

build(definition, *, inline_agents=None) accepts plain finite JSON mappings and returns a Workflow-compatible internal native subtype. build_json accepts exactly definition and optional inline_agents in a strict envelope. There are no public fingerprint, descriptor, path, base_dir, inline_schemas or validate=False arguments.

Aliases follow the existing simple step-name syntax and are at most 64 characters. Catalogue aliases may differ from canonical artifact IDs; retain original artifact content/digest. Inline IDs are supplied by the factory. Reject collisions and unused inline entries. Unused host assets do not enter identity. Catalogue/binding/policy setup owns snapshots and invokes no files, models, callbacks or validators.

WorkflowBindings derives an independent native RuntimeConfig with tool_directories=(), retaining other host settings. Seal and execute that effective configuration. Native registry validation/descriptors use public pure Runtime APIs, never Runtime construction or CLI discovery. Callback objects are retained by identity; immutable definitions and registration mappings are owned.

WorkflowPolicy is mandatory; it has no implicit trusted mode. Composition means more than one agent step, independent of inline-agent permission. Both permissions default false. Requested capabilities always remain subject to host runtime grants, graph grants, policy and prose. Registering an implementation does not grant it.

Omitted model_tier always selects the host default, even with an empty or named-tier-only policy allowlist. Explicit tiers require a configured route and an allowed name. Default/route configuration remains sealed.

## Scope

Support agent, gate, check, pause and finish, bounded revisits, native tools, host validators, file/database stores, approved catalogue schemas and optional inline agents. Trusted applications may generate schemas in memory and register them as approved host catalogue content.

Reject dynamic source, runtime, evidence, read_roots, require_reads and acquisition, unknown graph keys and filesystem/CLI tool grants. A resources proposal fails resource_not_bound. Inline bundled agent resources are embedded relative-name/string-content data and never host file lookups. Known builtin tool declarations may remain inert prose metadata; unknown names not present in the native registry fail. Preserve legacy requested-CLI preflight behavior.

Defer arbitrary client schemas, opaque factory adapter protocols, dynamic filesystem/CLI/resource materialization, a new workspace option, automatic prose concatenation, graph generation and HTTP/service endpoints. Domain logic stays in consumers.

## Canonical and executable artifact validation

Add Prosaic.validate_artifact_definition(kind, frontmatter), using the existing result contract of validate_frontmatter. Validate kind, optional declared-type agreement and canonical fields without inserting type or changing extension semantics. Existing validate_frontmatter and discovery diagnostics remain compatible.

Export Runtime.validate_execution_artifact(artifact, config, *, acquisition=None), a pure ValueError-based helper. Reuse structural inspection and requested_tools syntax; validate effort, final route/default and known selected-provider restrictions against effective Runtime features. Acquisition metadata inherits the final execution context; supplied tier/effort must match. The helper does not discover manifests, inspect files, construct a Runtime, invoke models or callbacks. Runtime execution reuses it. Export validate_custom_tools and custom_descriptors as supported pure APIs.

Harness applies canonical and executable validation to every resolved artifact, including typed host artifacts. Invocation-dependent rendered input size remains a pure preparation check before pending dispatch.

## Bounded snapshots and admission profile

Validate before deepcopy, dataclass conversion, serialization or hashing. Use iterative traversal with finite JSON, string keys, cycle detection, depth, expanded-work and encoded-byte bounds. Shared subtrees must not expand exponentially before rejection; benign sharing within budgets may be accepted. Raw decoding bounds bytes first and maps numeric/Unicode/recursion/duplicate-key failures to safe errors.

Dynamic format/evaluation profile version 1 seals the complete policy, limits and acceptance-affecting schema rules. Defaults:

| Bound | Default |
| --- | --- |
| Steps / agent steps | 64 / 32 |
| Proposal JSON bytes | 262144 |
| JSON container depth / expanded nodes per admitted value | 64 / 65536 |
| Resolved artifact bytes, including resources | 524288 total |
| Schema bytes | 65536 each / 524288 resolved total |
| Calls / visits / attempts per visit | 12 / 4 / 2 |
| Invocation timeout / whole-run seconds | 180 / 1800 |
| Reported whole-run token budget | 32768 |
| Run-input / human-response bytes | 65536 / 65536 |
| Prepared invocation JSON/rendered prompt bytes | 262144 |
| Agent output JSON bytes | 100000 |
| Persisted runtime event bytes | 65536 aggregate |
| Result metadata bytes | 65536 |
| Durable receipt bytes | 1048576 |
| Durable run document bytes | 4194304 |

Bounds are positive finite integers, excluding booleans. Host changes must remain compatible with the 8 MiB storage contract and output JSON ceiling. Missing graph bounds inherit the host defaults; lower request bounds are retained; requests over caps fail. Limit defaults/capacity reservations are part of profile identity.

Use exact storage encoding when budgeting durable documents; JSON indentation/ASCII escaping must not invalidate preflight. Profile 1 reserves 4096 bytes and 16 expanded nodes in nonterminal run documents for a small terminal blocked event and completed invocation ledger. State/data growth is checked before accepting new human decisions/output bindings or dispatching an invocation. Limit failures leave a valid bounded checkpoint, with no accepted oversized output. Initial input failure creates no state.

Call/visit/byte limits are enforced bounds. Tokens are a post-invocation reported-usage budget: one invocation may overshoot and unknown usage preserves existing fail-closed behavior. Whole-run time includes human waiting; deadlines/cancellation stop subsequent progress but cannot forcibly preempt trusted callbacks, validators or in-process schema CPU.

## Schemas

Only approved catalogue schemas are admitted. Use Draft 2020-12 object/boolean schemas, an isolated no-retrieval Registry per resolved root and correct resource/scope semantics. Reject duplicate canonical resource IDs and duplicate anchors within a resource, unsupported nested dialects, external references, dynamic references and schema evaluation/reference cycles on the new factory path. Support acyclic internal static refs, unique anchors/local IDs and ordinary defs reuse. Traverse schema positions, not JSON data stored in enum/const/examples.

Approved regex/combinator schemas and native tool parameter schemas remain a host-vetted trust choice; bounded JSON alone is not a CPU sandbox. Do not claim arbitrary full JSON Schema can safely execute in-process.

One evaluation facility handles outputs, receipt adoption, new human responses and saved decisions. Dynamic instances receive profile bounds. Legacy YAML keeps existing acceptance semantics, productive recursion, historical deeper valid responses and identity recipes. Controlled resolver/recursion/evaluation failures are distinct from invalid instances; diagnostics are bounded and do not contain raw values/schemas. Stop after the required number of errors.

## Admission provenance and mutation

Factory results retain fixed native origin through a distinct internal subtype and an owned admission record containing original seal, immutable serialized snapshots, effective policy/evaluation profile and trusted registrations. Missing/inconsistent records fail closed; altered path cannot turn a native workflow into legacy. Compare current content and supplied fingerprint with the independent original seal, and rerun shared semantic admission. Hash computation or a private boolean is not proof of admission.

Legacy Workflow constructor signature remains. Manually assembled resolved pathful legacy objects receive shared trusted legacy admission only when their legacy shape/path/bindings are valid; absent native metadata alone does not qualify. A raw Workflow with path=None cannot execute. No readmission silently repairs a forged identity.

Every Harness construction/run/resume/status and new dispatch validates admission, identity, required descriptors/validators and actual adapter. Dynamic defaults use independent owned configuration snapshots. Only standard ProsaicRuntime instances are supported as native runtime overrides in this MVP; matching live effective config, relevant descriptors/capabilities and empty cli_tool_names are mandatory. Opaque legacy fake adapters remain available on positively admitted legacy paths. No concurrently mutable Runtime/Harness sharing is supported; reusable factories own independent request snapshots.

Legacy YAML shares graph/artifact invariants but retains its transport privileges, file reads/CLI preparation, defaults and exact fingerprints. Required descriptors are derived from trusted native/CLI bindings and cannot be supplied as proof by callers.

## Execution, storage and recovery

Native Workflow.path is None. After admission, run/resume owns a private empty TemporaryDirectory to satisfy Runtime cwd. Never fall back to service cwd. Cleanup on completion, pause, cancellation and exception; random path stays outside identity and controlled prompt/event fields. Legacy YAML retains its root/evidence/preflight behavior.

Bound run inputs before state creation and prepare arguments/rendered prompt before incrementing attempts/calls or saving pending. Pure input/preparation rejection must not leave a phantom interrupted invocation. Runtime retains later conversation/transport budget checks.

A returned result/events/metadata over profile budgets becomes a bounded failure receipt preserving invocation identity and safely available usage/accounting data; never truncate output into a purported valid artifact. Persist the receipt, complete the ledger and block with a defined limit reason. Store failures still propagate.

Schema-evaluation failure after a saved receipt blocks schema_error without model retry or accepted output. Saved receipts are immutable and adopted after crashes. Existing resource-reason precedence is preserved: expired deadlines/cancellation may block before evaluation, but no new invocation occurs. Human validation failures write no decision. Historical checkpoint verification/status remains read-only.

Preserve pending recovery, explicit interrupted retry, stale-output checks, leases/revisions, expected revision for database human actions, checkpoint version 2 and receipt version 1. A crash after remote completion but before receipt commit remains ambiguous; no exactly-once remote-effect promise.

## Identity and errors

Preserve YAML fingerprint payload/omission rules exactly. Native identity adds admission format/profile and full effective policy to normalized graph, resolved schema/artifact digests, effective Runtime identity and relevant tool descriptors. Callback objects, temporary paths and unused host assets are excluded. Validator versions remain separately sealed as released. Used content/config/policy/profile changes reject reconstruction/resume.

WorkflowAdmissionError(ValueError) exposes stable bounded code/location: invalid_definition, invalid_artifact, invalid_schema, unknown_reference, policy_denied, limit_exceeded, resource_not_bound, binding_mismatch, identity_mismatch. No raw paths/prose/secrets/parser exceptions. Execution failures have bounded schema/input/state/result/receipt/event limit reasons. Consumers project safe summaries rather than serialize private execution objects/checkpoints/Runtime diagnostics.

## Implementation and release gates

Write regression tests before production changes. First add Prosaic/Runtime pure APIs, then bounded JSON/schema and shared graph admission, then factory/provenance and engine integration, then offline consumer examples and packaging.

Required evidence: malformed/aliased/deep input rejection before copying/writes; all policy intersections and no model-controlled binding; native mixed CLI-config isolation; independent seals and adapter mutation checks; isolated schema resolution and deterministic duplicate rejection; exact document budgets including Unicode; fault injection around normal/failure receipts and adoption with resource precedence; cleanup and cross-worker reconstruction in both store modes; historical YAML identities/deep responses/acquisitions/CLI/sandbox/manual adapters; full affected suites/core immutable TS oracle; clean installed wheels, public APIs and native local-HTTP example without Node/Prosaic CLI. Update immutable dependency pins in dependency order. Local candidate commits/wheels are verified separately from publishing; implementation does not authorize release/push/merge or live providers.
