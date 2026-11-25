"""Live binding checks guard provider requests and session receipts."""

import pytest

from prosaic_harness import Conversation, ConversationBindings, ConversationError
from support.conversation_host import conversation_fixture  # noqa: F401 (fixture)


@pytest.mark.parametrize('event_name', ['started', 'provider_request_started'])
def test_drift_before_provider_dispatch_prevents_request(conversation_fixture, monkeypatch, event_name):
    with conversation_fixture() as fx:
        original_readmit = ConversationBindings.readmit
        drifted = False

        def on_event(event):
            nonlocal drifted
            if event['event'] == event_name:
                drifted = True

        def readmit(bindings):
            if drifted:
                raise ConversationError('bindingMismatch')
            return original_readmit(bindings)

        chat = Conversation(fx.bindings, store=fx.store, scope=fx.scope, observer=on_event)
        session = chat.create()
        fx.queue_text('done')
        monkeypatch.setattr(ConversationBindings, 'readmit', readmit)
        with pytest.raises(ConversationError, match='bindingMismatch'):
            chat.send(session.session_id, message_id='m1', message='Hello',
                      expected_revision=session.revision, on_event=on_event)

        assert drifted
        assert fx.provider_calls == 0


def test_drift_at_runtime_completion_prevents_receipt_save(conversation_fixture, monkeypatch):
    with conversation_fixture() as fx:
        original_readmit = ConversationBindings.readmit
        drifted = False

        def observe(event):
            nonlocal drifted
            if event['event'] == 'invocation_completed':
                drifted = True

        def readmit(bindings):
            if drifted:
                raise ConversationError('bindingMismatch')
            return original_readmit(bindings)

        chat = Conversation(fx.bindings, store=fx.store, scope=fx.scope, observer=observe)
        session = chat.create()
        fx.queue_text('done')
        monkeypatch.setattr(ConversationBindings, 'readmit', readmit)
        with pytest.raises(ConversationError, match='bindingMismatch'):
            chat.send(session.session_id, message_id='m1', message='Hello',
                      expected_revision=session.revision)

        assert drifted
        assert fx.provider_calls == 1
        saved = fx.store.load_session(session.session_id, scope=fx.scope).state
        attempt_id = saved['pending']['invocationId']
        assert fx.store.load_receipt(session.session_id, attempt_id, scope=fx.scope) is None
