# Production MVP review: validated workflow construction

Date: 2026-10-09. Verdict: revise the design before implementation planning.

This review checks the [factory specification](2026-10-09-in-memory-workflow-design.md)
and [resolution research](2026-10-09-workflow-review-resolutions.md) against the
current Prosaic, Runtime and Harness implementations. Three independent reviewers
covered bindings/admission, schemas/recovery, and bounded work/compatibility. Their
findings were checked against source and small offline probes. There is no factory
implementation to certify yet; passing baseline tests is not evidence of production
readiness for these proposed APIs.

The original four findings have credible remedies, but those remedies leave seven
contracts needing revision. These are design gaps, not claims that an unimplemented
factory already contains exploitable code. The first three concern service
availability or execution admission and should be settled before adding APIs.

## 1. [P1] Factory admission must not fall back to legacy privileges

The specification retains valid manual `Workflow` construction and requires
readmission, while the research permits unidentified adapters for legacy workflows.
It never positively defines the legacy admission path or an independent original
factory seal. Today, `Workflow` contains mutable path, definition, configuration
and fingerprint fields; there is no origin contract to reuse.

References: specification lines 271–286 and 359–363; research lines 68–93;
[workflow.py](../../../src/prosaic_harness/workflow.py),
[Harness construction](../../../src/prosaic_harness/engine.py).

An implementation must not interpret missing factory metadata, a changed path or
a caller-recomputed fingerprint as permission to use legacy adapter exceptions.
Nor should recomputing a correct hash authorize a mutation to an already admitted
factory workflow.

Require an owned admission record with fixed origin, original content seal,
effective policy and private bindings. Factory identity must agree with both that
original record and freshly validated resolved content. Missing or inconsistent
factory provenance fails closed. A distinct internal factory workflow type is
also a viable way to retain the origin distinction; a private boolean alone is
not proof of validation.

Define trusted manual legacy admission explicitly. Preserve valid released manual
construction, but do not use absence of factory metadata as its only admission
criterion. Copying a factory object must retain its admission contract or require
reconstruction through the factory. This protects against malformed proposals and
accidental host assembly, not malicious Python capable of replacing the library.

Test stripped/replaced records, copied workflows, changed paths and mutations with
recomputed fingerprints at constructor/run/resume/status boundaries. None may
write state, adopt a receipt or execute. Positively admitted YAML and its existing
fake-adapter fixtures must still work.

## 2. [P1] Admission needs a work budget before copying or hashing

Depth and eventual serialized size do not bound traversal of an aliased Python
mapping. Repeating `value = [value, value]` fifty times creates only 51 containers
and stays below depth 64, but naive traversal expands roughly 2^50 occurrences.
Such data can enter `build(mapping)` through frontmatter or a gate's `equals`.

