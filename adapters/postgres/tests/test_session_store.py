"""Public conversation persistence acceptance; real SQL uses owned databases."""
from dataclasses import replace
import pytest
import prosaic_harness as api
import prosaic_harness_postgres as pg


def test_conversation_backend_is_public_and_optional():
    assert callable(getattr(pg, 'PostgresSessionStore', None))
    assert not hasattr(api, 'PostgresSessionStore')


@pytest.fixture
def chat_scope():
    return api.ConversationScope('conversation-tests', 'sandbox', 'chat', 'tenant', 'actor')


@pytest.fixture
def chat_document(chat_scope):
    from support.session_documents import document
    return document(chat_scope)


@pytest.fixture
def chat_store(db_admin_dsn, chat_scope):
    with pg.PostgresSessionStore(db_admin_dsn, namespace=chat_scope.namespace) as store:
        store.initialize()
        yield store


def test_shared_session_contract(chat_store, chat_scope, chat_document):
    from prosaic_harness.testing import assert_session_store_contract
    from support.session_documents import reserve, receipt
    from prosaic_harness.session_contracts import mark_dispatch
    state = reserve(chat_document)
    assert_session_store_contract(chat_store, scope=chat_scope, state=state,
                                  receipt=receipt(mark_dispatch(state, 'b' * 32)))


def test_foreign_owner_is_not_found_at_every_boundary(chat_store, chat_scope, chat_document):
    from support.session_documents import reserve, receipt
    from prosaic_harness.session_contracts import mark_dispatch
    sid, aid = chat_document['sessionId'], 'b' * 32
    running = mark_dispatch(reserve(chat_document), aid)
    with chat_store.lease(sid, scope=chat_scope) as lease:
        revision = chat_store.create_session(sid, running, lease, scope=chat_scope)
        chat_store.save_receipt(sid, aid, receipt(running), lease, scope=chat_scope)
        with pytest.raises(api.LeaseLost):
            chat_store.save_session(sid, running, revision, lease,
                                    scope=replace(chat_scope, actor='foreign'))
    foreign = replace(chat_scope, actor='foreign')
    with pytest.raises(api.SessionNotFound):
        chat_store.load_session(sid, scope=foreign)
    with pytest.raises(api.SessionNotFound):
        chat_store.load_receipt(sid, aid, scope=foreign)
    with pytest.raises(api.SessionNotFound):
        with chat_store.lease(sid, scope=foreign):
            pytest.fail('foreign owner must not acquire another session address')


def test_scope_and_session_scoped_revisions(chat_store, chat_scope, chat_document):
    from support.session_documents import document
    sid = chat_document['sessionId']
    with chat_store.lease(sid, scope=chat_scope) as lease:
        original = chat_store.create_session(sid, chat_document, lease, scope=chat_scope)
    other = document(chat_scope, session_id='c' * 32)
    with chat_store.lease(other['sessionId'], scope=chat_scope) as lease:
        chat_store.create_session(other['sessionId'], other, lease, scope=chat_scope)
        with pytest.raises(api.RevisionConflict):
            chat_store.save_session(other['sessionId'], other, original, lease, scope=chat_scope)


def test_store_and_pid_fence_before_write(db_admin_dsn, chat_store, chat_scope, chat_document):
    sid = chat_document['sessionId']
    with pg.PostgresSessionStore(db_admin_dsn, namespace=chat_scope.namespace) as other:
        other.check_ready()
        with chat_store.lease(sid, scope=chat_scope) as lease:
            with pytest.raises(api.LeaseLost):
                other.create_session(sid, chat_document, lease, scope=chat_scope)
            lease.pid = -1
            with pytest.raises(api.LeaseLost):
                chat_store.create_session(sid, chat_document, lease, scope=chat_scope)


def test_namespace_is_immutable_and_not_authority(chat_store, chat_scope, chat_document):
    with pytest.raises(AttributeError):
        chat_store.namespace = 'different'
    with pytest.raises(api.SessionNotFound):
        chat_store.load_session(chat_document['sessionId'], scope=replace(chat_scope, namespace='foreign'))


