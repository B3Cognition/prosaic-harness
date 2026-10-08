import json
import os
from pathlib import Path
import subprocess
import sys

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
import pytest


def run_cli(*args, dsn=None):
    env = {key: value for key, value in os.environ.items() if key in {'PATH', 'HOME', 'LANG', 'SYSTEMROOT'}}
    if dsn:
        env['TEST_HARNESS_DSN'] = dsn
    return subprocess.run([sys.executable, '-m', 'prosaic_harness_postgres.cli', *args,
        '--dsn-env', 'TEST_HARNESS_DSN'], env=env, capture_output=True, text=True, timeout=40)


def grant_runtime(admin_dsn, runtime_dsn):
    role = sql.Identifier(conninfo_to_dict(runtime_dsn)['user'])
    with psycopg.connect(admin_dsn) as admin:
        admin.execute(sql.SQL('GRANT USAGE ON SCHEMA prosaic_harness TO {}').format(role))
        admin.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA prosaic_harness TO {}').format(role))
        admin.execute(sql.SQL('GRANT INSERT, UPDATE ON prosaic_harness.runs, prosaic_harness.leases TO {}').format(role))
        admin.execute(sql.SQL('GRANT INSERT ON prosaic_harness.receipts TO {}').format(role))


def test_missing_secret_is_safe():
    result = run_cli('doctor')
    assert result.returncode != 0 and 'store_unavailable' in result.stderr
    assert 'Traceback' not in result.stderr


def test_invalid_secret_redacted():
    result = run_cli('doctor', dsn='invalid_DSN_SECRET_SENTINEL')
    assert result.returncode != 0 and 'SECRET_SENTINEL' not in result.stdout + result.stderr
    assert 'Traceback' not in result.stderr
    assert 'store_unavailable' in result.stderr


def test_init_twice_and_read_only_doctor(db_admin_dsn):
    for _ in range(2):
        result = run_cli('init', dsn=db_admin_dsn)
        assert result.returncode == 0, result.stderr
    with psycopg.connect(db_admin_dsn) as admin:
        before = admin.execute('SELECT * FROM prosaic_harness.schema_version').fetchall()
    result = run_cli('doctor', dsn=db_admin_dsn)
    assert result.returncode == 0, result.stderr
    with psycopg.connect(db_admin_dsn) as admin:
        assert admin.execute('SELECT * FROM prosaic_harness.schema_version').fetchall() == before
        for table in ['runs', 'leases', 'receipts']:
            assert admin.execute(sql.SQL('SELECT count(*) FROM prosaic_harness.{}').format(sql.Identifier(table))).fetchone()[0] == 0


def test_runtime_role_does_not_migrate_or_delete(db_admin_dsn, runtime_dsn):
    assert run_cli('init', dsn=db_admin_dsn).returncode == 0
    grant_runtime(db_admin_dsn, runtime_dsn)
    assert run_cli('doctor', dsn=runtime_dsn).returncode == 0
    denied = run_cli('init', dsn=runtime_dsn)
    assert denied.returncode != 0 and 'store_incompatible' in denied.stderr
    denied = run_cli('doctor', '--check-write', dsn=runtime_dsn)
    assert denied.returncode != 0 and 'store_incompatible' in denied.stderr
    with psycopg.connect(db_admin_dsn) as admin:
        assert admin.execute('SELECT count(*) FROM prosaic_harness.leases').fetchone()[0] == 0


def test_explicit_write_diagnostic_cleans_exact_owned_rows(db_admin_dsn):
    assert run_cli('init', dsn=db_admin_dsn).returncode == 0
    result = run_cli('doctor', '--check-write', dsn=db_admin_dsn)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['write_checked'] is True
    with psycopg.connect(db_admin_dsn) as admin:
        for table in ['runs', 'leases', 'receipts']:
            assert admin.execute(sql.SQL('SELECT count(*) FROM prosaic_harness.{}').format(sql.Identifier(table))).fetchone()[0] == 0


def test_doctor_incompatible_schema_is_safe(db_admin_dsn):
    assert run_cli('init', dsn=db_admin_dsn).returncode == 0
    with psycopg.connect(db_admin_dsn) as admin:
        admin.execute('UPDATE prosaic_harness.schema_version SET schema_version=99')
    result = run_cli('doctor', dsn=db_admin_dsn)
    assert result.returncode != 0 and 'store_incompatible' in result.stderr
    assert 'Traceback' not in result.stderr


def test_runtime_credentials_cannot_initialize_new_schema(runtime_dsn):
    result = run_cli('init', dsn=runtime_dsn)
    assert result.returncode != 0 and 'store_incompatible' in result.stderr


def test_cleanup_failure_is_not_reported_as_success(db_admin_dsn):
    assert run_cli('init', dsn=db_admin_dsn).returncode == 0
    with psycopg.connect(db_admin_dsn) as admin:
        admin.execute("CREATE FUNCTION public.reject_cleanup() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'SECRET_SENTINEL'; END $$")
        admin.execute('CREATE TRIGGER reject_cleanup BEFORE DELETE ON prosaic_harness.receipts FOR EACH ROW EXECUTE FUNCTION public.reject_cleanup()')
    result = run_cli('doctor', '--check-write', dsn=db_admin_dsn)
    assert result.returncode != 0 and not result.stdout
    assert 'SECRET_SENTINEL' not in result.stderr and 'Traceback' not in result.stderr
    namespace = json.loads(result.stderr)['diagnostic_namespace']
    assert namespace.startswith('prosaic-diagnostic-')
    with psycopg.connect(db_admin_dsn) as admin:
        assert admin.execute('SELECT count(*) FROM prosaic_harness.receipts WHERE namespace=%s', (namespace,)).fetchone()[0] == 1
