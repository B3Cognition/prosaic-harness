# Validated in memory workflow construction

Provide a supported Harness API that validates and seals workflows assembled in
memory. Trusted application code can supply inspected or composed agents,
schemas, and registered native tools. A service can use the same mechanism to
admit generated graphs against host-owned policy. Neither path requires a
caller-invented directory or manual fingerprints and private descriptor fields.

The user approved this direction on 2026-10-09. This written specification is
ready for review; implementation planning follows approval of this artifact.

## Scope and success criteria

The original Pressbox feedback describes trusted code loading inspected agents,
combining their prose, generating schemas, registering tools, and manually
assembling `Workflow`. The broader Opta product use case is new functionality
composing approved specialists from current Prosaic artifacts in response to a
prompt, with selection and review pauses. The user clarified that there is no
existing Opta workflow file to migrate. Generic acceptance fixtures must cover
these two construction patterns without depending on a product checkout.

Success means that a consumer can construct a runnable native-tool workflow
through public APIs without filling private fields, duplicating graph validation,
or inventing a YAML path. A generated graph cannot introduce endpoints, tool
implementations, physical paths, or authority beyond host policy. Existing YAML
workflows, checkpoint formats, and fingerprint recipes remain compatible.

The first delivery supports all existing graph step kinds, in-memory agent and
schema references, optional inline definitions, native custom tools, trusted
validators, bounded loops, and existing file/database run stores. It preserves
trusted YAML filesystem, evidence, acquisitions, and CLI capabilities.

Dynamic filesystem access, dynamic CLI registration, logical file-resource
materialization, automatic prose concatenation, HTTP endpoints, LLM graph
generation, product-specific authorization, and a fluent builder are outside
this delivery. Dynamic requests for unbound resources fail explicitly. A private
workspace never implicitly grants file access. These exclusions do not prevent
native host callbacks from implementing approved domain operations.

## Architecture and ownership

| Layer | Responsibility |
| --- | --- |
| Workflow proposal | Versioned graph, logical references, schemas, inline agent data when permitted, requested tools and limits |
| Harness construction and admission | Canonical and structural content checks, graph validation, catalogue resolution, host policy enforcement, snapshots, identity |
| Host execution binding | Runtime configuration, native registrations, trusted validators, injected adapter, private execution directory, preparation and preflight |
| Consumer service | Authentication, tenant policy selection, graph generation, domain authorization, storage selection, public response projection |

Prosaic remains the canonical prose parser and validator. Runtime remains the
execution and native tool owner. Harness gains construction and admission APIs;
it does not execute TypeScript, import product code, or interpret model-generated
Python. An LLM-generated proposal is ordinary untrusted data. Syntactic validity
of prose does not establish authorization or factual correctness.

Use one shared semantic validator for resolved graph content. YAML loading and
dynamic proposal handling have different input privileges and resolution rules,
then produce the same internal execution representation. Pathful YAML remains a
trusted host input, never an alternate service admission route selected by a client.

## Public construction APIs

Export four small host APIs from `prosaic_harness`:

```python
catalog = WorkflowCatalog(
    agents={"finder": inspected_agent, "reviewer": composed_agent},
    schemas={"result": result_schema},
)
bindings = WorkflowBindings(
    config=runtime_config,
    custom_tools=registered_tools,
    validators=trusted_validators,
)
policy = WorkflowPolicy(
    allowed_agents=frozenset({"finder", "reviewer"}),
    allowed_schemas=frozenset({"result"}),
    allowed_tools=frozenset({"lookup_entity"}),
    allowed_validators=frozenset({"result_check"}),
    allowed_model_tiers=frozenset({"fast"}),
    allow_agent_composition=True,
    allow_inline_agents=False,
    allow_inline_schemas=False,
)
factory = WorkflowFactory(catalog=catalog, bindings=bindings, policy=policy)
workflow = factory.build(definition)
harness = Harness(workflow, store=run_store, run_id=run_id)
```

These names are the selected implementation contracts. `build()` returns the
existing `Workflow` execution type with dynamic identity metadata and private
bindings. It accepts no fingerprint, descriptor-map, path, base-directory,
runtime-endpoint, or tool-registration arguments. The optional keyword arguments
are `inline_agents` and `inline_schemas`, both plain mappings. `build_json(text)`
decodes the corresponding envelope strictly and delegates to `build()`.

`WorkflowCatalog` snapshots host agent and schema mappings at construction.
Catalogue keys are logical aliases, not filesystem paths; an alias need not
equal the canonical artifact ID. Preserve the underlying artifact ID and digest
as provenance. Require simple aliases matching the existing step identifier
pattern, with at most 64 characters. Permit unused catalogue entries; identity
includes only resolved content. All referenced entries must exist and be allowed.

