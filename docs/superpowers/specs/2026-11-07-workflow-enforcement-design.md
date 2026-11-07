# Workflow enforcement tags with accepted dependency facts

The maintainer explicitly requested implementation, testing, merge and release,
including an installed Lab blueprint and version-specific release notes. Execute
natively using the existing release process. This advances the previously
deferred workflow-tag V2; the existing versioned Validator API stays supported.

## Outcome and ownership

An agent step may bind Core's existing enforcement tags to trusted Runtime
Guards. A revised review can inspect the accepted first review and revision and
refuse findings on insights that were neither flagged nor changed. Harness owns
graph admission, dependency freshness, state, receipts and recovery. Runtime
0.9.16 already owns all four rule stages, fix/retry/fail, accounting and bounded
HTTP execution. Use its public guarded-turn API; do not copy an execution loop.
The flagged-or-changed predicate remains application-owned example code.

Release Harness, then adopt its actual public wheel in a new Lab release. Core
0.5.0 and Runtime 0.9.16 need no new package release for this bridge. Proposed
versions are Harness 0.9.12 and Lab 0.9.9, subject to availability checks. Preserve
published adapters, assets, tags and historical snapshots. No live inference or
Cerebro application changes. Other Cerebro backlog items remain separate.

## Host API and admission

- Extend `Workflow.load(..., guards=())` for trusted YAML and
  `WorkflowBindings(..., guards=(), rule_project=None,
  rule_project_identity=None)` for factory graphs. Own registrations using
  the existing Guard snapshot/descriptor convention. Registering an unused
  implementation grants nothing and adds no workflow identity material.
- Add `WorkflowPolicy.allowed_guards`, empty by default. A factory graph must
  name only host-registered, allowed guards. Required Runtime guard floors remain
  authoritative and cannot be dropped, weakened or retargeted by prose.
- Native registration and graph admission remain free of provider calls,
  executable discovery, Runtime construction and guard callbacks. Compile using
  public `prosaic_runtime.compile_rules` and the declared public functions in
  `prosaic_runtime.rules` (`artifact_rules`, `turn_rules`). Do not read private
  Runtime fields. Compilation may resolve confined paths under an explicitly
  supplied trusted rule project; it must not read policy file contents.
- Seal full used guard declarations, compiled rule material, the fact profile
  `workflow-guard-input-v1`, and logical rule-project identity. Native roots
  require an absolute host path and a logical identity; YAML uses its workflow
  directory. Compare current execution paths as well as portable identity when
  validating an injected Runtime. Used declaration/config/prose drift refuses.
- Standard ProsaicRuntime overrides must match admitted configuration, tool and
  guard declarations and effective paths. Unsupported RuntimeAdapter/native CLI/
  unified execution must refuse guarded graphs before state allocation or calls.
- Existing untagged workflow prompts, default policies, schemas, fingerprints,
  checkpoint version 2 and receipt version 1 remain byte-compatible. Omit all
  new guard fields when unused, including empty `allowed_guards` in policy
  identity. Keep Validator and CheckContext behavior unchanged.

## Finite limits and unsupported combinations

Guarded invocations require explicit finite request and tool caps. Native hosts
already have `WorkflowPolicy.max_provider_requests_per_invocation` and
`max_tool_calls_per_invocation`; require non-None values when guards are active.
Trusted YAML gains optional `limits.max_provider_requests_per_invocation` and
`max_tool_calls_per_invocation`, nonnegative integers excluding bool. Factory
proposals may only lower explicitly supplied host caps; they cannot create or
raise permission. Missing caps refuse guarded admission. Old omitted caps retain
their existing meaning for untagged workflows.

`max_calls` still counts Harness invocations, not individual HTTP requests.
Runtime repair shares each invocation's declared request/token/tool/deadline
allowance. A cap of one never authorizes a second request. This does not add the
separate repair allowance requested in the backlog. Rule retry exhaustion,
explicit fail and guard faults return terminal `rule_violation` for this step;
Harness does not start a fresh invocation to bypass a guard's terminal decision.
Schema/Validator retries retain their existing explicit max-attempt semantics.

Guarded steps use API turns. Reject acquisition, required file-read receipts, terminal tools and argument
interpolation (`{{args}}`) in guarded artifacts before effects; these have no
safe equivalent in Runtime's turn API. Preserve all existing untagged support.
Required tools, private workspaces, scopes, accounting attribution and recovery
remain authoritative for supported guarded steps. Public Runtime turn callbacks
omit file-read receipts, so guarded require_reads refuses admission; the untagged
read path remains supported. Pair observed custom-tool completions with their
already-readmitted sealed registration version. Advertise a
Harness `workflow_rules_v1` capability after the supported paths are tested.

