# Versioned cross-step review validator V1

Execute natively. The maintainer approved this blueprint, tests, merge and release together with Runtime invocation headers; do not modify Cerebro itself.

Goal: ship a copyable application-owned review/revise/review workflow using existing Harness Validator and CheckContext APIs. No Runtime enforcement tags or new execution engine.

Contract: original host input contains `insights` with stable string `id` and `text`; first review returns `findings` with `insight_id` and `text`; revision returns the complete updated `insights`. Final findings must target an insight present in the revision that either appeared in first-review findings or has different text/is newly added relative to the original. Missing dependencies, duplicate/malformed IDs and invented original first-review IDs refuse. No client/model-supplied `changed_ids` may authorize a finding. This fixture's policy is an application example, not a generic SDK semantic assertion.

Files: `examples/revision-review/` with checks.py, workflow/runtime config, schemas, neutral paired ALWAYS/NEVER prose, synthetic request, opt-in runner/README; `tests/test_revision_review_blueprint.py`; release/install smoke and user docs. Preserve existing engine/identity contracts.

1. Watch failing tests before adding the blueprint: flagged unchanged accepts, changed/new accepts, untouched unflagged/deleted/invented refuses, duplicates/missing dependencies refuse, no mutation. Add real-loopback end-to-end refusal-feedback-correction and exhaustion, prior outputs unchanged, completed resume no extra requests, changed validator version refuses resume, stale declared dependency refuses.
2. Implement pure trusted checks and register explicit semantic+content versions through public Validator. Use declared required inputs for dependency freshness; revisions are schema checked before becoming accepted inputs. Copy the example to consuming apps before tailoring policy.
3. Run complete fresh source and installed-wheel tests including real blueprint inspection, schema and actual Runtime transport. Documentation records V1 limits and links to all deferred Cerebro requests (including workflow tags V2).
4. Prepare next unused Harness version, qualify against actually published feature Runtime/Core lineage. Exact-head overall SUCCESS, expected-head merge, equal tested/merged trees, original qualified artifacts only. Publish core distribution only, preserve PG store witnesses, verify anonymous bytes and fresh consumers.
