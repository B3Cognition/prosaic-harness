# Workflow enforcement implementation and release plan

> **For agentic workers:** Use superpowers:executing-plans for approved native execution. One fresh whole-branch review follows implementation. Steps use checkbox tracking.

**Goal:** Release workflow enforcement tags over accepted earlier outputs, with a new copyable Lab blueprint and version-specific notes.

**Architecture:** Harness compiles and seals trusted Guard registrations, projects bounded fresh dependency facts, and prepares/executes Runtime's existing guarded turns. Runtime 0.9.16 remains the only rule execution engine. Untagged workflows and the Validator V1 example retain their contracts and identities.

**Tech Stack:** Python 3.12; Core 0.5.0; Runtime 0.9.16; new Harness 0.9.12 and Lab 0.9.9 if free; existing published recorder 0.3.0/store 0.4.1.

**Spec:** `../specs/2026-11-07-workflow-enforcement-design.md` (maintainer-authorized native scope; fresh builder check: nothing important left).

## Global constraints

- Use only public Runtime APIs, including explicitly exported `prosaic_runtime.rules` functions; never copy a tool loop, rule evaluator, transport or accounting engine.
- No live inference, Cerebro integration edits, unrelated cleanup or changes to normal dirty checkouts/original companion worktrees. Preserve all prior release bytes, tags, snapshots and saved regression assertions.
- Empty/unused guard additions must not change released untagged workflow, default policy or bundle identity. Versioned Validators continue to work alongside tags.
- Guarded calls require finite explicit request/tool caps; no independent repair allowance or silent budget increase. Exhausted/faulted/fail rules do not acquire a new Harness retry.
- Guard facts contain only the host request and declared fresh accepted dependencies; no model-authored claim supplies authority. Preparation and receipt reservation precede pending allocation.
- Version notes declare identity/readmission and actual qualification limits. Require exact-head overall SUCCESS, expected-head merge, equal trees, original qualified bytes, public proof and post-merge CI.

## Review focus

- Inline/composed/tag metadata and required floors cannot bypass pure admission or registration permissions; all four Runtime hook phases remain enforced.
- Changed accepted dependency versions and optional stale outputs cannot silently become authoritative guard facts during replay or repair.
- Guarded adapter/config/project/declaration drift must fail before effects; immutable host registration snapshots and versioned bundles must reconstruct correctly.
- Tiny caps, malformed receipts and callbacks that mutate their private JSON views cannot strand pending work or erase safely retained accounting usage.
- Every old untagged prompt/fingerprint/bundle fixture and V1 validator remains compatible; installed copy-out execution must not depend on ambient PATH or source checkouts.

## Task 1: Guarded workflow admission and identity

**Files:** new `src/prosaic_harness/workflow_rules.py`; modify `workflow.py`, `factory.py`, `graph_admission.py`; tests `tests/test_workflow_rules_admission.py`, `tests/test_workflow_bundles.py`, `tests/test_workflow_factory.py`.

**Interfaces:** `Workflow.load(..., guards=())`; `WorkflowBindings(..., guards=(), rule_project=None, rule_project_identity=None)`; `WorkflowPolicy.allowed_guards`; optional root limits `max_provider_requests_per_invocation`, `max_tool_calls_per_invocation`. Internal owned rule registration/material helpers live in workflow_rules.py and reuse the existing conversation registration/descriptor conventions.

- [ ] Capture released no-guard YAML/native/bundle identity and prompt goldens before changes. Write failures for allowed/bound/floor admission, missing/invalid caps, unsupported combinations, malformed tags, guard/project/adapter drift, unused registrations and pure callback-free admission.
- [ ] Add bounded owned registrations, public compilation, full used descriptors, logical roots, safe omission and guard-policy intersection. Extend native frozen factory copies and bundle material; new guard-bearing bundles seal their complete host registrations, while old no-guard bundles stay byte-compatible.
- [ ] Trusted YAML may specify nonnegative finite invocation caps. Factory proposals only lower explicit host caps; missing native host caps never gain permission through the proposal. Seal only nondefault additions.
- [ ] Reject tagged acquisition, terminal, args interpolation and unsupported adapters before state/effects. Compare actual public Runtime compiled rules/declarations/paths with the admitted expected rules on readmission.
- [ ] Run the focused admission/factory/bundle tests and observe complete green before commit.

## Task 2: Guarded execution and durable rule evidence

**Files:** `workflow_rules.py`, `engine.py`, `contracts.py`, `observations.py` if a new stable reason requires it; tests `tests/test_workflow_rules_execution.py`, `tests/test_workflow_rules_recovery.py`.

**Interfaces:** version-1 facts at `GuardContext.input_data['workflow']`; fixed message plus owned inputData through public `prepare_turn`/`turn`; Result metadata `workflow_rules_v1` with version, fact SHA256, prepared context identity and validated IDs-only rule receipt. Existing receipt/checkpoint schema versions remain.

