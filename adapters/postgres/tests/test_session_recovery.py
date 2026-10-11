import uuid

import psycopg
import pytest
from prosaic_harness import ConversationScope
from prosaic_harness_postgres import PostgresSessionStore
from prosaic_harness.session_contracts import mark_dispatch
from prosaic_harness.session_codec import encode
from support.session_documents import document, reserve, receipt
from support.session_workers import SessionWorker


def worker_scope():
    return ConversationScope('conversation-workers', 'sandbox', 'chat', 'tenant', 'actor')


def expire_owned_session(dsn, scope, sid):
    # Only this test's exact namespace/session address is changed.
    with psycopg.connect(dsn) as admin:
        admin.execute('UPDATE prosaic_harness_conversations.leases '
            "SET expires_at=clock_timestamp()-interval '1 second' "
            'WHERE namespace=%s AND session_id=%s', (scope.namespace, sid))


@pytest.mark.parametrize('edge', ['created', 'reserved', 'dispatched', 'receipt', 'adopted'])
def test_conversation_worker_death_preserves_authoritative_edges(db_admin_dsn, edge):
    scope, sid = worker_scope(), uuid.uuid4().hex
    with PostgresSessionStore(db_admin_dsn, namespace=scope.namespace) as store:
        store.initialize()
    with SessionWorker(db_admin_dsn, sid, 'start', edge=edge) as first:
        assert first.ready.wait(10), first.failure()
        first.kill()
    with PostgresSessionStore(db_admin_dsn, namespace=scope.namespace) as reader:
        state = reader.load_session(sid, scope=scope).state
        saved = reader.load_receipt(sid, 'b' * 32, scope=scope)
    if edge == 'created':
        assert state['turns'] == [] and saved is None
    elif edge == 'reserved':
        assert state['attempts']['b' * 32]['dispatchMarker'] is False and saved is None
    elif edge == 'dispatched':
        assert state['attempts']['b' * 32]['dispatchMarker'] is True and saved is None
    else:
        assert saved is not None
        expire_owned_session(db_admin_dsn, scope, sid)
        with SessionWorker(db_admin_dsn, sid, 'adopt') as fresh:
            recovered = fresh.result()
        assert recovered['status'] == 'completed' and recovered['receiptAdopted'] is True
        with PostgresSessionStore(db_admin_dsn, namespace=scope.namespace) as reader:
            after = reader.load_session(sid, scope=scope).state
        assert len(after['attempts']) == 1
        assert after['retainedReceiptBytes'] == len(encode(saved))


def test_unknown_conversation_receipt_commit_is_read_from_primary_once(db_admin_dsn):
    from support.tcp_proxy import TcpProxy
    scope, sid = worker_scope(), uuid.uuid4().hex
    with PostgresSessionStore(db_admin_dsn, namespace=scope.namespace) as store:
        store.initialize()
    with TcpProxy(db_admin_dsn) as proxy:
        with SessionWorker(proxy.dsn, sid, 'start', edge='dispatched', operation_timeout_s=2) as first:
            assert first.ready.wait(10), first.failure()
            proxy.block_next_commit_reply()
            first.release.set()
            failed = first.result(allow_error=True)
            assert failed['error'] == 'store_unavailable' and failed['outcomeUnknown'] is True
            assert proxy.commit_sent.is_set()
    with psycopg.connect(db_admin_dsn) as admin:
        assert admin.execute('SELECT count(*) FROM prosaic_harness_conversations.receipts '
            'WHERE namespace=%s AND session_id=%s', (scope.namespace, sid)).fetchone() == (1,)
    expire_owned_session(db_admin_dsn, scope, sid)
    with SessionWorker(db_admin_dsn, sid, 'adopt') as fresh:
        assert fresh.result()['status'] == 'completed'
    with PostgresSessionStore(db_admin_dsn, namespace=scope.namespace) as reader:
        assert len(reader.load_session(sid, scope=scope).state['attempts']) == 1


def test_unknown_dispatch_marker_is_visible_without_receipt_or_automatic_effect(db_admin_dsn):
    from support.tcp_proxy import TcpProxy
    scope, sid = worker_scope(), uuid.uuid4().hex
    with PostgresSessionStore(db_admin_dsn, namespace=scope.namespace) as owner:
        owner.initialize()
    with TcpProxy(db_admin_dsn) as proxy:
        with SessionWorker(proxy.dsn, sid, 'start', edge='reserved', operation_timeout_s=2) as first:
            assert first.ready.wait(10), first.failure()
            proxy.block_next_commit_reply()
            first.release.set()
            failed = first.result(allow_error=True)
            assert failed['error'] == 'store_unavailable' and failed['outcomeUnknown'] is True
    with PostgresSessionStore(db_admin_dsn, namespace=scope.namespace) as reader:
        state = reader.load_session(sid, scope=scope).state
        assert state['attempts']['b' * 32]['dispatchMarker'] is True
        assert reader.load_receipt(sid, 'b' * 32, scope=scope) is None
        assert state['reservedReceiptBytes'] == state['policy']['maxReceiptBytes']


def test_acknowledged_session_and_receipt_survive_database_crash(owned_cluster):
    scope = ConversationScope('conversation-crash', 'sandbox', 'chat', 'tenant', 'actor')
    sid = uuid.uuid4().hex
    state = mark_dispatch(reserve(document(scope, session_id=sid)), 'b' * 32)
    saved = receipt(state)
    with PostgresSessionStore(owned_cluster.dsn, namespace=scope.namespace) as store:
        store.initialize()
        with store.lease(sid, scope=scope) as lease:
            revision = store.create_session(sid, state, lease, scope=scope)
            store.save_receipt(sid, 'b' * 32, saved, lease, scope=scope)
    owned_cluster.crash_restart()
    with PostgresSessionStore(owned_cluster.dsn, namespace=scope.namespace) as reader:
        reader.check_ready()
        assert reader.load_session(sid, scope=scope).revision == revision
        assert reader.load_receipt(sid, 'b' * 32, scope=scope) == saved
