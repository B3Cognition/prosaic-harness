# Research: resolving the in-memory workflow design review

The [production MVP design](2026-10-09-workflow-mvp-design.md) incorporates these
findings and the subsequent production review. Its contracts supersede the
preliminary recommendations below.

Date: 2026-10-09. Status: recommendations for revising the design; no production
implementation. Companion to [the proposed factory design](2026-10-09-in-memory-workflow-design.md).

The four findings are substantive. They expose gaps between the proposed
admission guarantees and the components that would execute an admitted graph.
The overall split between a proposal, host policy and private bindings remains
appropriate. No caller needs a `base_dir`, and valid prose still does not grant
tools or other host capabilities.

## Recommended decisions

| Finding | Recommended resolution | Main consequence |
| --- | --- | --- |
| Runtime override can change the execution configuration | Compare the actual adapter's execution configuration with the admitted configuration, in addition to capabilities, descriptors and validator versions | Factory workflows require an identifiable adapter; existing legacy test adapters remain compatible |
| Frontmatter validation misses classification and execution constraints | Add an explicit-type canonical helper in Prosaic and a pure execution-artifact helper in Runtime | The work needs a small Runtime API addition, reversing the current spec's assumption that none is necessary |
| Native construction can discover unrelated CLI manifests | Derive an owned native configuration with `tool_directories=()`, then seal and execute that configuration | Mixed host configuration remains usable without CLI reads or probes on the native path |
| Schema validity does not establish safe evaluation | Start with host-approved catalogue schemas; defer arbitrary client-authored inline schemas and centralize admission/evaluation handling | This narrows the proposed first-delivery schema scope; trusted applications can still generate schemas in memory |

The confirmed model-tier rule remains unchanged: omitting `model_tier` selects
the host default even with an empty or named-tier-only allowlist. That default
must be sealed and checked against the adapter actually used.

## Evidence and scope of the probes

Source review used Prosaic `ee145ef`, Runtime `109df2c` and Harness's factory
specification commit `69da014`, plus the subsequent model-tier clarification.
Python probes used Python 3.12.14 and jsonschema 4.26.0. Canonical classification
and Runtime identity probes were also repeated with all three repositories'
working source directories on `PYTHONPATH`. The CLI and schema probes used the
Harness environment's installed Runtime 0.7.0 and jsonschema. No model endpoint
or product callback was invoked.

| Probe | Observed result |
| --- | --- |
| Two Runtime instances differing only in model | Capabilities and tool descriptors equal; `runtime_identity(config)` differs |
| Mutate a nested endpoint feature in a frozen RuntimeConfig | Mutation succeeds and is visible through the Runtime instance |
| Validate outer `subagent` with frontmatter `type: rule` and `effort: unrecognized` | `validate_frontmatter` and `ProsaicArtifact.from_inspection` accept it; file-based `classify` detects the type conflict |
| Construct Runtime with a nonexistent configured CLI directory | Constructor raises `FileNotFoundError`, even without requesting a CLI tool |
| Construct with an independently derived configuration whose directories are empty | CLI loader receives an empty tuple; original configuration retains its directories |
| Schema `{"$ref":"#/missing"}` | Metaschema check succeeds; evaluation raises `_WrappedReferencingError` |
| Schema `{"$ref":"#"}` | Metaschema check succeeds; evaluation raises `RecursionError` |
| Local `$defs` reference, anchor reference, and productive recursive object schema | All evaluate successfully on suitable instances |
| External reference with explicit empty `referencing.Registry()` | Evaluation fails without a retrieval implementation |
| `{"type":"string","pattern":"^(a+)+$"}` against 30 `a` characters followed by `!` | A separate research process exceeded two seconds and was terminated; the schema is 40 JSON bytes and the instance 31 characters |

The regex probe is deliberately run in a disposable subprocess with a parent
timeout. It demonstrates that schema byte and JSON-depth bounds alone do not
bound evaluation time. It is not a benchmark or a production isolation design.

## 1. Bind the identity to the Runtime that will execute

Harness currently constructs or accepts an adapter in
[engine.py](../../../src/prosaic_harness/engine.py), while its tool checks concern
capabilities and descriptors. Runtime selects profiles, routes, features and
limits from its own `config`. Therefore two adapters can pass those checks and
execute different models or endpoints.

Use the existing
[`runtime_identity`](../../../src/prosaic_harness/workflow.py) representation for
configuration comparison. Preserve its legacy omission rules and fingerprint
recipe. Do not create a second abbreviated list of model-related fields: provider,
endpoint, model, default profile, routes, features, credential selectors, response
bounds, allowed tools and applicable sandbox settings all belong in the comparison.
Actual rotating credential bytes remain outside identity.

