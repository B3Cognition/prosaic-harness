# Context packs: local qualification

The implementation is locally qualified and remains unpublished. Hosted promotion
gates, including native Intel macOS, are still required. The [machine-readable
manifest](2026-11-09-context-packs-qualification.json) binds exact source commits,
wheel/sdist hashes, unchanged witnesses and completed local results.

| Component | Candidate | Artifact source |
| --- | --- | --- |
| Runtime | 0.9.19.dev0 | `0262016cb884dbdf27772fb4e48374af9821be95` |
| Harness | 0.9.13.dev0 | `04e802f8a680297d376c6f367ed6094a947bf405` |
| Harness PostgreSQL | 0.4.2.dev0 | same Harness source |
| Lab consumer | isolated acceptance branch | `d65fb927d241943c393af5617a26797ba99cc63f` |

Core 0.5.0 and the original Runtime recorder 0.3.0 use their unchanged published
wheel bytes. They were not rebuilt or republished. Documentation/evidence commits
after the artifact source commits do not change these qualified artifact bytes.

## Actual results

- Runtime full source suite: **2,575 passed, 2 optional source-only skips**.
- Harness full source suite: **1,438 passed, 6 optional source-only skips**; one
  existing fork warning. The skips cover unconfigured installed/database source
  probes; their separately required installed and database gates passed.
- Both required installed pytest wrappers passed. Runtime installed metadata,
  distribution ownership and unchanged Core/recorder requirements passed.
- All **10** local platform/floor cells passed every installed SDK smoke and
  `pip check`: native macOS ARM Python 3.11/3.12/3.13 plus the 3.11 dependency floor;
  Linux ARM containers and explicitly emulated AMD64 containers on 3.11/3.12/3.13.
- PostgreSQL 16/18 ARM and emulated AMD64 each passed **233 adapter tests**, **5
  installed legacy lifecycle cases**, and the complete installed pack witness,
  without skips. Source-suite hosts are macOS ARM; server and clean-wheel child
  architecture are recorded separately in the manifest.
- Lab PostgreSQL 16 and 18 each passed **12 required context-pack cases**, with
  matching host/image payload audits, immutable candidate provenance and verified
  owned-stack cleanup.
- Both controlled legacy SDK overlays passed four pack-free smokes. Requesting
  packs with the released Runtime refused before authorization/effects. These
  deliberate no-dependency overlays do not claim supported dependency resolution.

The actual default-capacity witness retained 16 items, 68,055 snapshot bytes,
27,646 model bytes, 65,536 private-fact bytes and two 24,572-byte reader outcomes.
Its receipt occupied 460,488 bytes with 1,013,880 bytes reserved before effects,
under the unchanged 1 MiB receipt ceiling and 64 KiB output allowance. The installed
native regression also admits 8 KiB private facts behind a 4 KiB model-input limit,
then validates a later human node against the correct accepted artifact.

The [independent review](../decisions/2026-11-09-context-packs-final-review.md)
found three Important defects; each was reproduced and fixed with regressions,
then the full source/artifact gates above passed. There are no deferred minor
findings. The exhaustive [ruling register](../decisions/2026-11-08-context-packs-rulings.md)
preserves decisions, reasons and costs.

## Reproduction and limits

Use `scripts/context_pack_qualify.py` with the paired immutable release roots,
unchanged witness wheels, recorded constraints and a fresh output directory.
The locally retained wheelhouse is `dist/context-packs-04e802f` in this worktree;
it contains only the five selected SDK wheels, three candidate sdists, source
receipts and this qualification manifest. Install explicit candidate wheel paths
in a fresh environment; no sibling editable install constitutes wheel evidence.

The Lab command is documented in its `docs/context-packs.md`:

```sh
python -m lab_runner test --mode context-packs --candidate \
  --candidate-manifest /absolute/path/to/manifest.json \
  --consumer-image sha256:THE_QUALIFIED_IMAGE_ID
```

Historical Lab paid-evaluation approvals remain pinned to their reviewed SDKs.
A broad run under newer SDKs therefore is not a green historical-evaluation
claim. Two legacy conversation expectations also fail with unchanged published
wheels; those differences were reproduced separately. The adjacent nonhistorical
Lab source gate passed 957 cases, and the new required lane passed all its cases.

No paid/live model calls were made. Synthetic tests establish contracts,
disclosure, budgets and recovery; they do not establish answer quality, tokenizer
accuracy, latency or cost savings. The Lab guide contains the separately enabled
held-out evaluation plan. No branch was pushed, tagged or published. All eight
long-lived/final-lifecycle owned database fixtures were removed through their
ownership-aware helpers; unrelated engine resources and images were preserved.