def test_raw_receipt_corruption_is_not_absence(db_admin_dsn, chat_store, chat_scope, chat_document):
    import psycopg
    from support.session_documents import reserve, receipt
    from prosaic_harness.session_contracts import mark_dispatch
    sid, aid = chat_document['sessionId'], 'b' * 32
    running = mark_dispatch(reserve(chat_document), aid)
    with chat_store.lease(sid, scope=chat_scope) as lease:
        chat_store.create_session(sid, running, lease, scope=chat_scope)
        chat_store.save_receipt(sid, aid, receipt(running), lease, scope=chat_scope)
    with psycopg.connect(db_admin_dsn) as conn:
        conn.execute('UPDATE prosaic_harness_conversations.receipts SET document=%s '
                     'WHERE namespace=%s AND session_id=%s AND invocation_id=%s',
                     ('{}', chat_scope.namespace, sid, aid))
    with pytest.raises(api.StoreCorrupt):
        chat_store.load_receipt(sid, aid, scope=chat_scope)


def test_finite_payload_and_sealed_identity_before_write(chat_store, chat_scope, chat_document):
    from prosaic_harness.session_contracts import seal
    sid = chat_document['sessionId']
    with chat_store.lease(sid, scope=chat_scope) as lease:
        hostile = seal(chat_document | {'turns': [{'forged': True}]})
        with pytest.raises(api.StoreCorrupt):
            chat_store.create_session(sid, hostile, lease, scope=chat_scope)
    with pytest.raises(api.SessionNotFound):
        chat_store.load_session(sid, scope=chat_scope)


def test_cas_preserves_original_binding_policy_and_accounting(chat_store, chat_scope, chat_document):
    from prosaic_harness.session_contracts import seal
    sid = chat_document['sessionId']
    with chat_store.lease(sid, scope=chat_scope) as lease:
        revision = chat_store.create_session(sid, chat_document, lease, scope=chat_scope)
        changed = seal(chat_document | {'bindingIdentity': 'f' * 64})
        with pytest.raises(api.StoreCorrupt):
            chat_store.save_session(sid, changed, revision, lease, scope=chat_scope)
        assert chat_store.load_session(sid, scope=chat_scope).revision == revision


@pytest.mark.parametrize('rewind', ['dispatch', 'allocatedLedger'])
def test_a_matching_hash_cannot_rewind_allocated_execution(chat_store, chat_scope, chat_document, rewind):
    from support.session_documents import reserve
    from prosaic_harness.session_contracts import mark_dispatch
    sid = chat_document['sessionId']
    reserved = reserve(chat_document)
    running = mark_dispatch(reserved, 'b' * 32)
    with chat_store.lease(sid, scope=chat_scope) as lease:
        revision = chat_store.create_session(sid, running, lease, scope=chat_scope)
        proposed = reserved if rewind == 'dispatch' else chat_document
        with pytest.raises(api.StoreCorrupt):
            chat_store.save_session(sid, proposed, revision, lease, scope=chat_scope)
        assert chat_store.load_session(sid, scope=chat_scope).state == running


@pytest.mark.parametrize('options', [dict(lease_s=14), dict(renew_s=True),
    dict(renew_s=60), dict(operation_timeout_s=float('inf')), dict(pool_size=True)])
def test_invalid_bounds_fail_before_opening_transport(options):
    factory = getattr(pg, 'PostgresSessionStore', None)
    assert factory is not None, 'conversation persistence is required'
    with pytest.raises(ValueError):
        factory('host=127.0.0.1 port=9 dbname=unused', namespace='test', **options)


def test_missing_dsn_environment_fails_without_fallback(monkeypatch):
    factory = getattr(pg, 'PostgresSessionStore', None)
    assert factory is not None, 'conversation persistence is required'
    monkeypatch.delenv('PROSAIC_CHAT_TEST_DSN', raising=False)
    with pytest.raises(api.StoreUnavailable):
        factory.from_env('PROSAIC_CHAT_TEST_DSN', namespace='test')