For factory workflows:

1. Admission snapshots and validates an owned effective RuntimeConfig.
2. The default adapter is constructed from an independent copy of that snapshot.
3. An injected ProsaicRuntime must expose a valid RuntimeConfig whose canonical
   identity equals the admitted identity. Recompute from its live configuration;
   a constructor-time hash is insufficient for shallowly frozen mappings.
4. An opaque adapter must provide a documented, versioned execution-identity
   protocol returning the same finite canonical configuration representation.
   Reject adapters without it on the factory path. Do not infer their identity
   from the workflow being handed to them.
5. Verify admission and adapter identity at public `run`, `resume` and `status`
   boundaries, and before issuing each new invocation. An initial mismatch must
   cause no store write, model call or callback. Readmission must not recompute a
   supplied fingerprint to silently authorize different bindings.

The proposed protocol is a contract with trusted host code, not an attestation
against a dishonest adapter. Callables already execute in the host trust domain.
Document that mutating an executing adapter concurrently is unsupported; default
factory execution must own its configuration and avoid shared mutable instances.

Retain the current no-config fake-adapter behavior for legacy loaded workflows.
When a legacy adapter exposes a real RuntimeConfig, compare it too. This closes
the concrete misconfiguration case without requiring every existing fake runtime
to pretend to have endpoint configuration. New factory adapters receive the
stricter contract explicitly.

Tool descriptor comparison remains scoped to the descriptors sealed for resolved
prose. Extra unused host registrations must not cause rejection or enter identity
merely because an injected adapter exposes them. Required validator versions keep
their existing checkpoint checks.

Acceptance tests should vary model, endpoint, provider, routes/default, features,
limits and grants separately; test nested mutation after Harness construction;
reject unidentified factory adapters; accept a matching identified adapter; and
retain representative legacy fake-runtime tests. A mismatch must also fail before
receipt adoption or a resumed model call.

## 2. Separate canonical artifact admission from executable admission

Prosaic discovery performs parsing, classification and frontmatter validation.
Exporting only `validate_frontmatter` omits classification. Its permissive string
`effort` field is intentional distribution behavior and should not be narrowed to
Runtime's current execution values in the canonical parser.

Add a public pure Prosaic helper, provisionally
`validate_artifact_definition(kind, frontmatter)`, which validates a supported
explicit artifact kind, agreement with `frontmatter.type` when present, and the
existing kind-specific frontmatter contract. Absent `frontmatter.type` is valid
when the caller supplies an explicit kind. Retain unknown extension metadata.
Do not synthesize a filesystem path from a logical alias to run directory-based
classification, or insert a missing `type` and thereby change content digests.
Share the type-agreement logic with discovery while preserving its existing
classification diagnostics and differential behavior.

Runtime should expose a second pure helper, provisionally
`validate_execution_artifact(artifact, config)`. It should reuse the inspection
structure contract and the execution checks currently scattered through `_run`:
supported executable kind, supported tool declaration syntax, supported effort,
and route/default selection. Validate known provider restrictions against the
selected endpoint as well: currently Anthropic rejects supplied effort metadata,
even if its value is one of Runtime's generic supported values. The helper must
not construct a Runtime, inspect files, discover CLI manifests, perform version
probes, render a model request through a transport, or invoke callbacks.

Harness combines those checks with policy and resolved registry checks. Registry
discovery and CLI preflight remain separate operations on the legacy path.
Invocation-dependent checks such as rendered prompt size and actual tool argument
validation remain execution checks; early admission cannot know future arguments.
Runtime execution should call its helper too, so the early and late supported
metadata rules cannot drift.

Apply these checks to inline agents, typed host catalogue artifacts, final agents
and acquisition artifacts where the legacy adapter supports them. A dataclass
instance is not evidence of admission. Invalid executable metadata should fail
before Harness persists a pending invocation. Leave unsupported arbitrary endpoint
behavior to execution; the helper cannot certify a remote model's capabilities.

Regression coverage needs conflicting/unknown kinds, absent explicit metadata,
invalid required frontmatter, malformed tool declarations, invalid effort,
missing routes, and known provider incompatibilities. Core parser/discovery
compatibility and legacy artifact digests are explicit regression gates.

## 3. Derive the native configuration without CLI preparation

Runtime's constructor eagerly calls `load_cli_tools(config.tool_directories)`.
Constructing it just to obtain native descriptors cannot satisfy the proposed pure
construction boundary. Native descriptor admission should call the existing pure
`validate_custom_tools`/descriptor functions directly, exposed as supported
Runtime APIs rather than relying on private fields.