- [ ] Watch both-wire failures for accepted flagged/changed/new findings and rejected untouched/unknown/removed findings; assert only declared fresh dependencies, immutable private guard views, all hook phases, fix/fail/retry/fault and request-cap1 refusal.
- [ ] Prepare exact guarded input/policy before invocation ledger/pending allocation. Use Runtime's prepared turn with accounting, observation, tool journal, cancellation and scope; keep the untagged `.run` path exact. Finite TurnLimits must honor configured invocation/output/metadata bounds.
- [ ] Reserve worst rule metadata/receipt size before spend. Persist bounded proof and known usage on both success and terminal rule refusal; block `rule_violation` without outer repair bypass. Keep schema/Validator acceptance mandatory.
- [ ] Validate receipt proof against pending arguments/current step/profile/sealed rule fingerprint on adoption. Malformed/missing/mismatched proof cannot advance. Preserve small valid proof/accounting when applying returned-result size fallbacks; admission rejects caps that cannot retain the required proof.
- [ ] Inject failures before dispatch, after response/before receipt, after receipt/before acceptance and around schema/guard callbacks. Saved receipts replay without new provider calls; uncertain pending calls require explicit retry consent. Verify file-store and hosted PG16/18 recovery.
- [ ] Run complete affected Harness source tests, including existing conversations, terminal/native tools, stores, observation and accounting tests, then commit.

## Task 3: Copyable SDK blueprint and Harness release

**Files:** new `examples/workflow-enforcement/` with host checks, tagged paired ALWAYS/NEVER prose, schemas, YAML/factory construction and opt-in runner; test `tests/test_workflow_enforcement_blueprint.py`; update root/examples READMEs, `docs/cerebro-requests.md`, capability docs, `docs/release-0.9.12.md`, changelog, version metadata/assertions and publish/test lineage.

**Interfaces:** preserve `examples/revision-review/` V1 bytes. New example uses a content-versioned final Guard, original request plus accepted first_review/revision inputs, explicit caps and no-ambient-PATH CLI selection. Expose `workflow_rules_v1` on Harness's documented capability surface.

- [ ] Add copied blueprint RED tests before resources. Prove real rejection/correction/exhaustion/approval/replay/version/freshness behavior on both supported synthetic wires, using public installed APIs.
- [ ] Document max_calls as invocations and the explicit per-invocation provider/tool limits; no repair budget is inferred. Keep all other Cerebro backlog items deferred.
- [ ] Verify next free version and current released Core/Runtime lineage. Build fresh source/installed-wheel consumers and strict payload/metadata audits. Run full source plus required PG/OS/Python gates; obtain the one fresh whole-branch review and fix actionable findings with watched regressions.
- [ ] Push final ready source, require all exact-head checks SUCCESS, expected-head merge and tree equality. Qualify exact merged source, promote original successful Publish SDK bytes with Core/Runtime lineage, core distribution only. Verify anonymous GitHub/PyPI hashes and clean installed blueprint consumers; preserve adapter witnesses.

## Task 4: Lab adoption, blueprint and release

**Files:** Lab `dependencies/releases*.json`, quality profiles/memory freezes and selectors, gates.py, new `lab_runner/blueprints/workflow_enforcement/`, package data/public-build inventory, `tests/blueprint_acceptance/test_workflow_enforcement.py`, required PG workflow lane, current READMEs/guides/changelog/feature map, `docs/release-0.9.9.md`, handoff/progress and verification.

**Interfaces:** actual published Harness 0.9.12 public URL/source/SHA256; Runtime 0.9.16/Core 0.5.0 and original adapters. New `workflow-enforcement` copy CLI entry; existing four blueprints remain supported.

- [ ] Watch feature capability refusal against released Harness 0.9.11; author candidate checks only in an explicitly separate environment. Do not claim a local candidate is a published dependency.
- [ ] Archive current manifests/profile/freezes byte-for-byte as pre-workflow-enforcement, add the exact released family to all capability allowlists, repin actually published bytes, refresh only active provenance/freezes and prove old profile selection.
- [ ] Ship and execute copied V2 resources through isolated wheel and rebuilt source. Cover both wires, admission/floors/budgets, declared input scope, replay/fault/version/staleness and both PG majors; do not skip required infrastructure. Extend the existing four-cell feature/PG lane and public distribution gates.
- [ ] Update every current README/release note/feature map and retain historical evidence. Full source, frontend, installed tests and whole-branch review precede one final-ready push; require all ten final-head jobs and exact overall SUCCESS.
- [ ] Verify original CI ZIP/artifact hashes and exact source/merged trees; publish original archives for the next free version. Verify anonymous downloads, fresh published wheel/rebuilt-source consumers, historical preservation and all post-merge checks. Record versions, PR/release links, limits and completion in the private cross-repository state file.