`WorkflowBindings` validates and snapshots `RuntimeConfig`, native `CustomTool`
definitions, and `Validator` definitions without calling handlers or validators.
It retains callback identities instead of deep-copying captured application
objects. No CLI manifest reads or probes occur during its constructor or native
factory construction. Native descriptor validation reuses Runtime's existing
registry machinery. Configuration and registrations are private host inputs.

`WorkflowPolicy` is mandatory for the new factory. There is no inferred trusted
mode, `validate=False`, or model-selectable policy. An application with broader
privileges constructs a broader policy in trusted code. A service selects a
request-appropriate policy after authentication; the definition cannot select it.

Factory instances snapshot configuration and policy and can be reused concurrently.
Per-request building owns fresh resolved data. Factory reuse does not make
`Harness` instances concurrently shareable. The returned workflow remains subject
to admission and mutation checks at execution boundaries.

For factory-built workflows, `Harness` obtains the default native registrations
and required validators from the private binding snapshot. Existing explicit
`runtime=` and `validators=` overrides remain available but must match the admitted
capabilities, descriptors and required validator versions. For legacy loaded
workflows, existing constructor behavior remains unchanged. Storage, run IDs and
accounting context stay explicit Harness arguments, independent of construction.

`build_json()` accepts exactly an envelope with `definition` and optional
`inline_agents`/`inline_schemas`. It rejects unknown envelope keys, duplicate JSON
keys, nonfinite values and oversize input before delegating to shared admission.
`build()` applies the same finite-data and byte bounds to the corresponding
mapping envelope. No transport route or authentication mechanism is introduced.

## Proposal format and permissions

The graph retains `version: 1`, `name`, `start`, `limits`, and `steps`, using the
existing `agent`, `gate`, `check`, `pause`, and `finish` kinds. An agent step's
`agent`, `schema`, and a pause's `response_schema` are logical references.
Step keys otherwise preserve existing semantics. Dynamic proposals reject
`source`, `runtime`, `evidence`, `read_roots`, `require_reads`, and `acquisition`
in this delivery because their current meanings require host file bindings.
They also reject unknown keys. A `resources` request fails with
`resource_not_bound`, rather than being ignored or interpreted as a local path.

Native tool names in `tools` and `require_tools` request capabilities. Each name
must refer to a registered native tool, be allowed by policy and runtime config,
and satisfy existing required-tool/prose rules. Built-in filesystem tools and
CLI-only names are unavailable to dynamic graphs in this delivery, even if a
private workspace or host CLI configuration exists. Prose may retain known
ungranted tool requests as it does today; those tools are not executable. Unknown
tool names fail admission. Bound descriptors include every registered custom
tool requested by resolved prose, preserving existing identity semantics.

The policy allowlists apply to catalogue aliases and registered host tool,
validator and route names. Enabling inline agent or schema permission authorizes
new noncolliding aliases of that content type; it does not require prelisting
those new aliases. Their tools, routes, limits and graph behavior still satisfy
all other policy constraints. Unused inline aliases fail even when permitted.

Validator names must be host-registered, policy-allowed, and valid for the step
kind. Model tiers must exist in runtime routes and be policy-allowed. The default
profile is host configuration; clients cannot select an endpoint or credentials.
Consequential native callbacks continue to enforce real host authorization.
Generated arguments or prose claiming approval do not authorize an operation.
Human choices enter through the existing explicit `Harness.resume()` interface.

`allow_agent_composition` governs caller-authored graphs containing more than one
agent step. Disabling it limits such graphs to one agent step; that step may still
be revisited within existing bounds. `allow_inline_agents` independently governs
new agent instructions. Thus a service may allow composing approved specialists
without accepting new prose, or allow a new single specialist while disabling
multi-agent graph composition. Both flags default to false. This contract does
not constrain the number of gate, pause, check or finish steps beyond graph limits.

Trusted application code may concatenate inspected prose before constructing a
catalogue. The resulting artifact receives the same canonical and semantic checks
as every other artifact. The factory seals the actual composite content; it does
not claim to prove the provenance of arbitrary host composition. A client cannot
label newly supplied prose as approved catalogue content. Automatic composition
templates and provenance manifests can be added separately if a consumer needs them.

## Inline content and canonical validation

