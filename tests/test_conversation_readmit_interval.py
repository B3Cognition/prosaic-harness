"""Cancellation polling may space its binding readmission; dispatch and receipt are always readmitted."""
import pytest
from prosaic_harness import Conversation, ConversationBindings, ConversationError
from support.conversation_host import conversation_fixture  # noqa: F401 (fixture)


@pytest.fixture
def readmissions(monkeypatch):
    calls = []
    original = ConversationBindings.readmit

    def counted(self):
        calls.append(1)
        return original(self)

    monkeypatch.setattr(ConversationBindings, 'readmit', counted)
    return calls


def controller(fx, **options):
    return Conversation(fx.bindings, store=fx.store, scope=fx.scope, **options)


def send(chat, text='Hello'):
    session = chat.create()
    return chat.send(session.session_id, message_id='m1', message=text, expected_revision=session.revision).document


def test_the_default_readmits_on_every_poll(conversation_fixture, readmissions):
    with conversation_fixture() as fx:
        fx.queue_text('done')
        chat = controller(fx)
        readmissions.clear()
        assert send(chat)['status'] == 'completed'
        per_poll = len(readmissions)
    with conversation_fixture() as fx:
        fx.queue_text('done')
        chat = controller(fx, readmit_interval_s=60)
        readmissions.clear()
        assert send(chat)['status'] == 'completed'
        spaced = len(readmissions)
    assert spaced < per_poll


def test_drift_is_still_refused_before_the_receipt(conversation_fixture, monkeypatch):
    with conversation_fixture() as fx:
        fx.queue_text('done')
        chat = controller(fx, readmit_interval_s=60)
        session = chat.create()
        original = ConversationBindings.readmit
        dispatched = []

        def drifts_after_dispatch(self):
            if fx.provider_calls:  # the model answered: the host's bindings changed meanwhile
                dispatched.append(1)
                raise ConversationError('bindingMismatch')  # what readmit raises on drift
            return original(self)

        monkeypatch.setattr(ConversationBindings, 'readmit', drifts_after_dispatch)
        with pytest.raises(ConversationError) as refused:
            chat.send(session.session_id, message_id='m1', message='Hello', expected_revision=session.revision)
        assert refused.value.code == 'bindingMismatch'
        assert dispatched  # the post-turn readmission ran and refused
        saved = fx.store.load_session(session.session_id, scope=fx.scope).state
        assert not any(a['receiptAdopted'] for a in saved['attempts'].values())


@pytest.mark.parametrize('value', [-1, 61, float('nan'), float('inf'), True, '1'])
def test_the_interval_is_bounded(conversation_fixture, value):
    with conversation_fixture() as fx:
        with pytest.raises(ValueError):
            controller(fx, readmit_interval_s=value)
