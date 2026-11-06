# Harness input-cap release plan

> **For agentic workers:** Use superpowers:executing-plans for native execution.

**Goal:** Commit the scoped cap changes, obtain green CI, merge and publish Harness 0.9.10.

**Architecture:** Additive read-only binding diagnostics; retain every existing
policy, identity and persistence contract. Promote the exact qualified tag bytes
through the existing selected-distribution release workflow.

**Tech Stack:** Python 3.11–3.13, pytest, setuptools, GitHub Actions, PyPI OIDC.

**Spec:** Maintainer's explicit commit/CI/merge/publish instruction in this chat;
session policy migration remains a separate change.

## Global constraints

- Base main `580d56bf005e653e6066c872dbdf333311d1763f`; latest release 0.9.9.
- Core 0.5.0 / Runtime 0.9.14 pins and adapter 0.4.1 stay unchanged.
- Preserve explicit tighter ordinary/interpreter caps, identity bytes, errors,
  stored sessions, receipts and recovery. No migrations or new automatic grants.
- Publish only Harness core; adapter builds are qualification witnesses.
- Preserve the original dirty checkout, previous releases and immutable artifacts.
- No live model calls or unrelated SDK/application changes.

## Review focus

- Effective cap uses the smaller value and the interpreter's independent policy.
- Diagnostics do not alter sealed bytes or enable policy migration.
- Source and wheel metadata/version pins agree; installed cap regressions run.
- Every required platform/Python/database/floor receipt passes without skipped gates.
- Promotion and public downloads preserve original candidate bytes and lineage.

## Task 1: Commit and prepare the versioned source

- [x] Commit only the five verified cap implementation/test/documentation files (`852da07`).
- [ ] Bump core to 0.9.10, update current install/release pins and retain historical notes.
- [ ] Run metadata/selection tests, full source suite, build and installed wheel checks.
- [ ] Commit the release metadata; push the branch and open a PR against main.
- [ ] Obtain whole-branch review and require all ordinary CI cells green.

## Task 2: Merge, qualify and publish

- [ ] Merge only the expected qualified head; verify source and merge trees match.
- [ ] Tag that exact source as v0.9.10 and require the full Publish SDK candidate gate.
- [ ] Verify the candidate's artifacts, 24 qualification records and upstream lineage.
- [ ] Promote candidate bytes with distribution=core; require PyPI and GitHub publication success.
- [ ] Verify actual public bytes, fresh installed cap tests and retained prior assets.

Actual run IDs, immutable hashes, commands and completion are retained in the
release assets and task-owned verification ledger; this plan states the gates.