Derive a separate configuration snapshot for the factory's native execution mode:

```python
native_config = replace(owned_host_config, tool_directories=())
```

Validate and seal this effective configuration and pass exactly it to execution.
Document this as explicit native binding semantics. Do not mutate the host config,
read directories to discover which names are CLI tools, or hash the original
directory configuration while executing a different configuration.

Retain other host settings, including `allowed_tools`, rather than deriving grants
from whichever registry entries happen to exist. The effective step grant is the
intersection of prose, step, policy, host configuration and registered native
tools. The registration supplies an implementation, not permission. Keeping
grants independent also avoids making unused registry changes alter identity.

Native construction then has no CLI registrations. Prose requests for names that
are neither recognized builtins nor registered native tools fail admission, even
if the host's full CLI configuration would have defined them. Known filesystem
builtin requests may remain inert prose metadata, but dynamic steps cannot grant
them. A host-registered native callback is still trusted host code, regardless of
whether its name happens to resemble a CLI tool elsewhere.

Correct the spec's broad claim about retaining ungranted requests: legacy CLI
requests are preflighted before grant intersection and missing grants fail.
The existing `test_cli_preflight_fails_before_endpoint_request` explicitly verifies
this. Preserve that behavior; do not suppress CLI preflight to make a dynamic
proposal appear admissible.

An injected Runtime constructed from the full mixed configuration fails the
native configuration identity check. Hosts can use the factory's default adapter
or construct an override from the admitted effective configuration. Add an explicit
check for a nonempty `cli_tool_names` set on native overrides; configuration equality
alone must not accept an adapter that retained previously discovered CLI bindings.
The default construction never discovers them in the first place.

Compared alternatives: rejecting all host configs containing directories is
simple but makes a service manually maintain duplicate configs. Adding a general
lazy Runtime preparation lifecycle is broader than necessary. Deriving the native
configuration is the smallest solution compatible with the intended service case.

Test mixed configs with missing directories, invalid manifests and native/CLI name
collisions without reading those assets. Spy on discovery/probe functions and
callbacks to establish the effect boundary. Keep the existing legacy CLI and
sandbox tests, and verify temporary execution directories never enter identity.

## 4. Treat schema admission and schema evaluation as separate problems

