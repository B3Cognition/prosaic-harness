"""An explicit storage contract changes only the full-page-write guard."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from prosaic_harness import StoreIncompatible
from prosaic_harness_postgres.transport import PostgresTransport


@pytest.mark.parametrize('profile', ['postgresql', 'aurora-postgresql'])
@pytest.mark.parametrize('row,accepted', [
    ((False, 'off', 'on', 'on', 'on'), True),
    ((False, 'off', 'on', 'off', 'on'), 'aurora'),
    ((False, 'off', 'off', 'off', 'on'), False),
    ((False, 'off', 'on', 'off', 'off'), False),
    ((True, 'off', 'on', 'off', 'on'), False),
    ((False, 'on', 'on', 'off', 'on'), False),
    ((False, 'off', 'on', 'on', 'remote_apply'), True),
    ((False, 'off', 'on', 'on', 'local'), False),
    ((False, 'off', 'on', 'invalid', 'on'), False),
    (None, False),
])
def test_profile_changes_only_full_page_requirement(profile, row, accepted):
    transport = object.__new__(PostgresTransport)
    transport.durability_profile = profile
    cursor = AsyncMock()
    cursor.fetchone.return_value = row
    connection = AsyncMock()
    connection.execute.return_value = cursor
    allowed = accepted is True or (accepted == 'aurora' and profile == 'aurora-postgresql')
    if allowed:
        asyncio.run(transport._guard(connection))
    else:
        with pytest.raises(StoreIncompatible):
            asyncio.run(transport._guard(connection))


@pytest.mark.parametrize('profile', ['', 'storage', 'Aurora', None, True])
def test_unknown_profile_rejected_before_connection(profile):
    with pytest.raises(ValueError, match='durability_profile'):
        PostgresTransport('unused', durability_profile=profile)


@pytest.mark.parametrize('module_name,class_name', [('store', 'PostgresRunStore'), ('session_store', 'PostgresSessionStore')])
def test_public_store_and_from_env_forward_profile(monkeypatch, module_name, class_name):
    import importlib
    module = importlib.import_module('prosaic_harness_postgres.' + module_name)
    captured = []
    monkeypatch.setattr(module, 'PostgresTransport', lambda dsn, **kw: captured.append(kw))
    monkeypatch.setenv('SYNTHETIC_DSN', 'synthetic')
    cls = getattr(module, class_name)
    cls('synthetic', namespace='fixture')
    cls.from_env('SYNTHETIC_DSN', namespace='fixture', durability_profile='aurora-postgresql')
    assert [kw['durability_profile'] for kw in captured] == ['postgresql', 'aurora-postgresql']


@pytest.mark.parametrize('command', ['init', 'doctor', 'migrate-conversations'])
def test_cli_forwards_explicit_profile(monkeypatch, command):
    from prosaic_harness_postgres import cli, session_store
    calls = []
    class Store:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def initialize(self): pass
        def check_ready(self): pass
        def migrate_context_storage(self): pass
    def create(name, **kwargs):
        calls.append(kwargs['durability_profile'])
        return Store()
    monkeypatch.setattr(cli.PostgresRunStore, 'from_env', create)
    monkeypatch.setattr(session_store.PostgresSessionStore, 'from_env', create)
    assert cli.main([command, '--dsn-env', 'SYNTHETIC_DSN', '--durability-profile', 'aurora-postgresql']) == 0
    assert calls == ['aurora-postgresql']


@pytest.mark.parametrize('class_name', ['PostgresRunStore', 'PostgresSessionStore'])
def test_explicit_profile_retains_real_connection_guards(db_admin_dsn, class_name):
    import prosaic_harness_postgres
    cls = getattr(prosaic_harness_postgres, class_name)
    with cls(db_admin_dsn, namespace='fixture', durability_profile='aurora-postgresql', pool_size=1) as store:
        store.initialize()
        store.check_ready()
        store._transport.call(lambda conn: conn.execute('SET synchronous_commit=off'))
        with pytest.raises(StoreIncompatible):
            store.check_ready()
