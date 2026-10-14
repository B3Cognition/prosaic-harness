import json
from dataclasses import replace
import pytest
from prosaic_harness import ConversationError, RevisionConflict, SessionNotFound
from support.conversation_host import conversation_fixture


@pytest.mark.parametrize('kind', ['memory', 'file'])
def test_provider_timeout_is_durable_and_replays_without_dispatch(conversation_fixture, monkeypatch, kind):
    attempts = []

    class Opener:
        def open(self, *args, **kwargs):
            attempts.append(1)
            raise TimeoutError('synthetic provider timeout')

    monkeypatch.setattr('urllib.request.build_opener', lambda *args: Opener())
    with conversation_fixture(kind) as fx:
        snapshot = fx.controller.create()
        args = dict(message_id='timeout', message='Hello', expected_revision=snapshot.revision)
        reply = fx.controller.send(snapshot.session_id, **args)
        assert reply.document['status'] == 'failed'
        assert reply.document['failureCode'] == 'timeout'
        assert fx.fresh_controller().send(snapshot.session_id, **args).document == reply.document
        assert fx.fresh_controller().recover(snapshot.session_id).document == reply.document
        assert attempts == [1]


@pytest.mark.parametrize('kind',['memory','file'])
def test_graph_free_two_turn_history_and_owned_reply(conversation_fixture,kind):
    with conversation_fixture(kind) as fx:
        snapshot=fx.controller.create()
        fx.queue_text('Prague')
        first=fx.controller.send(snapshot.session_id,message_id='first',message='I meant Prague',
            expected_revision=snapshot.revision)
        fx.queue_text('Czechia')
        second=fx.controller.send(snapshot.session_id,message_id='second',message='Which country?',
            expected_revision=first.document['revision'])
        assert second.document['answer']=='Czechia'
        assert len(fx.controller.history(snapshot.session_id))==4
        assert 'I meant Prague' in json.dumps(fx.provider_requests[-1])
        second.document['answer']='mutated'
        assert fx.controller.status(snapshot.session_id).document['answer']=='Czechia'
        assert not any(k in second.document for k in ('scope','config','evidence','context','accounting'))


def test_exact_replay_precedes_revision_and_new_capacity(conversation_fixture):
    from prosaic_harness import ConversationPolicy
    with conversation_fixture(policy=replace(ConversationPolicy(),max_turns=1,max_attempts=1)) as fx:
        snapshot=fx.controller.create()
        fx.queue_text('Done')
        args=dict(message_id='first',message='Hello',expected_revision=snapshot.revision)
        reply=fx.controller.send(snapshot.session_id,**args)
        assert fx.controller.send(snapshot.session_id,**args).document==reply.document
        assert fx.provider_calls==1
        with pytest.raises(ConversationError,match='messageConflict'):
            fx.controller.send(snapshot.session_id,**(args|{'message':'Changed'}))
        with pytest.raises(ConversationError,match='sessionLimit'):
            fx.controller.send(snapshot.session_id,message_id='new',message='Next',
                expected_revision=reply.document['revision'])
        assert fx.provider_calls==1


def test_stale_new_message_never_dispatches(conversation_fixture):
    with conversation_fixture() as fx:
        snapshot=fx.controller.create()
        fx.queue_text('Done')
        fx.controller.send(snapshot.session_id,message_id='one',message='Hello',expected_revision=snapshot.revision)
        with pytest.raises(RevisionConflict):
            fx.controller.send(snapshot.session_id,message_id='two',message='Next',expected_revision=snapshot.revision)
        assert fx.provider_calls==1


def test_failed_correction_survives(conversation_fixture):
    with conversation_fixture() as fx:
        snapshot=fx.controller.create()
        fx.queue_known_failure()
        failed=fx.controller.send(snapshot.session_id,message_id='correction',message='I meant Prague',
            expected_revision=snapshot.revision)
        assert failed.document['status']=='failed' and failed.document['failureCode']=='providerFailure'
        fx.queue_text('Prague')
        reply=fx.controller.send(snapshot.session_id,message_id='query',message='Which city?',
            expected_revision=failed.document['revision'])
        history=[m.to_dict() for m in fx.controller.history(snapshot.session_id)]
        assert history[0]['turnStatus']=='failed' and len(history)==3
        assert 'I meant Prague' in json.dumps(fx.provider_requests[-1])
        assert reply.document['answer']=='Prague'


def test_create_preallocated_id_replays_after_lost_ack(conversation_fixture):
    with conversation_fixture() as fx:
        first=fx.controller.create(session_id='a'*32)
        assert fx.fresh_controller().create(session_id='a'*32)==first


def test_foreign_actor_cannot_read_replay_or_admit(conversation_fixture):
    from prosaic_harness import Conversation
    with conversation_fixture() as fx:
        snapshot=fx.controller.create()
        foreign=Conversation(fx.bindings,store=fx.store,scope=replace(fx.scope,actor='foreign'))
        for operation in (lambda:foreign.status(snapshot.session_id),lambda:foreign.history(snapshot.session_id),
                lambda:foreign.send(snapshot.session_id,message_id='one',message='Hello',expected_revision=snapshot.revision)):
            with pytest.raises(SessionNotFound): operation()
        assert fx.provider_calls==0


def test_commit_events_follow_durable_receipt_and_adoption(conversation_fixture):
    with conversation_fixture() as fx:
        snapshot=fx.controller.create()
        events=[]
        def observed(event):
            events.append(event)
            if event['event']=='receiptSaved':
                assert fx.store.load_receipt(snapshot.session_id,event['invocationId'],scope=fx.scope)
                assert fx.controller.status(snapshot.session_id).document['status']=='running'
            if event['event']=='turnCommitted':
                assert fx.controller.status(snapshot.session_id).document['status']=='completed'
        fx.queue_text('Done')
        fx.controller.send(snapshot.session_id,message_id='first',message='Hello',
            expected_revision=snapshot.revision,on_event=observed)
        phases=[e['event'] for e in events if e['event'] in ('receiptSaved','turnCommitted')]
        assert phases==['receiptSaved','turnCommitted']