Inline agents are mappings of logical aliases to plain inspection-shaped data:
`type`, `frontmatter`, `body`, and optional `resources`. The factory supplies their
logical artifact ID; clients cannot override it. Only `subagent` and `command`
types are executable. Resources follow Runtime's existing bundled relative-path
and string-content contract; they are embedded content, never host file lookups.
Unknown inline fields, ambiguous names, and collisions with catalogue aliases
fail admission. `allow_inline_agents` must be true, and the alias must appear in
an admitted graph. Reject unused inline entries to catch accidental or hidden input.

Inline schemas use `inline_schemas`, with the same alias/collision rules and
`allow_inline_schemas` permission, which also defaults to false. Accept valid
Draft 2020-12 object or boolean schemas. Keep internal `$ref`/`$dynamicRef`
references and reject external references throughout the document. No remote
retrieval or custom schema validator supplied by the client is permitted.

Expose Prosaic's existing `validate_frontmatter` function at the public package
root and document its pure contract. Harness uses this canonical validator for
all resolved artifact frontmatter, including typed host artifacts. It then uses
Runtime's structural inspection contract and existing tool declaration semantics.
Structured inline data needs no second Markdown parser. A consumer choosing raw
Markdown uses Prosaic's existing `parse_artifact()` before canonical admission.
Malformed content receives safe diagnostics rather than raw parser text.

Snapshot definitions, schemas, frontmatter, resources, configuration profiles,
routes, endpoint features and policy before admission. Validate finite JSON,
string keys and bounded nesting before copying, traversing or hashing untrusted
content. Frozen dataclasses alone do not provide this guarantee. Snapshot native
registry mappings while retaining immutable tool definitions and their callables.

## Host limits

The dynamic policy has concrete finite defaults. Hosts may configure different
finite values, but requests cannot exceed them. Positive integer requirements
exclude booleans. Resolve defaults before validating identity and use effective
limits during execution.

| Policy bound | Default |
| --- | --- |
| Maximum steps | 64 |
| Maximum agent steps | 32, additionally restricted by composition permission |
| Maximum proposal JSON bytes | 262144 |
| Maximum JSON container depth | 64 |
| Maximum resolved artifact bytes including resources | 524288 total |
| Maximum inline or resolved schema bytes | 65536 each, 524288 total |
| Maximum calls | 12 |
| Maximum visits per step | 4 |
| Maximum attempts per agent visit | 2 |
| Maximum invocation timeout seconds | 180 |
| Maximum whole-run tokens | 32768 |
| Maximum whole-run seconds | 1800 |

Missing dynamic execution limits inherit host defaults, including token and
whole-run bounds. Requests exceeding a cap fail; do not silently raise a cap or
discard requested constraints. Apply per-step visit and attempt caps as well as
global caps. Requested lower limits are retained. Existing accounting for unknown
usage under finite token budgets and interrupted calls remains unchanged. These
are infrastructure bounds, not a guarantee of domain cost or side-effect count.

Legacy YAML defaults remain exactly as released. Built-in native service graphs
use the same factory policy admission as generated graphs; they may be compiled
at startup for a fixed policy. A cached graph cannot be reused under a different
request policy without readmission. The legacy pathful YAML loader remains a
trusted host adapter, never a client-selectable bypass into filesystem privileges.

## Shared semantic validation and mandatory admission

Extract a pure resolved-content validator from `workflow.py`. It checks graph
shape, supported keys, positive bounds, transitions, input references, dependency
requirements, schemas, canonical artifacts, model routes, tools, validators and
acquisition invariants. Transport adapters resolve content and supply trusted
environment metadata where required. Keep path confinement and file reads in
the YAML adapter and host binding layer. Preserve allowed bounded cycles.

`Workflow.load()` delegates to the shared validator after its existing resolution.
The dynamic factory resolves aliases, admits inline content and enforces policy,
then delegates to the same validator. Both paths generate descriptor maps and
identity internally. Service policy is an additional constraint, not a replacement
for graph checks or Runtime's per-invocation enforcement.

Every `Harness` construction and every public run, resume and status boundary
must verify the current resolved workflow against shared admission before writing
state or using saved state. A cached admission record may optimize construction,
but a caller-supplied hash or private marker is insufficient. Recompute the
expected content identity and required descriptors from trusted bindings, and
check adapter capabilities and required validator versions. Current identity
checks continue before graph advancement.

Retain the legacy `Workflow` constructor signature for compatibility. Manually
constructed valid objects can pass shared admission. Invalid graphs, missing or
forged descriptor maps, mismatched schemas, and invented fingerprints fail with
a migration diagnostic before creating a run. Do not silently repair an object
while keeping the caller's identity. Consumers should migrate to the factory.
Legacy examples replacing configuration and recomputing identity remain valid
only if the new configuration satisfies admission; those assignments never prove
admission. No permission is conferred by access to Python constructors.

