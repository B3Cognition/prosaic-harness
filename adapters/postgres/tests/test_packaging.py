"""Built wheels, not editable imports, are the installation contract."""
from email import message_from_string
import json
import os
from pathlib import Path
import subprocess
import sys
import venv
import zipfile

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / 'dist/prosaic_harness-0.6.0-py3-none-any.whl'
ADAPTER = ROOT / 'adapters/postgres/dist/prosaic_harness_postgres-0.1.0-py3-none-any.whl'


def test_ci_requires_both_database_majors_and_owned_recovery():
    jobs = yaml.safe_load((ROOT / '.github/workflows/tests.yml').read_text())['jobs']
    assert 'postgres' in jobs, 'missing required PostgreSQL adapter lane'
    assert jobs['postgres']['strategy']['matrix']['postgres'] == ['16', '18']
    commands = '\n'.join(step.get('run', '') for step in jobs['postgres']['steps'])
    assert 'local_cluster.py test' in commands and 'local_cluster.py stop' in commands
    assert 'python -m build adapters/postgres' in commands


def test_required_lane_rejects_skipped_case(tmp_path):
    (tmp_path / 'test_skip.py').write_text('import pytest\ndef test_missing_gate(): pytest.skip("unmet gate")\n')
    env = os.environ | {'PYTHONPATH': str(ROOT / 'adapters/postgres/tests')}
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'conftest',
        '--require-postgres', str(tmp_path / 'test_skip.py')], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 1, 'required lane silently accepted a skipped case'


def metadata(path):
    assert path.is_file(), 'build both distributions before running packaging gates'
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        name = next(name for name in names if name.endswith('.dist-info/METADATA'))
        return message_from_string(archive.read(name).decode()), names


def test_wheel_contents_and_dependency_boundaries():
    core, names = metadata(CORE)
    assert core['Version'] == '0.6.0'
    assert not any(name.startswith('prosaic_harness_postgres/') for name in names)
    assert not any('psycopg' in value.lower() for value in core.get_all('Requires-Dist'))
    adapter, names = metadata(ADAPTER)
    assert adapter['Version'] == '0.1.0'
    assert any(value.startswith('prosaic-harness<0.7,>=0.6') for value in adapter.get_all('Requires-Dist'))
    assert 'prosaic_harness_postgres/cli.py' in names


@pytest.fixture(scope='session')
def wheel_environments(tmp_path_factory):
    root = tmp_path_factory.mktemp('installed-wheels')
    envs = []
    for label, wheels in [('core', [CORE]), ('both', [CORE, ADAPTER])]:
        directory = root / label
        # Match python -m venv on supported POSIX hosts. Copying the uv-managed
        # macOS executable breaks its relative libpython load path.
        venv.EnvBuilder(with_pip=True, symlinks=True).create(directory)
        python = directory / 'bin/python'
        result = subprocess.run([str(python), '-m', 'pip', 'install', *map(str, wheels)],
            cwd=root, capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, 'clean declared-dependency wheel install failed'
        envs.append(python)
    return envs


def test_core_only_install_imports_without_postgres(wheel_environments, tmp_path):
    python, _ = wheel_environments
    result = subprocess.run([str(python), '-I', '-c', 'import importlib.util,prosaic_harness; '
        'assert importlib.util.find_spec("psycopg") is None; '
        'assert importlib.util.find_spec("prosaic_harness_postgres") is None; '
        'assert "site-packages" in prosaic_harness.__file__'], cwd=tmp_path,
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_both_wheels_setup_and_two_worker_quickstart(wheel_environments, db_admin_dsn, runtime_dsn):
    import uuid
    from test_cli import grant_runtime
    _, python = wheel_environments
    env = {key: value for key, value in os.environ.items() if key in {'PATH', 'HOME', 'LANG', 'SYSTEMROOT'}}
    env['PATH'] = str(python.parent) + os.pathsep + env.get('PATH', '')
    env['WHEEL_TEST_DSN'] = db_admin_dsn
    cli = python.parent / 'prosaic-harness-postgres'
    for args in [('init',), ('doctor',), ('doctor', '--check-write')]:
        result = subprocess.run([str(cli), *args, '--dsn-env', 'WHEEL_TEST_DSN'],
            env=env, capture_output=True, text=True, timeout=40)
        assert result.returncode == 0, result.stderr
    grant_runtime(db_admin_dsn, runtime_dsn)
    env['WHEEL_TEST_DSN'] = runtime_dsn
    runner = ROOT / 'examples/postgres/run_workflow.py'
    run_id = uuid.uuid4().hex
    common = ['--dsn-env', 'WHEEL_TEST_DSN', '--namespace', 'wheel-test', '--run-id', run_id]
    def run(command, *args):
        result = subprocess.run([str(python), str(runner), command, *common, *args], env=env,
            input='{}', capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    assert run('start')['state']['status'] == 'waiting'
    revision = run('status')['revision']
    assert run('resume', '--choice', 'approve', '--expected-revision', revision)['state']['status'] == 'completed'
