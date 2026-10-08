"""Disposable PostgreSQL fixtures with exact, validated ownership for cleanup."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

import psycopg


class LocalCluster:
    def __init__(self, engine, version='16'):
        if engine not in {'podman', 'docker'} or version not in {'16', '18'}:
            raise ValueError('supported fixture engine/version required')
        self.engine, self.version = engine, version
        self.token = uuid.uuid4().hex
        self.directory = Path(tempfile.mkdtemp(prefix='prosaic-harness-pgtest-')).resolve()
        self.manifest = self.directory / 'ownership.json'
        self.network = 'prosaic-harness-pgtest-' + self.token
        self.containers = []
        self.network_created = False
        self._write_manifest()

    def _run(self, *args, timeout=45):
        result = subprocess.run([self.engine, *args], capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError('owned container fixture command failed: ' + args[0])
        return result.stdout.strip()

    def _write_manifest(self):
        self.manifest.write_text(json.dumps({'engine': self.engine, 'version': self.version,
            'token': self.token, 'directory': str(self.directory), 'network': self.network,
            'network_created': self.network_created, 'containers': self.containers}, indent=2))

    def _validate_container(self, entry):
        info = json.loads(self._run('inspect', entry['id']))[0]
        if (info['Id'] != entry['id'] or info['Name'].lstrip('/') != entry['name']
                or info['Config']['Labels'].get('prosaic-harness-test-owner') != self.token):
            raise RuntimeError('fixture ownership mismatch; refusing container mutation')

    def _container(self, suffix, *extra):
        name = self.network + '-' + suffix
        container_id = self._run('run', '-d', '--name', name, '--network', self.network,
            '--label', 'prosaic-harness-test-owner=' + self.token,
            '-p', '127.0.0.1::5432', '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
            '-e', 'PGDATA=/var/lib/postgresql/test-data',
            '-v', str(self.directory / 'pg_hba.conf') + ':/fixture/pg_hba.conf:ro',
            'docker.io/library/postgres:' + self.version, *extra)
        entry = {'id': container_id, 'name': name}
        self.containers.append(entry)
        self._write_manifest()
        port = self._run('port', container_id, '5432/tcp').rsplit(':', 1)[1]
        entry['dsn'] = f'postgresql://postgres@127.0.0.1:{port}/postgres'
        self._write_manifest()
        self._wait(entry['dsn'])
        return entry

    @staticmethod
    def _wait(dsn):
        end = time.monotonic() + 30
        while time.monotonic() < end:
            try:
                with psycopg.connect(dsn, connect_timeout=1):
                    return
            except psycopg.Error:
                time.sleep(.1)
        raise RuntimeError('owned PostgreSQL fixture did not become ready')

    def start(self):
        # Trust is confined to this generated network and loopback host ports.
        (self.directory / 'pg_hba.conf').write_text('local all all trust\nhost all all 0.0.0.0/0 trust\nhost replication all 0.0.0.0/0 trust\n')
        self._run('network', 'create', '--label', 'prosaic-harness-test-owner=' + self.token, self.network)
        self.network_created = True
        self._write_manifest()
        self.primary = self._container('primary', 'postgres', '-c', 'hba_file=/fixture/pg_hba.conf')
        self.dsn = self.primary['dsn']
        return self

    def start_standby(self):
        self._validate_container(self.primary)
        command = ('pg_basebackup -D "$PGDATA" -h ' + self.primary['name']
                   + ' -U postgres -R -X stream; exec docker-entrypoint.sh postgres -c hba_file=/fixture/pg_hba.conf')
        standby = self._container('standby', 'bash', '-ec', command)
        self.standby = standby
        return standby['dsn']

    def crash_restart(self):
        self._validate_container(self.primary)
        self._run('kill', '--signal', 'KILL', self.primary['id'])
        self._run('start', self.primary['id'])
        # Docker may reallocate an ephemeral published host port on restart.
        port = self._run('port', self.primary['id'], '5432/tcp').rsplit(':', 1)[1]
        self.dsn = self.primary['dsn'] = f'postgresql://postgres@127.0.0.1:{port}/postgres'
        self._write_manifest()
        try:
            self._wait(self.dsn)
        except RuntimeError as error:
            port = self._run('port', self.primary['id'], '5432/tcp')
            logs = self._run('logs', '--tail', '20', self.primary['id'])
            raise RuntimeError(f'{error}; original DSN={self.dsn}; current port={port}; logs={logs}') from error

    def set_setting(self, name, value):
        if name not in {'fsync', 'full_page_writes'} or value not in {'on', 'off'}:
            raise ValueError('unsupported disposable server setting')
        self._validate_container(self.primary)
        with psycopg.connect(self.dsn, autocommit=True) as admin:
            admin.execute(f"ALTER SYSTEM SET {name}='{value}'")
            admin.execute('SELECT pg_reload_conf()')
        end = time.monotonic() + 3
        while time.monotonic() < end:
            with psycopg.connect(self.dsn) as admin:
                if admin.execute('SELECT current_setting(%s)', (name,)).fetchone()[0] == value:
                    return
            time.sleep(.05)
        raise RuntimeError('disposable setting reload failed')

    def linux_wheel_smoke(self, root):
        self._validate_container(self.primary)
        root = Path(root).resolve()
        name = self.network + '-linux-wheels'
        command = '''
set -eu
apt-get update -qq
apt-get install -y -qq git >/dev/null
python -m venv /tmp/core
/tmp/core/bin/python -m pip install /core-wheels/prosaic_harness-0.6.0-py3-none-any.whl >/dev/null
/tmp/core/bin/python -I -c 'import importlib.util,prosaic_harness; assert importlib.util.find_spec("psycopg") is None; assert importlib.util.find_spec("prosaic_harness_postgres") is None'
python -m venv /tmp/both
/tmp/both/bin/python -m pip install /core-wheels/prosaic_harness-0.6.0-py3-none-any.whl /adapter-wheels/prosaic_harness_postgres-0.1.0-py3-none-any.whl >/dev/null
/tmp/both/bin/python /fixture/linux_wheel_smoke.py
'''
        container_id = self._run('create', '--name', name, '--network', self.network,
            '--label', 'prosaic-harness-test-owner=' + self.token,
            '-e', 'HARNESS_SMOKE_DSN=postgresql://postgres@' + self.primary['name'] + '/postgres',
            '-v', str(root / 'dist') + ':/core-wheels:ro',
            '-v', str(root / 'adapters/postgres/dist') + ':/adapter-wheels:ro',
            '-v', str(root / 'examples/postgres') + ':/examples:ro',
            '-v', str(root / 'adapters/postgres/tests/support/linux_wheel_smoke.py') + ':/fixture/linux_wheel_smoke.py:ro',
            'docker.io/library/python:3.12-slim', 'sh', '-ec', command)
        self.containers.append({'id': container_id, 'name': name})
        self._write_manifest()
        return self._run('start', '-a', container_id, timeout=240)

    def stop(self):
        for entry in reversed(self.containers):
            self._validate_container(entry)
            self._run('rm', '-f', '-v', entry['id'])
            self.containers.remove(entry)
            self._write_manifest()
        if self.network_created:
            info = json.loads(self._run('network', 'inspect', self.network))[0]
            labels = info.get('Labels', info.get('labels', {}))
            if labels.get('prosaic-harness-test-owner') != self.token:
                raise RuntimeError('fixture network ownership mismatch; refusing cleanup')
            self._run('network', 'rm', self.network)
            self.network_created = False
            self._write_manifest()
        for name in ('pg_hba.conf', 'ownership.json'):
            (self.directory / name).unlink(missing_ok=True)
        self.directory.rmdir()

    @classmethod
    def from_manifest(cls, path):
        path = Path(path).resolve()
        data = json.loads(path.read_text())
        if (path.name != 'ownership.json' or path.parent != Path(data['directory']).resolve()
                or not path.parent.name.startswith('prosaic-harness-pgtest-')
                or data['network'] != 'prosaic-harness-pgtest-' + data['token']):
            raise ValueError('invalid fixture ownership manifest')
        cluster = cls.__new__(cls)
        for key in ('engine', 'version', 'token', 'network', 'network_created', 'containers'):
            setattr(cluster, key, data[key])
        if cluster.engine not in {'podman', 'docker'}:
            raise ValueError('invalid fixture engine')
        cluster.directory, cluster.manifest = path.parent, path
        if cluster.containers:
            cluster.primary = cluster.containers[0]
            cluster.dsn = cluster.primary['dsn']
        return cluster


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('start')
    start.add_argument('--engine', choices=['podman', 'docker'], required=True)
    start.add_argument('--version', choices=['16', '18'], default='16')
    for command in ('test', 'stop'):
        commands.add_parser(command).add_argument('--manifest', required=True)
    args = parser.parse_args()
    if args.command == 'start':
        cluster = LocalCluster(args.engine, args.version)
        try:
            cluster.start()
            print(cluster.manifest)
        except BaseException:
            cluster.stop()
            raise
    else:
        cluster = LocalCluster.from_manifest(args.manifest)
        if args.command == 'stop':
            cluster.stop()
        else:
            env = os.environ | {'HARNESS_TEST_DATABASE_URL': cluster.dsn,
                'HARNESS_TEST_CONTAINER_ENGINE': cluster.engine, 'HARNESS_TEST_POSTGRES_VERSION': cluster.version}
            root = Path(__file__).resolve().parents[4]
            raise SystemExit(subprocess.run([sys.executable, '-m', 'pytest', '-q',
                'adapters/postgres/tests', '--require-postgres'], cwd=root, env=env, timeout=600).returncode)


if __name__ == '__main__':
    main()