`Draft202012Validator.check_schema` checks conformance to a metaschema. It does not
prove that referenced targets exist or that evaluation terminates cheaply. The
JSON Schema specification explicitly discusses recursive loops and excessive
resource use, and its validation vocabulary warns about expensive regular
expressions. [Core recursion rules](https://json-schema.org/draft/2020-12/json-schema-core#section-9.4.1),
[core security considerations](https://json-schema.org/draft/2020-12/json-schema-core#section-13),
[validation security considerations](https://json-schema.org/draft/2020-12/json-schema-validation#section-10).

Use an explicit in-memory `referencing.Registry` with retrieval disabled for
admission and every evaluation. Resolve references with the library's resource
and scope semantics, including local IDs and anchors; a string beginning with `#`
does not prove its target exists. Walk schema positions, not arbitrary data in
`enum`, `const` or examples. Fix the dialect to Draft 2020-12 for new admission,
including nested resources, rather than allowing an unexpected dialect switch.
Do not install a custom client resolver or format callback.
[Official referencing configuration](https://python-jsonschema.readthedocs.io/en/stable/referencing/).

Recommended first-delivery boundary: proposed graphs reference approved catalogue
schemas. Trusted application code may generate schemas in memory and register
them in that catalogue; host registration is an explicit trust decision. This
preserves the original trusted-assembly use case and the generated-graph specialist
composition use case. A generated proposal cannot promote its own schema into the
catalogue merely by choosing an alias. Defer `inline_schemas` and
`allow_inline_schemas` from the released factory API until their execution safety
contract is implemented; do not ship a flag that appears to authorize arbitrary
schemas safely. This is a proposed scope change to the companion spec.

For the new factory's initial schema reference profile, support acyclic local
static `$ref` reuse and reject `$dynamicRef` and reference/evaluation cycles
conservatively. This avoids promising complete static progress analysis. Ordinary
`$defs` schemas used in the current examples remain supported. Productive recursive
schemas are legitimate, as the probe demonstrates; restricting them is a documented
new-factory limitation, not a claim that they are invalid JSON Schema. Keep existing
trusted YAML reference behavior and its fingerprint inputs compatible. Relaxing
the new profile should accompany bounded evaluation, rather than a weaker loop
check. Approved regex-bearing catalogue schemas remain a host trust responsibility;
this proposal does not claim that arbitrary full JSON Schema is safe in-process.

Centralize evaluation in a Harness facility used by agent-output acceptance,
pending-receipt adoption, human response validation, and stored human-decision
validation in `contracts.py`. Bound input bytes, finite JSON nesting and emitted
diagnostics; stop after the required number of errors rather than materializing
the entire `iter_errors` generator. These bounds reduce work but are not a hard
CPU timeout. Clearly distinguish an invalid instance from a schema-evaluation
failure such as a resolver exception or recursion failure. Sanitize failure
messages, retaining field locations instead of raw schemas or values.

On a schema-evaluation failure after a persisted model receipt, retain the receipt
and completed invocation ledger, save a terminal blocked reason such as
`schema_error`, and do not schedule another model attempt. Recovery must adopt the
same receipt and reach the same blocked outcome if the process stopped before
saving that outcome. Resume cannot repeatedly invoke the model to repair a broken
schema. For a human response, reject before recording the choice; checkpoint
validation must return a controlled failure and remain read-only. Normal invalid
model output retains existing bounded correction-attempt behavior.

Three future choices are viable, with different scope:

| Client schema support | Cost and limitation |
| --- | --- |
| Approved catalogue references only | Recommended first delivery; arbitrary client-defined output shapes are unavailable |
| Explicit restricted generated-schema profile | Can permit simple object/array/type/enum/bounds contracts; needs a reviewed keyword admission profile excluding regex, references and expensive composition, plus structural work/input bounds. Keep the official evaluator; do not implement a replacement JSON Schema engine |
| General Draft 2020-12 schemas | Needs killable, resource-limited evaluation, explicit no-retrieval resolution, instance/error bounds, concurrency limits and durable timeout outcomes across every evaluation path |

A thread or executor timeout alone does not stop a running regex validator. A
general-schema worker must be disposable, receive only bounded JSON, have no
product callbacks or credentials passed to it, and never own store state or host
locks. Killing a worker can damage shared synchronization primitives, so shared
queues/locks must not become reusable state after a timeout. Parent-owned deadlines,
worker termination/reaping and platform-specific memory-limit behavior need
dedicated verification. Admission in a worker would also change the current
spec's pure construction/effect boundary and must be documented separately.
[Python process termination semantics](https://docs.python.org/3.11/library/multiprocessing.html#multiprocessing.Process.terminate).

Schema acceptance cases should include missing pointers and anchors, reference
targets that are not schemas, self/mutual references, nested IDs/dialects, external
references with retrieval spies, valid local `$defs`, productive recursion under
the legacy contract, and known regex/composition hazards under any future generated
profile. Exercise successful/failed response validation and interrupted receipt
adoption, proving no duplicate model call. Run these against the supported minimum
jsonschema dependency and the tested current version.

## Implementation ordering after design revision

1. Amend the companion spec with the decisions above, especially the adapter
   protocol and narrower initial schema scope. Define safe admission error codes
   for configuration mismatch, invalid execution metadata and schema failures.
2. Add the pure Prosaic type/frontmatter helper and Runtime execution/registry APIs.
   Gate them with core differential compatibility and Runtime execution tests.
3. Extract shared Harness resolved validation and schema admission/evaluation;
   preserve exact legacy YAML identities and existing recovery behavior.
4. Add private snapshots and native config derivation, then the factory and JSON
   envelope. Make default and injected execution pass the same mandatory checks.
5. Add factory admission, mutation and recovery regressions, followed by full
   suites, builds and installed-wheel smoke tests in dependency order. Update VCS
   pins only after the prerequisite APIs exist in reviewed commits.

No product source file or existing Opta workflow is required. Use neutral local
HTTP fixtures and native specialist tools to demonstrate agent composition,
selection/review pauses, schema references and recovery. Product authorization
remains in the host callbacks.

## Verification performed for this research

Runtime baseline:

```text
.venv/bin/python -m pytest tests/test_custom_tools.py tests/test_config.py tests/test_cli_tools.py tests/test_anthropic.py -q
116 passed in 26.06s
```

Harness baseline:

```text
.venv/bin/python -m pytest tests/test_validation.py tests/test_custom_tools.py tests/test_human_responses.py tests/test_recovery_contracts.py -q
37 passed in 6.92s
```

These are current-behavior compatibility baselines, not proof that the proposed
resolutions are implemented. No production files were changed, no live endpoint
was used, and no build/wheel claim is made for a documentation-only investigation.
