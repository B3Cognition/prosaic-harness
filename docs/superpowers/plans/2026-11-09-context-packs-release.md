# Context Packs Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The user selected native implementation and authorized merging and publication.

**Goal:** Publish the context-pack train after updating public documentation and merging Runtime, Harness and Lab in dependency order.

**Architecture:** Qualify stable artifacts from each exact merged commit, then promote those original bytes through the existing publication workflows. Lab consumes verified public wheels and makes context-pack acceptance mandatory for the stable train.

**Tech Stack:** Python, PostgreSQL, GitHub Actions, PyPI, checksum-pinned SDK manifests.

**Spec:** Runtime and Harness `docs/context-packs.md`, Lab `docs/context-packs.md`, and the user's instruction to update documentation, merge the three PRs and publish releases.

## Global Constraints

- Runtime 0.9.19; Harness 0.9.13; Harness PostgreSQL 0.4.2; Lab 0.9.12.
- Preserve Core 0.5.0 and the original Runtime PostgreSQL recorder 0.3.0 bytes.
- Merge Runtime PR26, Harness PR20 and Lab PR54 in dependency order.
- Publish only exact-source qualified original artifacts, with index digest verification.
- Preserve historical manifests, artifacts, release notes and earlier qualification evidence.
- Keep all native platform, installed-wheel, dependency-floor and PostgreSQL gates.
- Existing dirty main workspaces remain untouched; use the isolated feature trees.
- No new confirmation is required for the already authorized merges and publications.

## Review Focus

- Stable package versions must agree across metadata, workflows, installed tests and documentation.
- Publication tags must name the exact qualified merged commits; old development artifacts cannot be relabeled.
- Harness must consume the stable Runtime source and qualified original wheels.
- Released Lab context-pack acceptance must fail missing capability or tests and retain zero skips.
- Updating current SDK pins must preserve historical profiles and original recorder provenance.

### Task 1: Runtime stable release

- [ ] Replace active 0.9.19.dev0 references with 0.9.19 and retain historical evidence.
- [ ] Update README, changelog, release index and versioned release notes, including migration/compatibility.
- [ ] Verify package metadata and release tooling; push PR26 and await exact-head CI.
- [ ] Merge PR26 at the verified head; tag the merged commit and qualify the stable bytes.
- [ ] Promote qualified artifacts through Publish SDK; verify PyPI and GitHub release bytes.

### Task 2: Harness and PostgreSQL stable releases

- [ ] Finalize Harness 0.9.13 / adapter 0.4.2 versions, Runtime floor and source pin.
- [ ] Update both READMEs, changelog, release index and main/adapter release notes.
- [ ] Verify package metadata, release tooling and unchanged legacy paths; await PR20 CI.
- [ ] Merge PR20 after Runtime; qualify the merged source with final Runtime provenance.
- [ ] Publish Harness and adapter from the same qualified artifacts under their version tags.
- [ ] Verify both public distributions and release assets without replacing old versions.

### Task 3: Lab released-train activation

- [ ] Add failing tests requiring stable context-pack released-mode acceptance and preserved old trains.
- [ ] Support the stable train, released-mode context-pack execution and current public manifests.
- [ ] Preserve prior manifests/provenance; archive only genuine downloaded public bytes and hashes.
- [ ] Update Lab 0.9.12 metadata, README, changelog, release notes and consumer instructions.
- [ ] Run focused contracts and independent review of release-activation changes.
- [ ] Require all fresh PR54 source/distribution, rule, effort and owned-stack gates before merge.

### Task 4: Lab merge and publication

- [ ] Merge PR54 at the tested head after upstream publication; verify tested/merged tree equality.
- [ ] Require post-merge gates and retain original qualified Lab wheel/sdist from the released lane.
- [ ] Publish v0.9.12 with original CI payloads, checksums and sanitized qualification evidence.
- [ ] Verify anonymous public downloads and isolated wheel/rebuilt-source consumers.

### Task 5: Final verification

- [ ] Verify all PRs merged, all version tags point to expected commits, and release pages are published.
- [ ] Verify package indexes, current manifests, README links and release-note links agree.
- [ ] Report release URLs, versions, passing gates and any concrete unresolved limitation.