This is a boundary against untrusted proposals and accidental host assembly.
It does not sandbox or defend against malicious trusted Python code capable of
replacing Harness, callbacks, configuration or admission implementation.

## Execution directories and effect boundaries

Dynamic construction has no physical directory argument and performs no file
creation, model invocation, handler execution, validator execution or CLI probe.
`Workflow.path` is `None` for dynamic workflows. Existing loaded workflows retain
their actual YAML `Path`. Replace direct `workflow.path.parent` assumptions with
an internal binding accessor. Dynamic evidence snapshots are empty in this release.

For native-only dynamic execution, Harness owns a private empty temporary
directory during each run/resume operation to satisfy the current Runtime `cwd`
contract. It is allocated only after successful admission and removed when the
operation exits, including exceptions. A fresh directory on resume is valid
because dynamic workflows have no filesystem capabilities or persisted resource
dependencies. Its random physical name is excluded from workflow identity and
never becomes a prompt field, resource identifier, tool grant or public event.
Do not use the service process's current directory as a fallback. An injected
adapter receives this same private directory and the usual empty filesystem policy.

A host may configure a private `workspace` in `WorkflowBindings` for existing
trusted filesystem workflows. That option is host-only and is not accepted by
the dynamic proposal. It does not enable file tools in a dynamic graph in this
release. Existing YAML uses its released root semantics, evidence snapshots and
preflight behavior. Cross-worker file resources require durable host storage;
implementing new logical resource materialization is a separate delivery.

Separate the following effects in code and documentation:

| Stage | Permitted effects |
| --- | --- |
| Native catalogue/binding setup and graph admission | Pure validation, snapshots and descriptors; no callbacks or filesystem work |
| Trusted YAML loading and CLI preparation | Existing bounded file reads and manifest discovery |
| Environment preflight | Existing trusted CLI availability/version probes; no model calls or native product handlers |
| Run/resume | Private directory allocation, store leases and writes, model execution, granted callbacks and validators |

Required binding and preflight failures occur before run state creation or new
dispatch. Preserve the existing no-automatic-retry rule for interrupted model
requests. Preflight cannot substitute for invocation-time authorization.

## Identity and recovery

Preserve the current YAML fingerprint recipe exactly, including omission of
default-off sandbox configuration and empty tool directories. Preserve checkpoint
version 2 and receipt version 1. Existing released workflows must resume with
their existing identities after this change.

For dynamic workflows, use the existing identity payload plus an `admission`
section identifying dynamic format version 1 and the complete effective policy.
Hash normalized definitions, resolved schemas, canonical artifact digests,
runtime identity and relevant native descriptors. Preserve effective configured
limits and schema references. Resolve mapping order deterministically. Do not
serialize handlers, validator callbacks, authorization predicates or physical
temporary directories. Validator versions remain separately sealed in checkpoints
as today; required host registrations must match at execution admission.

Policy changes conservatively invalidate dynamic resume, even when a changed
allowlist entry is unused. Unused catalogue content and unused native registrations
do not alter identity when policy remains the same. A change to any resolved
prose, schema, runtime setting, used tool descriptor or host policy blocks resume
before another call. Tool version assertions continue to cover captured handler
semantics and fixed data; the factory does not infer them from Python source.

Behavioural parity between YAML and dynamic workflows does not imply identical
fingerprints. Cross-format adoption of an existing run is unsupported in this
delivery. Reconstruct dynamic workflows from the same proposal and host catalogue,
bindings and policy in each worker. Hosts persist versioned proposals and approved
asset versions separately from Harness state; Harness remains the sole state writer.

Mutation of caller-owned input after construction has no effect. Mutation of a
returned mutable legacy workflow invalidates its admission/identity and blocks
execution unless it is reconstructed and readmitted. Preserve pending-call
recovery, saved-receipt adoption, stale-output rejection, leases, revisions and
explicit human response schema validation.

## Errors and public service output

Export `WorkflowAdmissionError(ValueError)` with a stable `code` and a bounded
field location. Initial codes cover `invalid_definition`, `invalid_artifact`,
`invalid_schema`, `unknown_reference`, `policy_denied`, `limit_exceeded`,
`resource_not_bound`, `binding_mismatch`, and `identity_mismatch`. Raw content,
parser exceptions, credentials, source paths, callback captures and provider
errors are not included in dynamic admission diagnostics. Retain released YAML
diagnostic compatibility where required by existing tests.

