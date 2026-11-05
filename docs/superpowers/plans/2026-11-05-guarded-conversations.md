# Guarded conversations across Harness and Lab

The user approved the companion scope proposed in this chat: preserve rule policy
and composed inspection rules, register host guards through admission and resume,
retain rule outcomes in durable receipts, then qualify the installed SDKs in Lab
PR #45. Implement inline. Keep existing unguarded identities and receipt bytes
unchanged. Never add retries or weaken saved regression expectations. No live
providers, release, merge, or changes to the author's branches.

## Review focus

- Composed rules may exist only in inspection metadata: never reconstruct them solely from body tags.
- Mutable caller policy/guard containers must not change admitted bindings; changed guard declarations must invalidate resume.
- Interpreter phases must enforce the same host floor, without inheriting tool authority.
- Failed guarded turns must persist/replay without repeating model calls or effects.
- Receipt metadata must be closed, bounded and validated before storage, including context receipts and malformed hashes/IDs.

## Task 1: Preserve and admit policy, artifacts and guards

Files: `factory.py`, `conversation_bindings.py`, new `conversation_rules.py`,
`tests/test_conversation_rules.py`.

Add failing tests for lost floors and composed rules, successful registered
enforcement, declaration/version drift, owned aliases, interpreter rules and
unchanged unguarded identity. Add optional `guards=()` to ConversationBindings;
store host callables in memory and only their complete descriptors in binding
identity. Reconstruct guards using public Runtime Guard fields to validate them.
Use those guards at initial admission, readmission and execution. Preserve
nonempty required_guards/rules/ruleIssues in shared config/artifact snapshots.
Run saved compatibility tests and existing binding/factory tests.

## Task 2: Durable bounded rule receipts

Files: `session_contracts.py`, `conversation_rules.py`,
`tests/test_conversation_rules.py`, `tests/test_session_contracts.py`.

Watch ruleViolation receipt failures first. Admit ruleViolation in session failure
validation; include optional `rules` containing evaluated/violated/fixed/faulted
IDs and fingerprint when nonempty. Validate closed shape, UTF-8, cardinality,
subset relations, hash and structural bounds; keep existing receipt capacity
checks and old receipts unchanged. Test actual failures, replay and recovery on
memory/file stores, context receipt compatibility and invalid metadata.

## Task 3: Installed SDK Lab candidate and acceptance

Lab branch starts at PR #45 `44539fd`. Re-pin Core to released 0.5.0 and Runtime
to exact fixed PR #16 `498ffc7`, with verified wheel hashes. Include the exact
Harness companion commit as an explicitly labelled local candidate. Update the
candidate builder and audit tests to admit that third candidate. Preserve the
ordinary/reasoning manifests. Add a copyable Harness host wrapper and acceptance
tests using public installed APIs, synthetic OpenAI-compatible and Anthropic
wires, file-store replay/recovery, custom guard fixes/fails, floors and composed
rules. Carry the two value-guard probes and magnitude controls into Lab.
Document remaining fee grammar limits honestly (three strict expected failures).

## Task 4: Qualification and handoff

Run full Harness and Lab default suites in their declared environments, full
candidate acceptance, builds, installed-wheel checks, saved regressions and
dependency audit. Use available owned PostgreSQL fixture tooling for store
qualification; record unavailable infrastructure explicitly. Review the complete
diff and leave local branches/commits with exact versions, test counts and limits.

## Progress

- Baseline: Harness 0f18ae9, Lab 44539fd, Runtime 498ffc7, Core 0.5.0.
- Saved Harness tests were observed red: 3 failed, 1 passed (2026-11-05).
- Lab baseline installed-wheel acceptance: 120 passed, 3 expected failures.
- Tasks 1/2 focused verification: 189 passed; recovery/context follow-up 47 passed.
- Independent review found and reproduced guard path-root drift, legacy converter
  downgrade, valid faulted-without-violated results, duplicate rule IDs and source
  symlink redirection. Each gained a failing regression before its fix. Final
  root/recovery/legacy subset: 50 passed. Published Runtime smoke retains
  unguarded admission and refuses composed rules before legacy conversion.
- PostgreSQL 18: all three lifecycle cases passed, including guarded receipt recovery.
- Full first run: 1015 passed, 2 skipped, two historical workflow identity failures.
  Both also failed on unchanged Harness main with Runtime #16. Ruling: omit only
  the new empty required_guards field from legacy runtime identity (as already
  done for absent effort/sandbox controls); do not update golden expectations.
