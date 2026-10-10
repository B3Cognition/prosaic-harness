# Workflow factory execution ledger

Plan: [2026-10-09-workflow-factory.md](2026-10-09-workflow-factory.md).
Normative spec: [production MVP](../specs/2026-10-09-workflow-mvp-design.md).

- Design revision saved after authorized cleanup of 158 Echelon test directories.
- Feature branches: `codex/validated-workflow-factory` in Core, Runtime and Harness.
- Native worktree creation previously failed ENOSPC. Existing feature branches
  provide branch isolation; unrelated research and production files preserved.
- Ruling: execute after design update without another approval pause because the
  user explicitly authorized this sequence. Cost if wrong: reversible local code.
- Ruling: use existing feature checkouts rather than move three repositories into
  separate new worktrees after the disk blocker. Cost if wrong: less checkout
  isolation; agents have separate file ownership and no main-branch changes.
- Ruling: pure helper components may be implemented in parallel in disjoint files
  with fixed interfaces; root owns integration. Cost if wrong: interface rework,
  covered by final integration tests/review.
- Task 1: Core helper complete, 34 new tests, full suite 466 passed; immutable
  TypeScript migration oracle passed (13 suites / 55 original tests).
- Task 2: Runtime helper complete, 39 new tests, full suite 495 passed / 1 skipped.
- Task 3: JSON/schema helpers and shared legacy loader complete. Independent review
  fixes cover boolean reference positions, scoped IDs and instance-limit errors;
  historical deeper/recursive schemas, defaults and captured YAML identity pass.
- Task 4: Public factory/shared graph complete, 61 focused factory tests passed.
  Independent review fixes cover model-tier names, per-root schema budgets,
  typed resource copying, registration snapshots and validator-version bounds.
- Task 5: Mandatory admission, private cwd and bounded recovery complete. Native
  execution tests cover independent seals, adapter mutation, malformed/oversized
  returned results, ledger completion, terminal byte/node reserves and adoption.
- Task 6: Installed wheels and public offline example pass on Python 3.12/current
  dependencies and Python 3.11/jsonschema4.23/referencing0.28.4. Each uses one native
  tool call, two local provider requests and no invocation during fresh resume.
  Full Harness suite: 337 passed on Python 3.12; 333 full-suite plus the final
  4 composition cases passed on the minimum Python 3.11 dependency lane.
  All implementation/review/packaging tasks are complete locally; normal release
  CI and publishing remain separate from the authorized implementation.
- Baseline Harness sandbox run: 121 passed, 51 localhost-binding setup errors.
  Permitted offline localhost baseline rerun: 172 passed in 38.65 seconds.
- Real PostgreSQL16 verification: 24 passed, zero skips, including all three native
  factory cases and existing store/controller/receipt/crash recovery checks.
- Real PostgreSQL18 verification: same 24 passed, zero skips. Both owned servers,
  downloaded binaries/archives and data directories were stopped and removed.
- Native worker verification: two isolated processes rebuild the same admission,
  preserve the receipt and resume a validated human response without inference.
- Local dependency commits: Core `737bc0f4e6b5d3bd7bd370f2c0d408bc89eb494f`,
  Runtime `833ace8dc01c125e653e451287d2fcc316b33627`; Harness pins updated in order.
- Local candidate versions: Core 0.3.2, Runtime 0.7.1, Harness 0.6.2; PostgreSQL adapter
  remains 0.1.1 with compatible `>=0.6,<0.7` Harness requirement.
- Final evidence: [verification record](../../workflow-factory-verification.md).
- No live provider, push, merge or release authorized or performed.