The library's Python execution objects contain private configuration and are not
service response objects. Consumers must project logical workflow/run summaries
and safe errors rather than serialize `Workflow`, bindings, raw checkpoints or
Runtime diagnostics. Bindings must not inject internal workspace paths into
prompts or tool descriptions. Trusted native handlers remain responsible for
returning suitable domain data; generic redaction of arbitrary tool results is
not a substitute for designing their contracts.

## Changes by repository

| Repository | Changes |
| --- | --- |
| Prosaic | Export/document existing canonical frontmatter validation; add public contract tests; preserve parser and on-disk formats |
| Harness | Shared admission module; catalogue, binding, policy and factory APIs; dynamic identity; mandatory execution admission; private directory lifecycle; public errors, documentation and examples |
| Runtime | Reuse existing native registry and artifact validation; no API change is required for the selected private-directory compatibility approach |
| Consumer service | Adopt factory construction for existing trusted assembly or new approved-specialist composition; product workflows and domain tools remain outside infrastructure repositories |

Harness currently pins Runtime, which pins Prosaic. Test against the locally
updated Prosaic public export and verify the installed dependency chain. A release
must update immutable dependency pins in dependency order so the new Harness
cannot install against a Prosaic version lacking that export. No release, push,
consumer modification or live model run is authorized by this design-writing task.

## Verification and implementation order

Implementation planning should preserve this order:

1. Capture released YAML admission and exact fingerprints using existing
   meaningful fixtures; add regressions for direct-construction bypasses.
2. Export canonical validation and extract shared resolved admission without
   changing YAML formats, fingerprints, step semantics or existing preflight effects.
3. Add public host types, bounded proposal admission, canonical inline content,
   snapshots, native descriptor derivation and dynamic identity.
4. Integrate mandatory Harness admission and private directory lifecycle for
   both file and database store modes, with mutation and adapter checks.
5. Add offline examples and acceptance fixtures for trusted composed artifacts
   and restricted generated graphs using current canonical artifact contracts.
6. Run full affected suites, build wheels and verify installed artifacts and
   pinned dependency compatibility before preparing any release.

Acceptance tests must establish:

- A trusted host can assemble inspected/composed prose, generated schemas and
  native tools without private fields, duplicate graph validation or fake paths.
- An approved-specialist graph can select an entity, fetch structured data,
  prepare a result and reach explicit selection/review pauses using synthetic
  native callbacks and a local HTTP fixture. Product tool names stay in consumers.
- Inline prose and multi-agent composition permissions operate independently;
  valid prose requesting unauthorized behavior cannot broaden effective grants.
- Invalid transitions, references, schemas, bounds and unsupported fields fail;
  registration alone never authorizes execution. Remote schema references, JSON
  cycles, nonfinite numbers, excess nesting and duplicate raw JSON keys fail safely.
- Raw `Workflow` objects with valid-looking hashes but invalid graphs or omitted
  tool descriptors fail before state writes, across run, resume and status paths.
- Input mutation leaves snapshots unchanged; changes to returned workflow data,
  effective policy, required tool versions or required validator versions block use.
- Construction performs no models, handlers, validators, directory creation or
  CLI probes. Native execution uses a managed private directory, never the process
  working directory, and removes it on completion, pause, cancellation and error.
- Dynamic file/resource requests fail explicitly. Internal workspace paths do
  not enter controlled prompt, error or structural event fields.
- Exact released YAML fingerprints, default omission rules and existing recovery,
  read receipts, acquisitions, human responses, custom tools and sandbox behavior pass.
- FileRunStore and existing database adapter fixtures retain lease/revision and
  saved-receipt behavior; reconstruction in a fresh worker resumes without duplicate
  inference after a saved receipt.
- Built wheels expose the documented imports and run the native examples without
  temporary workflow, agent or schema files or a mandatory Prosaic executable.

Use `.venv/bin/python -m pytest` and `.venv/bin/python -m build` in each affected
repository, plus its installed-wheel checks. Core Prosaic full tests retain their
immutable TypeScript differential oracle as required by its repository guidance;
production code remains Python. Use synthetic data and local endpoint fixtures.
No live provider credentials or product side effects are needed for acceptance.

## Supporting evidence

The [research note](../../../../prosaic/docs/2026-10-09-in-memory-workflow-research.md)
records the current constructor bypasses, shallow mutability probes, source
references, and 81 focused Harness plus 62 Runtime baseline tests. Those checks
verified the existing implementation, not the APIs defined here. Implementation
acceptance requires the full suites and wheel checks above.
