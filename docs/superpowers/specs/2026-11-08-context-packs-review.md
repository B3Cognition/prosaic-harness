# Context packs: adversarial design review

Date: 2026-11-08. Scope: design only, against Runtime v0.9.17 and Harness v0.9.12.
No product implementation, live inference, or runtime test execution is part of
this review. The [design](2026-11-08-context-packs-design.md) remains proposed.

## Method and baseline

Review the proposed API and state transitions against released source, not the
older local working trees. Walk concrete cases: revoked evidence in later history,
a validator returning a private value, crashes before/after dispatch and adoption,
oversized optional evidence, repeated source revisions, and restoring a frozen
selection with changed bindings. A fresh independent reviewer evaluated the whole
design and verified the guard/controller boundaries against the same releases.

Primary anchors:

- [History and receipt reducers](https://github.com/B3Cognition/prosaic-harness/blob/v0.9.12/src/prosaic_harness/session_contracts.py): portable history excludes old inputData; session and conversation receipt versions must match.
- [Controller checks and acceptance](https://github.com/B3Cognition/prosaic-harness/blob/v0.9.12/src/prosaic_harness/engine.py): validators receive full CheckContext, raw issue strings enter feedback/events, and controller validation follows durable Runtime receipts.
- [Conversation recovery](https://github.com/B3Cognition/prosaic-harness/blob/v0.9.12/src/prosaic_harness/conversation.py): same-attempt recovery and explicitly acknowledged retries have different resource transitions.
- [Context assembly](https://github.com/B3Cognition/prosaic-runtime/blob/v0.9.17/src/prosaic_runtime/context_assembly.py): current assembly finalizes a history selection and reserves execution readmission for one input.
- [Execution admission](https://github.com/B3Cognition/prosaic-runtime/blob/v0.9.17/src/prosaic_runtime/context_execution.py): actual payload readmission/counting and continuation fitting are Runtime responsibilities.
- [Session context](https://github.com/B3Cognition/prosaic-harness/blob/v0.9.12/src/prosaic_harness/session_context.py): cumulative work and closed v2 records cannot silently accept new fields or mismatched receipt versions.

## Findings and resolutions

| ID | Severity | Failure scenario | Design resolution |
| --- | --- | --- | --- |
| CP-01 | P1 | A revoked source's previous reader result is sent again through history without a new read or pack. | Retained per-turn exposure bindings, conservative authorization of the full retained history before later fitting/dispatch, denial without silent pruning, and separate viewing/reconciliation semantics. |
| CP-02 | P1 | A validator returns an issue string containing omitted private facts; the controller emits it immediately and sends it in the next attempt. | Whole-run safe-feedback-v1: closed codes by default, sealed source-independent static remediation catalog, and projection at every check/event/public-error boundary. No dynamic declassification in v1. |
| CP-03 | P2 | Recovery is assumed not to rerun validators, but the released controller validates after saving the Runtime receipt. | Preserve repeatable controller validation; only Runtime guard hooks are already settled. Explicit repeatable-validator attestations and frozen CheckContext; no invented exactly-once validation promise. |
| CP-04 | P1 | Two independent sources both use revision v1 and identical content; deduplication merges their attribution. | Include source identity/alias, item ID, both locators, revision, content and scope in evidence identity; opaque SDK citation IDs. |
| CP-05 | P2 | A large optional item makes an otherwise fitting required pack fail; max_variants=1 divides by zero. | Greedy whole-unit byte admission, explicit omission, bounded smaller variants, and a mandatory-only one-variant case. |
| CP-06 | P1 | Recovery can only reconstruct a variant by rerunning selection or reading private Runtime fields. | Public export_frozen_input/restore_turn seam, separate InputVariantSelection, exact wire/report verification at execution readmission, and no callbacks during restoration. |
| CP-07 | P2 | A session v3 receives receipt v2 even though the reducer requires equal versions; conversation v2 is already allocated. | Separate version table: conversation session/receipt v3; workflow checkpoint v3/receipt v2; distinct prepared encoding and proof versions. |
| CP-08 | P2 | Query-specific ranking changes a supposedly immutable registered pack specification. | Dynamic captures/ranks live in the snapshot; registered slots remain stable. Explicit ID order, source ranking, and stable-ID fallback have fixed precedence. |
| CP-09 | P2 | Every trial invokes the current finalizing assembler, duplicating readmission reservations or resetting work. | One Runtime fitting transaction, finalization only once, shared budget, headroom for final readmission, and verified-base selection before an unfunded optional trial. |
| CP-10 | P2 | Reader body limits ignore JSON escaping and provenance overhead, or cut a large JSON value into invalid data. | Separate raw-body/encoded-result limits, byte-safe text pagination, exact offsets, and whole-value/narrow-pointer JSON reads. |
| CP-11 | P2 | The design names a complete guard-facts snapshot but controller validators actually depend on a wider CheckContext. | Freeze the existing CheckContext shape independently; reconstruct it for existing validator APIs and include it in capacity admission. |
| CP-12 | P2 | An unguarded byte-only pack unnecessarily requires token counters/private-guard capabilities. | Conditional capability matrix and explicit denial only for requested unsupported semantics; no silent weakening. |
| CP-13 | P1 | The proposed frozen restoration lacks the current user message, which is absent from prior portable history, and has no host workspace parameter. | Frozen input explicitly retains exact current message/digest; restore accepts a separate readmitted host workspace where tools require it. |
| CP-14 | P2 | Current read authorization is required but its purpose is missing from the closed authorization enum. | Add retainedRead explicitly, separating viewing/replay from new inference authorization and internal receipt settlement. |
| CP-15 | P2 | A nested pack-envelope digest is confused with the digest of complete Runtime input_data, losing fixed controller fields or failing selection checks. | Preserve candidate index mapping and verify nested-pack and complete-input digests separately. |

The independent review initially identified CP-01, CP-02 and CP-03. The remaining
items were found by the primary review and checked against the same contracts.
Resolution means the intended behavior is now specified; it does not mean code
exists or the corresponding release tests have passed.

## Deliberate tradeoffs retained

- Initial composition/fitting is bounded pure work, but pre-persistence CPU work
  is not crash-durable. Same-attempt recovery preserves spent work; an explicitly
  acknowledged new retry has separate admitted execution allowance.
- History-first fitting may prefer retained conversation over optional evidence.
  It is an explicit initial policy, not a universal quality claim.
- Authorization covers a bounded logical invocation and rechecks deferred reads;
  cancellation can curtail in-flight work but cannot retract bytes already sent.
- Conservative history authorization may block a session after source revocation,
  even if some old turns would otherwise be omitted. V1 does not silently rewrite
  transcripts or claim to infer provenance from arbitrary domain-tool output.
- Private-access guards are fail-only. Model-only guards retain existing repairs
  and bounded retries. This closes ordinary output channels, not arbitrary trusted
  Python behavior or information disclosed by an authorized pass/fail result.
- Inline retention can hit state/receipt quotas before token limits. No new blob
  service or implicit increase of existing store limits is introduced. Installed
  qualification must prove a useful guarded case under default store limits.

## Required evidence before implementation can be called complete

The design's qualification section now includes explicit regression scenarios for
all findings above, installed legacy/opt-in paths, and a default-capacity witness.
Source tests, installed-wheel tests, file/PostgreSQL recovery and migrations remain
future implementation gates. Real-model quality/cost evaluation is separate from
contract correctness and requires explicit live-run authorization.

## Review status

Initial adversarial review: complete, consequential findings incorporated.
Final consistency re-review: complete. The independent reviewer found no remaining
consequential blockers in the authorization, restoration, feedback, recovery,
budgeting, capability, and record-version contracts after the last clarifications.
Documentation checks: UTF-8, final newlines, whitespace, fenced blocks, local
Markdown links, and revised-contract assertions passed; Git whitespace checks passed.
