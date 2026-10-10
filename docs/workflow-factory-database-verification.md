# Workflow factory database verification

Date: 2026-10-10. Both declared PostgreSQL majors passed the focused native
factory and existing RunStore integration checks against isolated disposable
loopback clusters. No live provider, global package installation, shared database
or Docker service was used.

| PostgreSQL server | Focused result | Native factory cases | Skips |
| --- | --- | --- | --- |
| 16.15 (Homebrew), arm64 | 24 passed in 21.98s | 3 passed | 0 |
| 18.6 (Homebrew), arm64 | 24 passed in 21.32s | 3 passed | 0 |

Each server's exact version was checked through a real SQL `SELECT version()`.
The test environment used psycopg's libpq client version `180006` (18.6). The
native cases verify reconstruction from a fresh factory, required and stale
human revision checks, successful resume, and adoption of both normal and
bounded failure receipts without another model dispatch. The remaining cases
exercise the real PostgreSQL store contract, engine lease loss and revision
guards, process death at durable edges, retry consent, and adoption after an
unknown receipt commit reply. These results cover the selected integration
checks; Docker-based standby and full crash-matrix gates were not rerun.

## Isolated setup and provenance

Official [Homebrew formula metadata](https://formulae.brew.sh/api/formula/postgresql@18.json)
selected the arm64 golden-gate bottles. Public GHCR downloads were SHA-256
verified before extraction. No authentication tokens were recorded.

| Bottle | Verified SHA-256 |
| --- | --- |
| PostgreSQL 16.15_1 | `d60d675afb25019c6fab16aac94d44b2410534123799d87dfbda6f1485ebbc8b` |
| PostgreSQL 18.6_1 | `c03f8a2999453ed0c4f0290daba750f25602e3f32ab694d99830c7d252868137` |
| OpenSSL 4.0.3 | `cfe1f3ee8ddafdb7f19fe4d4dd600e2b84257df4fa09a169ccb7322d38483f90` |
| krb5 1.22.2_2 | `678c05de46229f5b35631196808a7f6e4a32f9a18bc9574ec447f6c8290dfff7` |

All downloads, copied binaries, libraries and cluster data were owned by
`/private/tmp/prosaic-native-postgres.RQeFSk`. Existing Homebrew gettext, zstd,
lz4, ICU 78 and readline libraries were referenced read-only. Only extracted
Mach-O copies were relocated with `install_name_tool`; embedded install paths
were relocated to task-owned short symlinks and those copies were given ad-hoc
signatures. No installed Homebrew files were changed.

The clusters were initialized with UTF-8, locale C, synthetic superuser
`postgres`, local fixture trust authentication, and `dynamic_shared_memory_type=mmap`.
Explicit loopback listen addresses prevented exposure on other interfaces.
Sandbox escalation followed observed PostgreSQL shared-memory and loopback
socket denials and was limited to the disposable fixture and tests.

## Verification command

Run from the Harness repository, with `port=55461` for PostgreSQL 16 and
`port=55462` for PostgreSQL 18:

```sh
HARNESS_TEST_DATABASE_URL='host=127.0.0.1 port=55461 dbname=postgres user=postgres connect_timeout=3' PYTHONPATH=src:adapters/postgres/src .venv/bin/python -m pytest adapters/postgres/tests/test_native_factory.py adapters/postgres/tests/test_engine.py adapters/postgres/tests/test_store.py adapters/postgres/tests/test_recovery.py --require-postgres -q --tb=short
```

`--require-postgres` made a skipped fixture fail the verification lane. Fixtures
created and dropped only their own random test databases and roles. Model calls
were synthetic loopback fixtures.

## Ownership and shutdown

Historical owner-only commands used for these runs are recorded below. They
target only the exact task-created data directories; they never stop shared
Docker containers or unrelated PostgreSQL processes.

```sh
/private/tmp/pgn-RQeFSk/bin/pg_ctl -D /private/tmp/prosaic-native-postgres.RQeFSk/data -l /private/tmp/prosaic-native-postgres.RQeFSk/postgres.log -o '-h 127.0.0.1 -p 55461 -k /private/tmp/prosaic-native-postgres.RQeFSk -c max_connections=30 -c shared_buffers=32MB' -w start
/private/tmp/pgn18-RQeFSk/bin/pg_ctl -D /private/tmp/prosaic-native-postgres.RQeFSk/data18 -l /private/tmp/prosaic-native-postgres.RQeFSk/postgres18.log -o '-h 127.0.0.1 -p 55462 -k /private/tmp/prosaic-native-postgres.RQeFSk -c max_connections=30 -c shared_buffers=32MB' -w start
/private/tmp/pgn-RQeFSk/bin/pg_ctl -D /private/tmp/prosaic-native-postgres.RQeFSk/data -m fast -w stop
/private/tmp/pgn18-RQeFSk/bin/pg_ctl -D /private/tmp/prosaic-native-postgres.RQeFSk/data18 -m fast -w stop
```

Both stop commands completed successfully with `server stopped`; subsequent
`pg_ctl status` checks for each exact data directory returned `no server running`
(exit 3). Both data directories, all verified archives and extracted binaries,
download metadata and helper scripts, and the four task-owned short symlinks
were then removed. Cleanup assertions verified their removal. Only the two
small server logs remain in `/private/tmp/prosaic-native-postgres.RQeFSk` (about
21 KiB combined); this repository report preserves the durable evidence.
