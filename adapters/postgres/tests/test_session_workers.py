import uuid

import psycopg
import pytest
from prosaic_harness import ConversationScope, LeaseLost, StoreIncompatible, StoreUnavailable
from prosaic_harness_postgres import PostgresSessionStore
from support.session_documents import document, reserve
from support.session_workers import SessionWorker
from test_session_recovery import worker_scope


def test_simultaneous_workers_do_not_advance_the_same_revision_twice(db_admin_dsn):
    scope, sid = worker_scope(), uuid.uuid4().hex
    with PostgresSessionStore(db_admin_dsn, namespace=scope.namespace) as owner:
        owner.initialize()
        with owner.lease(sid, scope=scope) as lease:
            revision = owner.create_session(sid, document(scope, session_id=sid), lease, scope=scope)
    with SessionWorker(db_admin_dsn, sid, 'advance', revision=revision) as first:
        with SessionWorker(db_admin_dsn, sid, 'advance', revision=revision) as second:
            results = [first.result(allow_error=True), second.result(allow_error=True)]
    assert sum(result.get('status') == 'pending' for result in results) == 1
    assert any(result.get('error') in {'session_busy', 'revision_conflict'} for result in results)
    with PostgresSessionStore(db_admin_dsn, namespace=scope.namespace) as reader:
        assert len(reader.load_session(sid, scope=scope).state['turns']) == 1


def test_generation_takeover_fences_late_checkpoint_and_receipt(db_admin_dsn):
    from support.session_documents import receipt
    from prosaic_harness.session_contracts import mark_dispatch
    scope, sid = worker_scope(), uuid.uuid4().hex
    with PostgresSessionStore(db_admin_dsn, namespace=scope.namespace) as first:
        first.initialize()
        with PostgresSessionStore(db_admin_dsn, namespace=scope.namespace) as second:
            with first.lease(sid, scope=scope) as old:
                state = mark_dispatch(reserve(document(scope, session_id=sid)), 'b' * 32)
                revision = first.create_session(sid, state, old, scope=scope)
                with psycopg.connect(db_admin_dsn) as admin:
                    admin.execute('UPDATE prosaic_harness_conversations.leases '
                        "SET expires_at=clock_timestamp()-interval '1 second' "
                        'WHERE namespace=%s AND session_id=%s', (scope.namespace, sid))
                with second.lease(sid, scope=scope) as fresh:
                    assert fresh.generation > old.generation
                    with pytest.raises(LeaseLost):
                        first.save_session(sid, state, revision, old, scope=scope)
                    with pytest.raises(LeaseLost):
                        first.save_receipt(sid, 'b' * 32, receipt(state), old, scope=scope)
                    second.save_receipt(sid, 'b' * 32, receipt(state), fresh, scope=scope)
                    assert second.load_session(sid, scope=scope).revision == revision


def test_execution_keeps_no_database_transaction_or_connection(db_admin_dsn):
    scope, sid = worker_scope(), uuid.uuid4().hex
    with PostgresSessionStore(db_admin_dsn, namespace=scope.namespace, pool_size=1) as store:
        store.initialize()
        with store.lease(sid, scope=scope) as lease:
            store.create_session(sid, document(scope, session_id=sid), lease, scope=scope)
            # This is the host execution interval between short store operations.
            assert store._transport.pending_operations == 0
            with psycopg.connect(db_admin_dsn) as admin:
                assert admin.execute("SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname=current_database() AND pid<>pg_backend_pid() "
                    "AND state='idle in transaction'").fetchone() == (0,)
            assert store.load_session(sid, scope=scope).state['turns'] == []


def test_stale_standby_is_not_authoritative_for_conversations(owned_cluster):
    scope = ConversationScope('conversation-routing', 'sandbox', 'chat', 'tenant', 'actor')
    sid = uuid.uuid4().hex
    with PostgresSessionStore(owned_cluster.dsn, namespace=scope.namespace) as store:
        store.initialize()
    standby = owned_cluster.start_standby()
    with psycopg.connect(standby, autocommit=True) as admin:
        admin.execute('SELECT pg_wal_replay_pause()')
    with PostgresSessionStore(owned_cluster.dsn, namespace=scope.namespace) as store:
        with store.lease(sid, scope=scope) as lease:
            store.create_session(sid, document(scope, session_id=sid), lease, scope=scope)
    with PostgresSessionStore(standby, namespace=scope.namespace, operation_timeout_s=1) as routed:
        with pytest.raises((StoreIncompatible, StoreUnavailable)):
            routed.load_session(sid, scope=scope)


@pytest.mark.parametrize('setting', ['fsync', 'full_page_writes'])
def test_unsafe_wal_settings_refuse_conversation_access(owned_cluster, setting):
    owned_cluster.set_setting(setting, 'off')
    with PostgresSessionStore(owned_cluster.dsn, namespace='conversation-unsafe') as store:
        with pytest.raises(StoreIncompatible):
            store.check_ready()
