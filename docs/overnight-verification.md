# Extended development verification — 2026-09-30

This campaign tests the unpushed development branches, not a new release.
Runtime code: `16047e9af51e46ff163ef4ea969427b49b52ee91`.
Harness code: `e024b0c9c65c8522f5bbe0bfd044e61967400f2c`.
Both repositories use `codex/tool-choice-enforcement`. Published versions and
Harness's immutable Runtime dependency pin remain unchanged; staged examples
need the explicit development override in [the examples guide](../examples/README.md).

## Full-suite rounds

Each round ran the entire Runtime and Harness pytest suites, not a selected
subset. Round 1 has console receipts. Rounds 2–16 have local JUnit receipts in
the ignored Harness directory `runs/overnight-20260930/round-NN/`.

| Round | Python | Hash seed | Runtime passed | Harness passed |
| --- | --- | --- | --- | --- |
| 1 | 3.12 | default | 115 | 75 |
| 2, verified rerun | 3.12 | 2 | 131 | 76 |
| 3 | 3.12 | 3 | 132 | 76 |
| 4 | 3.12 | 4 | 132 | 82 |
| 5 | 3.12 | 5 | 132 | 82 |
| 6 | 3.12 | 6 | 136 | 82 |
| 7 | 3.11 | 7 | 138 | 85 |
| 8 | 3.13 | 8 | 138 | 85 |
| 9 | 3.12 | 9 | 138 | 85 |
| 10 | 3.11 | 10 | 138 | 85 |
| 11 | 3.13 | 11 | 138 | 85 |
| 12 | 3.12 | 12 | 138 | 85 |
| 13 | 3.11 | 13 | 138 | 85 |
| 14 | 3.13 | 14 | 138 | 85 |
| 15 | 3.12 | 15 | 138 | 85 |
| 16, installed wheels | 3.12 | 16 | 138 | 85 |

Verified rounds have no skips. Round 2 initially failed a newly added admission
regression; the failure receipt remains in `round-02/harness.xml`. Its passing
rerun is `harness-verified.xml`, alongside `runtime-verified.xml`. New regression
tests also failed before their corresponding fixes. Thus this table records
verified full rounds, not a claim that every command ever issued passed.
Rounds 8–15 repeated the same final code across interpreter/hash combinations
without intermittent failures. Repetition is not independent proof of safety.

Reproduce a source round in each checkout (with the development dependencies
and Prosaic executable installed):

```sh
export PATH="/absolute/path/to/prosaic-harness/.venv/bin:$PATH"
PYTHONHASHSEED=15 .venv/bin/python -m pytest -q
```

The installed-wheel round used a fresh Python 3.12 environment, explicitly
installed both development wheels without resolving Harness's published Git pin,
installed pytest/PyYAML/jsonschema separately, and disabled pytest's source
`pythonpath` setting with `-o pythonpath=''`. Both import locations were verified
inside that environment's `site-packages`, rather than either source checkout.
Prosaic inspection used the installed companion CLI on PATH.

## Sequential fixes and edge cases

Each issue was handled separately: reproduce it, add a failing regression, fix
it, verify focused tests, then run both full suites before the next fix.

1. **Unknown usage and admission integrity.** Absent, malformed, incomplete,
   negative or boolean usage no longer becomes an authoritative zero/partial
   total. Genuine reported zero remains valid. A conversation with an unknown
   turn remains unknown, retaining known partial usage only as a diagnostic.
   Harness now checks resource guards after accounting but before accepting
   output, so unknown finite-budget usage, over-budget responses, deadline
   crossings and cancellation cannot leave an accepted artifact behind.
   Runtime `18d2e2e`; Harness `def2a32` and additional edge tests `e024b0c`.
2. **Serialized input limits without tools.** The plain request path now applies
   the configured input-byte limit to serialized request overhead as well as
   prompt content, before issuing HTTP. Runtime `523266e`.
3. **Credential-bearing inference redirects.** A two-server regression with a
   synthetic bearer demonstrated the redirect boundary. Public bounded Runtime
   inference now rejects redirects before any second-host request, for both
   tool and no-tool paths. No real key was used in this probe. Runtime `19680cf`.
4. **Prosaic inspection timeouts.** A timed-out external inspector now returns
   a bounded failed Result with `inspection_timeout`, rather than leaking a
   subprocess exception. Final and acquisition inspection are covered.
   Runtime `16047e9`.

Existing full-suite coverage also exercises interrupted-call recovery,
fingerprint/config binding, changed evidence, read path/hash/coverage checks,
tool-choice rejection, shared acquisition budgets, stale review versions,
malformed checkpoints, bounded repairs and human rejection. Tests are mostly
deterministic local HTTP/SSE and controller regressions, not live-model benchmarks.

## Larger Harness examples

`incident-staged-review.yml` and `incident-preloaded-review.yml` use three
synthetic incident documents totaling 8,334 bytes. They cover a misleading
reliability denominator, timeouts versus late server completion, unscored factual
correctness, unconfirmed causality, missing ownership, and quoted hostile
instructions. Neutral fragment/synthesis/reviewer prose, local admission checks,
bounded repairs, and explicit human resolution are included.

The staged blueprint acquires each file through its own controller-owned
fragment invocation; it does not depend on voluntary subsequent reads. An early
one-acquisition prototype correctly blocked when the model omitted the other
required files. The blueprint was strengthened, not its coverage validator
weakened. The preloaded blueprint supplies immutable source snapshots and
grants no native tools. The [examples guide](../examples/README.md) includes run,
config override, inspection and human-resume commands.

## Live TokenProxy results

Endpoint: `http://10.16.81.27:8080/v1`. Credentials came from `TOKENPROXY_KEY`;
no key or authorization header is committed. Local receipts are ignored under
`runs/overnight-20260930/`.

| Probe | Observed outcome |
| --- | --- |
| Incident staged controller | Human waiting; five invocations, three successful native reads |
| Incident preloaded | Human waiting; two invocations, zero native reads |
| All-model evidence matrix | 14/16 completed; both Ornith staged cases blocked on final formatting |
| Ornith staged with explicit JSON mode | 2/2 completed, streaming off/on; one invocation and one native read each |

Both incident workflows used balanced Qwen analysis and strong DeepSeek review.
Neither was human-approved, published or externally executed. Human waiting is
the intended pause, not final human acceptance.

The matrix tested Qwen, Ornith, DeepSeek and Nemotron with streaming off/on and
staged/preloaded modes, preserving identical source/schema/quote admission.
All eight staged cases performed native reads. All eight preloaded cases
completed without native reads. Ornith's two default staged cases prefixed JSON
with explanatory text, exhausting the two-attempt bound with no accepted output;
the matrix therefore exited 1. No automatic text extraction or fallback was
added. An explicit endpoint JSON-mode experiment then completed both Ornith
staged settings; configuration guidance is in the examples guide. Other models
were not retested with JSON mode enabled in that experiment.

These are small stochastic checks on this endpoint, not quality rankings or a
reliability benchmark. Matching byte receipts and source quotations do not
establish entailment, correct reasoning, or immunity to prompt injection. Tool
permission/scoping, controller admission and human authorization stay separate.

## Packaging and scope

Both sdists and wheels built successfully in a temporary output directory,
without overwriting published release artifacts. The Harness sdist includes the
new workflows, neutral prose, schemas and incident documents; Runtime includes
its acquisition examples. Local configuration and run receipts are excluded.
Development wheels retain the existing package version metadata and are test
artifacts only, not publication candidates. No push, tag or release was made.