## Guard facts and dispatch

At a guarded step, make a bounded owned input snapshot:

```json
{"workflow": {"version": 1, "step": "revised_review", "request": {},
  "artifacts": {"first_review": {}, "revision": {}},
  "artifact_bindings": {}, "sources": {}, "validation_feedback": ""}}
```

The contents come from the existing Harness arguments projection, adding only
the fixed profile version and current step. Optional human responses retain
their existing host-generated projection. Request data is nested and cannot
override step, artifacts, bindings or profile version. Only explicitly declared
required/optional input outputs are visible; absent optional inputs are omitted.
Any selected present stale dependency refuses before pending dispatch. Neither
model-claimed changed IDs nor arbitrary other workflow outputs enter authority.

Pass that snapshot as `Runtime.prepare_turn(input_data=...)` with a fixed message
asking the agent to execute the step from inputData.workflow. The same snapshot
is visible to guards as `GuardContext.input_data['workflow']`; Runtime already
provides private per-check copies. Pure preparation, exact request-size admission
and worst receipt-size reservation occur before incrementing attempts/calls or
persisting pending. Execute the prepared object with `Runtime.turn`, preserving
all current cancellation, observer, tool journal and frozen accounting context.
Runtime enforces before_tool, after_tool, before_answer and final as applicable;
schema/Validator admission remains required before accepting workflow output.

## Receipts and recovery

Keep existing receipt/checkpoint schemas. Guarded Result metadata contains a
closed bounded `workflow_rules_v1` extension: version, fact-snapshot SHA256,
prepared context identity and the existing IDs-only rule receipt (evaluated,
violated, fixed, faulted, fingerprint). It contains no raw dependency values,
prose, guard reasons or credentials. Reserve this extension before provider spend.

When adopting a guarded receipt, require its fact digest to match the pending
arguments/current step/profile and its rule fingerprint to match sealed rules.
Validate closed shapes and outcome subsets. A missing or malformed extension
cannot claim successful enforcement or advance output. Context identity is the
admitted prepared-turn hash, not a promise that a model obeyed anything. Existing
receipt identity binds run, invocation, arguments and workflow fingerprint.

Saved successful and refused receipts must replay without dispatch or additional
usage. A lost receipt after an uncertain call still requires explicit interrupted
retry consent; usage evidence is not consent. File and PostgreSQL stores use the
same extension contract. Changed versions/settings/prose/project identities or
earlier accepted dependency bindings must refuse resume or adoption as relevant.

## Blueprint and proof

Keep the released `revision-review` V1 blueprint unchanged. Add a separate
`workflow-enforcement` blueprint using the same synthetic insight policy, a
registered content-versioned final Guard and declared first-review/revision
inputs. It must show tagged refusal, bounded correction, successful flagged/
changed/new IDs, rejection of untouched/unknown/removed IDs, fault/fail behavior,
explicit approval, no-call replay and stale/version refusal. No domain predicate
belongs in generic Harness infrastructure.

Use both OpenAI-compatible and Anthropic loopback fixtures, source and fresh
installed wheels, YAML and factory graphs, all rule phases, floor/permission
refusal, mutable/oversized/invalid input, identity goldens and receipt fault
injection. Missing capability or limits must fail before state or inference.
Native-style tool steps and existing Validator tests remain unchanged.

The Lab adopts only the actually published Harness wheel with exact public URL,
source and SHA256, archives the prior manifests/profile/freezes byte-for-byte,
and retains all existing blueprints. New copy-out resources must ship in wheel,
source and safe consumer-image inventory. Require the full existing four Linux
AMD64/ARM64 x PG16/18 ordinary and rule/blueprint matrices, both reasoning jobs,
real PG recovery, public index and wheel/rebuilt-source consumers. No skipped
required infrastructure. Confirm cleanup and post-merge CI.

Release from exact-head overall GraphQL SUCCESS, an expected-head merge and
identical tested/merged trees. Harness publishes original qualified bytes with
Core/Runtime lineage. Lab publishes original successful CI archives. Verify
anonymous public hashes and clean installed/copy-out consumers. Release notes
state compatibility, identity/readmission, actual validation and live limits.