References: specification lines 135–136, 215–218 and 232–233;
[Runtime's current JSON depth helper](../../../../prosaic-runtime/src/prosaic_runtime/tools.py).

The safe smaller probe, with 18 unique containers, visited 262,143 expanded nodes
and produced 786,428 serialized bytes. The eventual byte check is too late if the
same algorithm is used for larger shared subtrees.

Require an iterative finite-JSON preflight with a traversal/expanded-size budget
before deepcopy, dataclass conversion, serialization or hashing. A bounded walk
may stop when its work budget is exhausted; alternatively, memoize subtree sizes
and reject excessive expanded size without expanding repeatedly. Reject cycles.
Rejecting all repeated container identities is simpler, but would also reject
benign host sharing, so document that choice if selected. Do not silently apply
a tree-only restriction to the entire host catalogue without considering aliases.

Bound raw input bytes before `build_json` decoding. Convert parser depth,
recursion, Unicode, duplicate-key and numeric failures into safe admission errors,
then perform bounded semantic preflight. This does not require writing a new JSON
parser. The work budget belongs in the sealed dynamic admission profile.

Tests need a 50-level alias DAG, ordinary bounded sharing, cycles, raw JSON deeper
than the configured limit and invalid Unicode/numbers. Prove failure before copying
or hashing, without making tests themselves perform exponential work.

## 3. [P1] Completed responses need a durable receipt budget

Runtime's default response byte limit equals the store's 8 MiB document limit.
A receipt also contains arguments, events and metadata. Harness saves it before
checking the 100,000-byte output JSON limit. A completed invocation can therefore
fail receipt persistence and look interrupted on restart.

References: specification lines 359–363 and 439–443; research lines 246–262;
[receipt creation](../../../src/prosaic_harness/engine.py),
[document encoding](../../../src/prosaic_harness/run_store.py),
[file serialization](../../../src/prosaic_harness/store.py).

File storage also measures two encodings. `encode_document` uses compact UTF-8
JSON; `write_json` uses indentation and ASCII escapes. A sealed probe with
1,500,000 `é` characters passed the first check at 3,000,135 bytes, but the latter
representation requires 9,000,153 bytes. The UTF-8 payload and compact preflight
document fit the default transport/store limits, yet the representation the file
adapter writes exceeds its limit.

Give dynamic execution explicit aggregate budgets for returned result, persisted
events, metadata and the complete receipt. Measure the exact representation that
will be stored, with a consistent storage contract and envelope headroom. Limit
individual event fields and aggregate event bytes, not just event count. Align
provider/output bounds with that envelope instead of raising the store limit.

If a returned result exceeds its admitted budget, create a bounded failure receipt
that preserves invocation identity and safely available usage/accounting data,
without presenting truncated stdout as a valid result. Save that receipt, complete
the ledger and block with a defined limit reason. Account for oversized metadata
and events as well as stdout/stderr. Do not accidentally swallow store failures
or claim durable recovery when storage itself is unavailable.

This bounds failures caused by returned data. A crash after remote completion but
before any receipt commit remains genuinely ambiguous; preserve explicit
interrupted-call handling and do not promise exactly-once model or tool execution.

Test oversized ASCII/Unicode, metadata, event fields and aggregate events in file
and database adapters. Crash after the bounded failure receipt is saved and prove
fresh-worker recovery completes the ledger without another invocation. Retain
existing checkpoint/receipt versions, seals and reads of historical documents.

## 4. [P2] Run inputs and invocation preparation need their own bounds

The policy bounds workflow construction data, but `Harness.run(inputs)` currently
only hashes the inputs. It saves an initial checkpoint, then copies the request
into pending arguments and persists pending state before Runtime checks prompt
size. Output fan-in and human-response history can also make later arguments large.

References: specification lines 228–248;
[run admission and dispatch preparation](../../../src/prosaic_harness/engine.py),
[Runtime prompt/conversation checks](../../../../prosaic-runtime/src/prosaic_runtime/runtime.py).

A pure size probe with a 4.3 MB request fit an initial sealed document and exceeded
the 8 MiB limit when copied into pending arguments. Separately, the proposed
524,288-byte artifact allowance exceeds Runtime's default 262,144-byte input bound.
A sufficiently large approved artifact can fail before any model request but after
pending state was written. The subsequent missing receipt is ambiguous to recovery.

Specify and seal separate dynamic execution bounds for run inputs, human response
instances and prepared invocation arguments/prompt. Validate request JSON before
the first state write using the bounded preflight from finding 2. Reject artifacts
whose minimum rendered prompt is already impossible under the execution bound.

Check the actual arguments and rendered prompt after fan-in and response-history
assembly, before incrementing calls/attempts or saving pending dispatch. Excessive
fan-in should produce a controlled input-limit outcome without an invocation.
Runtime retains its wire-payload/conversation checks and can return a durable
runtime limit failure when later tool turns exhaust that budget.

The implementation plan must choose concrete defaults and verify that all admitted
state/receipt envelopes fit the existing store limit. Reusing the proposal byte
bound for every execution input without calculating envelope overhead is insufficient.

Test oversized/deep/aliased/nonfinite run inputs, large approved artifacts, many
bounded inputs feeding one agent, and growing human-response history. Initial
input rejection creates no state; pre-dispatch exhaustion creates no pending
invocation, call increment or external request. Existing YAML input semantics need
their own compatibility treatment rather than silently acquiring new limits.

## 5. [P2] Schema resolution must be isolated and unambiguous

The research specifies correct reference scope but does not prohibit duplicate
resource identifiers/anchors or define registry ownership. Both affect behavior
without necessarily affecting the sorted content fingerprint.

References: research lines 216–221 and 235–238; specification lines 346–348;
[sorted digest](../../../src/prosaic_harness/workflow.py).

Reproduced with jsonschema 4.26.0 and an explicit empty Registry: two `$defs` have
`$anchor: same`, one requiring a string and one an integer. Reversing their mapping
order changes whether integer `1` is accepted, while `check_schema` accepts both
and their Harness digests are identical. An unused catalogue document can likewise
override a used document's nested `$id` when both enter a shared registry.

Use an isolated no-retrieval registry for each resolved schema root. On the new
factory path, reject duplicate canonical resource IDs and anchors within their
resource scope before evaluation. Resolve only that root's approved internal
resources. Unused catalogue entries must have no effect on its evaluator. Canonical
sorting is not a substitute for rejecting ambiguous declarations.

Tests should reorder duplicate declarations and always reject; add unused resources
with colliding IDs and preserve used-schema behavior/identity; retain unique anchors,
nested local IDs and current `$defs` fixtures. Keep legacy reference acceptance
separate where preserving released behavior requires it.

## 6. [P2] Define evaluation profiles and recovery reason precedence

The shared evaluation recommendation adds nesting limits to historical human
decisions while preserving YAML identities and checkpoints. A 70-container,
142-byte response can pass the current checkpoint contract. Imposing the proposed
64-container bound during legacy status/resume would strand it under an unchanged
fingerprint.

References: research lines 246–262; specification lines 332–334;
[stored human-decision validation](../../../src/prosaic_harness/contracts.py).

Seal a versioned evaluation profile in dynamic admission identity: dialect,
reference restrictions and acceptance-affecting instance/work bounds. Apply dynamic
bounds consistently to output acceptance, receipt adoption, new human responses and
stored decisions. Preserve released legacy acceptance semantics and fingerprints.
Dependency upgrades require compatibility fixtures; they must not silently change
the meaning of an existing profile. Package version alone is not an evaluation
contract, and must not be added to legacy fingerprint recipes.

The research also promises the identical `schema_error` outcome after interrupted
receipt processing. Existing `_accept` checks resource conditions first. If saving
`schema_error` is interrupted and the deadline then passes, adoption of the same
receipt can instead block with `run_deadline`. Cancellation produces the same
precedence issue.

Keep the existing precedence for the MVP and amend the promise: adopt the immutable
saved receipt, retain a completed ledger, accept no output and make no additional
invocation; a resource reason may take precedence over schema evaluation. A schema
error is terminal when reached and saved. This fits the current state/store formats.

Test historical deep/recursive valid YAML responses, changed dynamic profiles,
minimum/current jsonschema compatibility, and interrupted schema-error saves with
advancing clocks/cancellation. Repeated resume, including `retry_interrupted=True`,
must not cause a new invocation after a saved receipt.

## 7. [P2] Acquisition validation needs the final execution context

The proposed pure execution helper takes `(artifact, config)`, yet the research
also requires it for acquisitions. Acquisition execution inherits the final
artifact's route/effort when those fields are omitted. Validating it independently
against the host default can select the wrong provider and reject a valid YAML flow.

References: research lines 123–129 and 140–144;
[Runtime route inheritance](../../../../prosaic-runtime/src/prosaic_runtime/runtime.py),
[legacy acquisition metadata checks](../../../src/prosaic_harness/workflow.py).

Concrete case: default Anthropic; final agent selects an OpenAI route with
`effort: low`; acquisition supplies the same effort and omits its tier. Current
execution uses OpenAI. Independent validation would select Anthropic and reject
its unsupported effort metadata.

Resolve the final invocation context once, and validate acquisitions against it,
keeping existing explicit-metadata agreement rules and artifact digests. Validate
provider behavior against effective features after Runtime's deliberate feature
overrides. Test omitted/matching/conflicting acquisition metadata, mixed-provider
default/routes and overridden configured features. No dynamic acquisition support
is needed for this MVP; the issue is preserving the trusted YAML path during
shared-validation extraction.

## A smaller, coherent MVP

Keep the public factory, host catalogue, native bindings, mandatory policy, all
existing graph step kinds, separate composition/inline-agent permissions, private
temporary execution directories, and both store modes. Client graphs reference
host-approved schemas and native implementations. Trusted code may generate
schemas in memory and register them as approved catalogue content.

Defer arbitrary client schemas, dynamic filesystem/CLI/resource materialization,
an opaque adapter identity protocol, and the unused new `workspace` option. Trusted
YAML retains its existing directories, resources and adapter compatibility.
Factory execution can initially use Harness-created ProsaicRuntime or a supported
standard override with matching live configuration/descriptors and no loaded CLI
tools. Define whether subclasses are supported; do not accidentally promise every
duck-typed adapter. These exclusions do not prevent either requested use case.

Host-approved schemas may retain useful regex and combinators. Hosts must vet their
worst-case behavior on bounded model/human data; native tool parameter schemas need
the same treatment. Do not describe arbitrary approved JSON Schema as automatically
safe to evaluate. General untrusted-schema support needs a separate bounded evaluator
contract. Trusted callbacks/validators also remain cooperative host code.

State limit semantics plainly: call/visit/byte limits are enforced bounds; token
limits stop progress based on reported usage and one invocation can overshoot;
deadlines include human-wait time and prevent further progress, but cannot forcibly
preempt native handlers, validators or in-process schema evaluation. Exactly-once
remote effects and generic product authorization are outside Harness's guarantees.
The confirmed omitted-model-tier rule remains unchanged.

## Production release gate

A production MVP needs one amended normative spec; the existing spec and research
currently make conflicting promises. Resolve the findings and scope above, then
write implementation tasks. Release evidence must establish all of the following:

| Gate | Required evidence |
| --- | --- |
| Admission and bindings | Fail-closed origin, original seal, bounded work, all policy/grant intersections, live Runtime match and no CLI discovery on native paths |
| Input and storage bounds | Concrete sealed input/prompt/result/event/receipt limits; exact serialization bounds; durable limit failures and no preflight-created pending calls |
| Schema semantics | Isolated registries, duplicate rejection, resolved local references, explicit dynamic evaluation profile, and preserved legacy acceptance |
| Effects and cleanup | No construction I/O/models/handlers/validators; private cwd never becomes controlled prompt/event data; cleanup on success, pause, cancellation and exception |
| Recovery | Crash injection at pending, normal/failure receipt, adoption and transition; deadline/cancellation precedence; no duplicate inference after a saved receipt |
| Concurrency | Store lease/revision and competing worker/human-action tests; immutable reusable factory snapshots; no concurrently shared mutable Harness/Runtime |
| Legacy compatibility | Exact YAML fingerprints and default omissions; historical version-2 checkpoints/receipt version 1; reads/acquisition/CLI/sandbox and manual-adapter regressions |
| Installed distribution | Full affected suites, supported Python matrix, core differential oracle, clean installed wheels, public import/example smoke without Node or mandatory Prosaic CLI on the native path |
| Dependency/service integration | Immutable pins in dependency order and a neutral installed-package consumer fixture covering approved specialist composition, pause, fresh-worker reconstruction and safe projection |

Existing integration-lab released-dependency gates should remain intact. Candidate
factory tests supplement them; they do not establish that current released packages
already provide the new APIs. No live provider credentials or product side effects
are needed for these gates.

## Verification limits for this review

The duplicate-anchor hash/evaluation difference was independently repeated in the
Harness environment using jsonschema 4.26.0. Reviewer probes also exercised alias
expansion, receipt encodings, run-input duplication, registry contamination,
historical response depth and resource precedence using bounded synthetic data.
No live endpoint or product callback was used, and no production source was changed.

One additional filesystem-backed prompt probe could not start because the host
reported no space for a temporary file. Its proposed failure sequence is supported
by source tracing; it is not reported as a successful execution probe. Remaining
checks used in-memory probes. No new full-suite/build/wheel readiness claim is made.
