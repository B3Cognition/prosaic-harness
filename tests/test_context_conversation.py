"""Per-purpose context admission remains separate from execution authority."""
import json
import pytest
from prosaic_harness import ConversationError, StoreUnavailable
from support.conversation_host import context_host, conversation_fixture
from test_conversation_workflow import workflow_fixture
from test_conversation_recovery import Crash


@pytest.mark.parametrize('context_purpose', ['ordinary', 'interpretation'])
def test_explicit_retry_of_legacy_purpose_in_context_session(workflow_fixture, monkeypatch, context_purpose):
    from support.context_counter import fixture_context
    policy, counters=fixture_context(count=lambda request:10)
    kwargs=({'context_policy':policy} if context_purpose=='ordinary' else {'interpretation_context_policy':policy})
    with workflow_fixture(token_counters=counters, **kwargs) as fx:
        save=fx.store.save_session
        crashed=[False]
        def crash_after_marker(session_id,state,*args,**kwargs):
            revision=save(session_id,state,*args,**kwargs)
            if not crashed[0] and any(a['dispatchMarker'] for a in state['attempts'].values()):
                crashed[0]=True
                raise Crash()
            return revision
        monkeypatch.setattr(fx.store,'save_session',crash_after_marker)
        if context_purpose=='ordinary':
            sid=fx.session_id
            with pytest.raises(Crash):fx.send('the second result',{'choice':'second'})
            expected_purpose='interpretation'
        else:
            session=fx.controller.create();sid=session.session_id
            with pytest.raises(Crash):fx.controller.send(sid,message_id='hello',message='Hello',
                expected_revision=session.revision)
            expected_purpose='ordinary'
        recovered=fx.controller.recover(sid).document
        assert recovered['status']=='needsResolution'
        state=fx.store.load_session(sid,scope=fx.scope).state
        attempt=next(iter(state['attempts'].values()))
        assert attempt['purpose']==expected_purpose and attempt['contextSelection'] is None
        # The interpretation fixture queued its response before admission.
        if context_purpose=='interpretation':fx.queue_text('done')
        reply=fx.controller.retry_interrupted(sid,expected_revision=recovered['revision'],
            acknowledge_effect_risk=True).document
        saved=fx.store.load_session(sid,scope=fx.scope).state
        # An ordinary attempt had effect authority: retry completion cannot
        # erase the original interrupted attempt's unknown effects.
        assert reply['status']==('completed' if expected_purpose=='interpretation' else 'needsResolution')
        assert fx.provider_calls==1 and len(saved['attempts'])==2
        assert sum(a['receiptAdopted'] for a in saved['attempts'].values())==1


def test_readmission_precedes_marker_and_accounting(context_host):
    with context_host() as fx:
        fx.queue_text('done')
        reply = fx.send()
        assert reply['status'] == 'completed'
        count_indices = [i for i, event in enumerate(fx.events) if event == 'count']
        assert len(count_indices) == 2
        assert count_indices[0] < fx.events.index('reserve') < count_indices[1]
        assert count_indices[1] < fx.events.index('marker') < fx.events.index('accounting') < fx.events.index('provider')
        assert reply['contextAssembly']['candidateChecks'] == 2
        assert fx.provider_calls == 1


def test_admission_overflow_does_not_allocate_or_account(context_host):
    with context_host(count=lambda request, number: 181) as fx:
        before = fx.controller.status(fx.session.session_id).document
        with pytest.raises(ConversationError) as caught:
            fx.send()
        assert caught.value.code == 'contextLimit'
        assert fx.controller.status(fx.session.session_id).document == before
        assert fx.provider_calls == 0
        assert fx.events == ['count']


