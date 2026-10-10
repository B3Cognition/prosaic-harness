# Harness package migration

The candidate distribution names are `b3-prosaic-harness` 0.7.1 and optional
`b3-prosaic-harness-postgres` 0.2.1. Harness selects
`b3-prosaic-runtime>=0.8,<0.9`; the PostgreSQL adapter selects
`b3-prosaic-harness>=0.7,<0.8`. Python imports and CLI commands remain
`prosaic_harness`, `prosaic_harness_postgres`, `prosaic-harness` and
`prosaic-harness-postgres`.

ALWAYS create a fresh virtual environment or consumer image for migration.
NEVER install the legacy and b3 distributions together: they share import paths,
and uninstalling one can remove files belonging to the other. ALWAYS retain
historical wheels and receipts separately; NEVER glob-install historical caches.
PyPI's unrelated `prosaic` distribution is not part of this ecosystem.

Before index publication, the release owner supplies a curated wheelhouse and
an explicit candidate manifest binding all five b3 wheel filenames and hashes
to their reviewed source commits. The Runtime 0.8 producer and final Harness
features remain prerequisites for this closure; metadata preparation alone
does not qualify the complete train.

```sh
python3 -m venv .venv-candidate
.venv-candidate/bin/python -m pip install --find-links /absolute/path/to/curated-wheelhouse \
  b3-prosaic-harness==0.7.1 b3-prosaic-harness-postgres==0.2.1
.venv-candidate/bin/prosaic-harness --help
.venv-candidate/bin/prosaic-harness-postgres --help
.venv-candidate/bin/python -I scripts/workflow_factory_smoke.py
```

After publication is verified, the same requirements resolve through the index
without `--find-links`. Current candidate artifacts are unpublished. ALWAYS run
the synthetic installed-wheel check from the matching candidate checkout;
NEVER interpret a local fixture pass as live-provider or database qualification.

Candidate source builds use an exact committed Git archive. Recursive source
documentation inclusion is safe only within that tracked snapshot; private,
untracked research and generated run data must stay outside the archive.
The packaging regression accepts `PROSAIC_RELEASE_REF` for a staged Git tree
before commit, and defaults to `HEAD` for committed-source verification.
