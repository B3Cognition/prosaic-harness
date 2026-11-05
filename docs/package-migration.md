# Harness package migration

The published packages are `b3-prosaic-harness` **0.9.8** and optional
`b3-prosaic-harness-postgres` **0.4.1**. Harness requires
`b3-prosaic-runtime>=0.9.13,<0.10`; the PostgreSQL adapter requires
`b3-prosaic-harness>=0.9,<0.10`. Runtime 0.9.13 supplies the latest canonical
none/Gemma controls. Core is 0.5.0. Imports and CLI names remain
`prosaic_harness`, `prosaic_harness_postgres`, `prosaic-harness` and
`prosaic-harness-postgres`.

ALWAYS create a fresh environment or consumer image. NEVER install legacy and
`b3-` distributions together: they own the same import paths, and uninstalling
one can remove another's files. Preserve historical environments and receipts
separately. PyPI's unrelated `prosaic` distribution is not part of this ecosystem.

```sh
python3 -m venv .venv-harness
.venv-harness/bin/python -m pip install 'b3-prosaic==0.5.0' \
  'b3-prosaic-runtime==0.9.13' 'b3-prosaic-harness==0.9.8'
# Optional shared state; no database is initialized during installation:
.venv-harness/bin/python -m pip install 'b3-prosaic-harness-postgres==0.4.1'
.venv-harness/bin/python -m pip check
.venv-harness/bin/prosaic-harness --help
.venv-harness/bin/prosaic-harness-postgres --help
```

For reproducible deployments, select a complete checksum-pinned release manifest
and verify downloaded bytes before installing. Candidate wheelhouses apply only
to explicitly selected unpublished development versions, not these public releases.
The Integration Lab's [reasoning lane](https://github.com/B3Cognition/prosaic-integration-lab/blob/main/docs/reasoning-effort.md)
uses a separate manifest and environment; it does not silently replace its
ordinary integration baseline or certify all five packages on every platform.

Run installed smoke scripts from the matching source archive. Fixture success
does not qualify a live model, database deployment or storage configuration.
Candidate source builds use an exact committed archive. Keep private research,
untracked files and run data outside release archives. The packaging regression
accepts `PROSAIC_RELEASE_REF` for a staged Git tree and defaults to `HEAD`.