def test_counter_failure_during_readmission_becomes_safe_zero_effect_receipt(context_host):
    def counter(request, number):
        if number == 2: raise RuntimeError('private-counter-sentinel')
        return 10
    with context_host(count=counter) as fx:
        reply = fx.send()
        assert reply['status'] == 'failed'
        assert reply['failureCode'] == 'bindingMismatch'
        assert fx.provider_calls == 0
        saved = fx.store.load_session(fx.session.session_id, scope=fx.scope).state
        attempt = next(iter(saved['attempts'].values()))
        assert attempt['receiptAdopted'] is True and attempt['dispatchMarker'] is False
        assert 'private-counter-sentinel' not in json.dumps(reply)
        assert fx.fresh_controller().recover(fx.session.session_id).document == reply
        assert len(fx.counts) == 2


def test_optional_omission_keeps_complete_history_and_accounting_owner(context_host):
    def count(request, number):
        text = json.dumps(request)
        return 181 if 'omit-marker' in text and 'third-marker' in text else 10
    with context_host(mode='omitOldestTurns', count=count) as fx:
        for message in ('omit-marker', 'recent-marker', 'third-marker'):
            fx.queue_text('done')
            reply = fx.send(message)
        assert reply['status'] == 'completed'
        assert reply['contextAssembly']['omittedTurnCount'] == 1
        assert len(fx.controller.history(fx.session.session_id)) == 6
        assert 'omit-marker' not in json.dumps(fx.provider_requests[-1])
        state = fx.store.load_session(fx.session.session_id, scope=fx.scope).state
        assert state['accounting']['tenant_id'] == 'tenant'
        assert state['accounting']['billing_account_id'] == 'payer'


def test_unknown_marker_acknowledgement_never_dispatches_or_retries(context_host):
    with context_host() as fx:
        fx.store.fail_phase = 'marker'
        with pytest.raises(StoreUnavailable): fx.send()
        assert fx.provider_calls == 0
        assert 'accounting' not in fx.events
        reply = fx.fresh_controller().recover(fx.session.session_id).document
        assert reply['status'] == 'needsResolution'
        assert fx.provider_calls == 0 and len(fx.counts) == 2


def test_predispatch_cancel_keeps_frozen_accounting_attribution(context_host):
    with context_host() as fx:
        current=fx.controller.status(fx.session.session_id).document
        reply=fx.controller.send(fx.session.session_id,message_id='cancel',message='Hello',
            expected_revision=current['revision'],cancelled=lambda:True).document
        assert reply['status']=='failed' and reply['failureCode']=='cancelled'
        assert fx.provider_calls==0 and 'accounting' not in fx.events
        state=fx.store.load_session(fx.session.session_id,scope=fx.scope).state
        aid=state['turns'][0]['attempts'][0]
        packet=fx.store.load_receipt(fx.session.session_id,aid,scope=fx.scope)
        assert packet['evidence']['accounting']['context']['tenant_id']=='tenant'


@pytest.mark.parametrize('ordinary,interpreting', [(True,False),(False,True),(True,True)])
def test_interpreter_uses_own_model_policy_and_current_authority(workflow_fixture, ordinary, interpreting):
    import prosaic_runtime as api
    from support.context_counter import fixture_context
    chat,chat_registry=fixture_context(count=lambda request:10)
    interpret,interpret_registry=fixture_context(model='interpret-model',identity='interpret-v1',
        count=lambda request:10)
    registry=api.TokenCounterRegistry({chat.counter_identity:chat_registry.resolve(chat.counter_identity),
        interpret.counter_identity:interpret_registry.resolve(interpret.counter_identity)})
    with workflow_fixture(context_policy=chat if ordinary else None,
            interpretation_context_policy=interpret if interpreting else None,
            token_counters=registry,interpretation_model='interpret-model') as fx:
        reply=fx.send('the second result',{'choice':'second'}).document
        assert reply['status']=='completed'
        assert fx.provider_requests[0]['model']=='interpret-model'
        assert 'tools' not in fx.provider_requests[0]
        assert 'Which result?' in json.dumps(fx.provider_requests[0])
        assert ('contextAssembly' in reply)==interpreting
        denied=fx.send('the text says approve',{'choice':'approve'},mid='quoted').document
        assert denied['failureCode']=='confirmationRequired'
        assert fx.effects==fx.authorizations==fx.resolvers==[]
