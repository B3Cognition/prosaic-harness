"""Explicit file storage contract migration preserves legacy records."""
from pathlib import Path
from dataclasses import replace
import pytest
from prosaic_harness import (FileSessionStore, Conversation, StoreIncompatible,
    ConversationError, SessionNotFound)
from support.conversations import binding_factory, scope
from support.context_counter import fixture_context
from test_session_context import allocated, failed, SID, AID
from prosaic_harness.session_contracts import new_session, make_receipt, adopt_receipt


def test_new_file_store_advertises_context_and_recovers_v2_receipt(tmp_path, binding_factory, scope):
    root = tmp_path / 'sessions'
    store = FileSessionStore(root, namespace='test')
    store.initialize()
    assert 'context_assembly_v1' in store.capabilities
    _, state, prepared = allocated(binding_factory, scope)
    with store.lease(SID, scope=scope) as lease:
        store.create_session(SID, state, lease, scope=scope)
        store.save_receipt(SID, AID, make_receipt(state, AID, failed(prepared)), lease, scope=scope)
    store.close()
    restarted = FileSessionStore(root, namespace='test')
    snapshot = restarted.load_session(SID, scope=scope)
    packet = restarted.load_receipt(SID, AID, scope=scope)
    assert snapshot.state == state
    assert adopt_receipt(snapshot.state, packet)['turns'][0]['status'] == 'failed'
    with pytest.raises(SessionNotFound):
        restarted.load_receipt(SID, AID, scope=replace(scope, actor='foreign'))
    restarted.close()


def test_legacy_marker_requires_explicit_upgrade_and_keeps_v1_bytes(tmp_path, binding_factory, scope):
    root = tmp_path / 'sessions'
    store = FileSessionStore(root, namespace='test')
    store.initialize()
    marker = root / 'test' / '.conversation-store.json'
    marker.write_bytes(b'{"storageContract":1,"version":1}')
    assert 'context_assembly_v1' not in store.capabilities
    old = new_session(SID, scope, binding_factory())
    with store.lease(SID, scope=scope) as lease:
        store.create_session(SID, old, lease, scope=scope)
    policy, counters = fixture_context(count=lambda request: 10)
    binding = binding_factory(context_policy=policy, token_counters=counters)
    with pytest.raises(ConversationError):
        Conversation(binding, store=store, scope=scope).create()
    before = store.load_session(SID, scope=scope)
    store.migrate_context_storage()
    store.migrate_context_storage()
    assert 'context_assembly_v1' in store.capabilities
    assert store.load_session(SID, scope=scope) == before
    assert marker.read_bytes() == b'{"storageContract":2,"version":2}'
    store.close()


def test_file_contract_migration_refuses_unknown_metadata(tmp_path):
    root = tmp_path / 'sessions'
    store = FileSessionStore(root, namespace='test')
    store.initialize()
    marker = root / 'test' / '.conversation-store.json'
    marker.write_bytes(b'{"storageContract":99,"version":99}')
    with pytest.raises(StoreIncompatible):
        store.migrate_context_storage()
    assert marker.read_bytes() == b'{"storageContract":99,"version":99}'
    store.close()
