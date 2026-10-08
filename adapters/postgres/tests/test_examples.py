import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from test_cli import run_cli, grant_runtime

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / 'examples/postgres/run_workflow.py'


def example(dsn, run_id, command, *, choice=None, revision=None, workflow=None):
    env = {key: value for key, value in os.environ.items() if key in {'PATH', 'HOME', 'LANG', 'SYSTEMROOT'}}
    env['TEST_RUNTIME_DSN'] = dsn
    args = [sys.executable, str(RUNNER), command, '--dsn-env', 'TEST_RUNTIME_DSN',
            '--namespace', 'example', '--run-id', run_id]
    if choice:
        args += ['--choice', choice]
    if revision:
        args += ['--expected-revision', revision]
    if workflow:
        args += ['--workflow', str(workflow)]
    return subprocess.run(args, input='{}', env=env, text=True, capture_output=True, timeout=30)


def test_documented_pause_cross_process_runtime_role(db_admin_dsn, runtime_dsn):
    assert run_cli('init', dsn=db_admin_dsn).returncode == 0
    grant_runtime(db_admin_dsn, runtime_dsn)
    run_id = uuid.uuid4().hex
    started = example(runtime_dsn, run_id, 'start')
    assert started.returncode == 0, started.stderr
    assert json.loads(started.stdout)['state']['status'] == 'waiting'
    snapshot = example(runtime_dsn, run_id, 'status')
    assert snapshot.returncode == 0, snapshot.stderr
    revision = json.loads(snapshot.stdout)['revision']
    denied = example(runtime_dsn, run_id, 'resume', choice='approve', revision='stale')
    assert denied.returncode != 0 and 'revision_conflict' in denied.stderr
    resumed = example(runtime_dsn, run_id, 'resume', choice='approve', revision=revision)
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout)['state']['status'] == 'completed'


def test_documented_synthetic_agent_is_real_runtime(db_admin_dsn, runtime_dsn, model_server, tmp_path):
    import shutil
    import yaml
    assert run_cli('init', dsn=db_admin_dsn).returncode == 0
    grant_runtime(db_admin_dsn, runtime_dsn)
    shutil.copytree(ROOT / 'examples/postgres', tmp_path / 'example')
    path = tmp_path / 'example/runtime.yml'
    raw = yaml.safe_load(path.read_text())
    raw['profiles']['synthetic']['base_url'] = model_server.url
    path.write_text(yaml.safe_dump(raw))
    result = example(runtime_dsn, uuid.uuid4().hex, 'start', workflow=tmp_path / 'example/synthetic.yml')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['state']['calls'] == 1
    assert model_server.request_count == 1
