"""Installed-wheel SDK/CLI smoke inside an owned native Linux container."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


def main():
    assert platform.system() == 'Linux'
    assert psycopg.pq.version() >= 170000
    base = os.environ['HARNESS_SMOKE_DSN']
    db, role = 'harness_test_' + uuid.uuid4().hex, 'harness_role_' + uuid.uuid4().hex
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(db)))
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(role)))
    dsn = make_conninfo(base, dbname=db)
    env = os.environ | {'WHEEL_DSN': dsn, 'PATH': str(Path(sys.executable).parent) + ':' + os.environ['PATH']}
    cli = Path(sys.executable).parent / 'prosaic-harness-postgres'
    def call(args, *, inputs=None):
        result = subprocess.run(args, env=env, input=inputs, capture_output=True, text=True, timeout=40)
        assert result.returncode == 0, 'installed-wheel command failed'
        return json.loads(result.stdout)
    try:
        for args in [('init',), ('init',), ('doctor',), ('doctor', '--check-write')]:
            call([str(cli), *args, '--dsn-env', 'WHEEL_DSN'])
        identifier = sql.Identifier(role)
        with psycopg.connect(dsn) as admin:
            admin.execute(sql.SQL('GRANT USAGE ON SCHEMA prosaic_harness TO {}').format(identifier))
            admin.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA prosaic_harness TO {}').format(identifier))
            admin.execute(sql.SQL('GRANT INSERT,UPDATE ON prosaic_harness.leases,prosaic_harness.runs TO {}').format(identifier))
            admin.execute(sql.SQL('GRANT INSERT ON prosaic_harness.receipts TO {}').format(identifier))
        env['WHEEL_DSN'] = make_conninfo(dsn, user=role)
        run_id = uuid.uuid4().hex
        common = ['--dsn-env', 'WHEEL_DSN', '--namespace', 'linux-smoke', '--run-id', run_id]
        runner = '/examples/run_workflow.py'
        assert call([sys.executable, runner, 'start', *common], inputs='{}')['state']['status'] == 'waiting'
        revision = call([sys.executable, runner, 'status', *common])['revision']
        assert call([sys.executable, runner, 'resume', *common, '--choice', 'approve',
                     '--expected-revision', revision])['state']['status'] == 'completed'
        print(json.dumps({'platform': platform.system(), 'architecture': platform.machine(),
                          'psycopg': psycopg.__version__, 'libpq': psycopg.pq.version(),
                          'installed_wheel_quickstart': 'passed'}))
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(db)))
            admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


if __name__ == '__main__':
    main()
