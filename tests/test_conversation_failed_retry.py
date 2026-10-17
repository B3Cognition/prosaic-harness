"""Known no-effect failures can retry without replacing the original message."""
from dataclasses import replace

import pytest
from prosaic_harness import ConversationError, ConversationPolicy, RevisionConflict
from support.conversation_host import conversation_fixture, context_host


def fail_with_known_usage(fx, snapshot):
    fx.responses.append((200, {'choices': [{'message': {'role': 'assistant', 'content': 'partial'},
        'finish_reason': 'length'}], 'usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}}))
    reply = fx.controller.send(snapshot.session_id, message_id='original', message='Resolve this request',
        expected_revision=snapshot.revision)
    assert reply.document['status'] == 'failed'
    return reply


@pytest.mark.parametrize('kind', ['memory', 'file'])
def test_explicit_failed_retry_preserves_request_and_accounted_attempts(conversation_fixture, kind):
    with conversation_fixture(kind) as fx:
        snapshot = fx.controller.create()
        failed = fail_with_known_usage(fx, snapshot)
        before = fx.store.load_session(snapshot.session_id, scope=fx.scope).state
        fx.queue_text('Resolved')
        reply = fx.fresh_controller().retry_failed(snapshot.session_id,
            expected_revision=failed.document['revision'], acknowledge_effect_risk=True)
        after = fx.store.load_session(snapshot.session_id, scope=fx.scope).state
        assert reply.document['status'] == 'completed' and reply.document['messageId'] == 'original'
        assert len(after['turns']) == 1 and len(after['attempts']) == 2
        assert after['turns'][0]['requestIdentity'] == before['turns'][0]['requestIdentity']
        first, second = [after['attempts'][aid] for aid in after['turns'][0]['attempts']]
        assert first == next(iter(before['attempts'].values()))
        assert second['contextIdentity'] == first['contextIdentity']
        assert second['inputBytes'] == first['inputBytes']
        assert after['providerRequests'] == fx.provider_calls == 2
        assert fx.controller.recover(snapshot.session_id).document == reply.document
        assert fx.provider_calls == 2


def test_failed_retry_requires_consent_current_revision_and_remaining_quota(conversation_fixture):
    policy = replace(ConversationPolicy(), max_attempts_per_turn=1)
    with conversation_fixture(policy=policy) as fx:
        snapshot = fx.controller.create()
        failed = fail_with_known_usage(fx, snapshot)
        retry = fx.controller.retry_failed
        with pytest.raises(ConversationError, match='confirmationRequired'):
            retry(snapshot.session_id, expected_revision=failed.document['revision'], acknowledge_effect_risk=False)
        with pytest.raises(RevisionConflict):
            retry(snapshot.session_id, expected_revision=snapshot.revision, acknowledge_effect_risk=True)
        with pytest.raises(ConversationError, match='sessionLimit'):
            retry(snapshot.session_id, expected_revision=failed.document['revision'], acknowledge_effect_risk=True)
        assert fx.provider_calls == 1
        assert fx.controller.status(snapshot.session_id).document == failed.document


def test_failed_retry_does_not_dispatch_unknown_usage(conversation_fixture):
    with conversation_fixture() as fx:
        snapshot = fx.controller.create()
        fx.queue_known_failure()
        failed = fx.controller.send(snapshot.session_id, message_id='original', message='Resolve',
            expected_revision=snapshot.revision)
        with pytest.raises(ConversationError, match='messageConflict'):
            fx.controller.retry_failed(snapshot.session_id, expected_revision=failed.document['revision'],
                acknowledge_effect_risk=True)
        assert fx.provider_calls == 1


def test_completed_or_subsequent_turn_cannot_be_retried(conversation_fixture):
    with conversation_fixture() as fx:
        snapshot = fx.controller.create()
        failed = fail_with_known_usage(fx, snapshot)
        fx.queue_text('Next answer')
        completed = fx.controller.send(snapshot.session_id, message_id='next', message='Next',
            expected_revision=failed.document['revision'])
        with pytest.raises(ConversationError, match='messageConflict'):
            fx.controller.retry_failed(snapshot.session_id, expected_revision=completed.document['revision'],
                acknowledge_effect_risk=True)
        assert fx.provider_calls == 2


def test_context_retry_keeps_frozen_selection_and_original_accounting(context_host):
    with context_host() as fx:
        failed = fail_with_known_usage(fx, fx.session)
        before = fx.store.load_session(fx.session.session_id, scope=fx.scope).state
        fx.queue_text('Resolved')
        reply = fx.fresh_controller().retry_failed(fx.session.session_id,
            expected_revision=failed.document['revision'], acknowledge_effect_risk=True)
        after = fx.store.load_session(fx.session.session_id, scope=fx.scope).state
        attempts = [after['attempts'][aid] for aid in after['turns'][0]['attempts']]
        assert reply.document['status'] == 'completed'
        assert after['accounting'] == before['accounting']
        assert attempts[0]['contextSelection'] == attempts[1]['contextSelection']
        assert attempts[0]['initialContextReport'] == attempts[1]['initialContextReport']
        assert attempts[0]['context']['request_id'] == attempts[1]['context']['request_id'] == fx.session.session_id
        assert attempts[0]['context']['invocation_id'] != attempts[1]['context']['invocation_id']
        assert fx.provider_calls == 2


def test_missing_adopted_receipt_blocks_retry_before_dispatch(conversation_fixture, monkeypatch):
    with conversation_fixture() as fx:
        snapshot = fx.controller.create()
        failed = fail_with_known_usage(fx, snapshot)
        monkeypatch.setattr(fx.store, 'load_receipt', lambda *args, **kwargs: None)
        with pytest.raises(ConversationError, match='messageConflict'):
            fx.controller.retry_failed(snapshot.session_id, expected_revision=failed.document['revision'],
                acknowledge_effect_risk=True)
        assert fx.provider_calls == 1


def test_failed_retry_checks_all_prior_receipts_without_replenishing_usage(conversation_fixture):
    with conversation_fixture() as fx:
        snapshot = fx.controller.create()
        failed = fail_with_known_usage(fx, snapshot)
        fx.queue_known_failure()
        unknown = fx.controller.retry_failed(snapshot.session_id, expected_revision=failed.document['revision'],
            acknowledge_effect_risk=True)
        assert unknown.document['status'] == 'failed'
        with pytest.raises(ConversationError, match='messageConflict'):
            fx.controller.retry_failed(snapshot.session_id, expected_revision=unknown.document['revision'],
                acknowledge_effect_risk=True)
        state = fx.store.load_session(snapshot.session_id, scope=fx.scope).state
        assert len(state['turns']) == 1 and len(state['turns'][0]['attempts']) == 2
        assert state['providerRequests'] == fx.provider_calls == 2


@pytest.mark.parametrize('field,value', [('inputBytes', 1), ('contextIdentity', '0' * 64),
    ('providerAllowance', 1), ('toolAllowance', 1)])
def test_storage_rejects_changed_failed_retry_preparation(conversation_fixture, field, value):
    from prosaic_harness import StoreCorrupt
    from prosaic_harness.session_contracts import reserve_attempt, validate_session_transition
    with conversation_fixture() as fx:
        snapshot = fx.controller.create()
        fail_with_known_usage(fx, snapshot)
        state = fx.store.load_session(snapshot.session_id, scope=fx.scope).state
        attempt = next(iter(state['attempts'].values()))
        candidate = reserve_attempt(state, message_id='original', message='Resolve this request',
            invocation_id='a' * 32, context_identity=attempt['contextIdentity'],
            encoding_version=attempt['encodingVersion'], input_bytes=attempt['inputBytes'],
            provider_allowance=2, tool_allowance=0, retry=True)
        candidate['attempts']['a' * 32][field] = value
        # Rebuild derived counters so rejection tests frozen preparation, not a stale seal.
        from prosaic_harness.session_contracts import _with_counters
        candidate = _with_counters(candidate)
        with pytest.raises(StoreCorrupt): validate_session_transition(state, candidate)
