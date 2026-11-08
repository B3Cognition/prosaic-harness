import pytest
from prosaic_harness import Conversation,ConversationError,ContextPacker
from test_context_pack_conversation import pack_chat
from test_workflow_rules_execution import rule_endpoint


def test_denied_retained_read_allows_internal_receipt_adoption(rule_endpoint,tmp_path,monkeypatch):
    cfg,requests,replies=rule_endpoint;replies.append('Answer');denied=[False]
    chat,candidates,store,scope=pack_chat(cfg,tmp_path,authorize=lambda use:not (denied[0] and use.purpose=='retainedRead'))
    session=chat.create();save=store.save_receipt
    def lost(*args,**kwargs):
        save(*args,**kwargs)
        raise OSError('after durable receipt')
    monkeypatch.setattr(store,'save_receipt',lost)
    with pytest.raises(OSError):
        chat.send(session.session_id,message_id='first',message='Question',expected_revision=session.revision,context_pack=candidates())
    monkeypatch.setattr(ContextPacker,'compose',lambda *a,**k:pytest.fail('adoption recomposed'))
    denied[0]=True
    with pytest.raises(ConversationError,match='contextUseDenied'):
        Conversation(chat.bindings,store=store,scope=scope).recover(session.session_id)
    state=store.load_session(session.session_id,scope=scope).state
    assert state['pending'] is None and state['turns'][0]['status']=='completed' and len(requests)==1


@pytest.mark.parametrize('guarded',[False,True])
def test_profiled_execution_readmission_failure_is_a_durable_failed_turn(rule_endpoint,tmp_path,monkeypatch,guarded):
    import prosaic_runtime as api
    cfg,requests,replies=rule_endpoint
    guards=[api.Guard('facts','1',('final',),lambda *a:pytest.fail('failed readmission ran guard'),input_access='authoritativeAndModel')] if guarded else []
    chat,candidates,store,scope=pack_chat(cfg,tmp_path,guards=guards);session=chat.create()
    monkeypatch.setattr(api.ProsaicRuntime,'turn',lambda *a,**k:(_ for _ in ()).throw(api.TurnAdmissionError('bindingMismatch')))
    reply=chat.send(session.session_id,message_id='first',message='Question',expected_revision=session.revision,context_pack=candidates())
    assert reply.document['status']=='failed' and reply.document['failureCode']=='bindingMismatch' and requests==[]
    assert store.load_session(session.session_id,scope=scope).state['pending'] is None


@pytest.mark.parametrize('phase',['reserve','dispatch','work'])
@pytest.mark.parametrize('kind',['memory','file'])
def test_recovery_uses_frozen_context_and_requires_consent_for_unknown_work(rule_endpoint,tmp_path,monkeypatch,phase,kind):
    from prosaic_harness import StoreUnavailable
    from support.context_counter import fixture_context
    cfg,requests,replies=rule_endpoint;replies.append('Answer');counts=[]
    options={}
    if phase=='work':
        policy,counters=fixture_context(cfg.profiles['local'].provider,count=lambda request:counts.append(request) or 10)
        options=dict(context_policy=policy,token_counters=counters)
    chat,candidates,store,scope=pack_chat(cfg,tmp_path,kind=kind,**options);session=chat.create();save=store.save_session
    def lost(sid,state,revision,lease,**kwargs):
        result=save(sid,state,revision,lease,**kwargs)
        if state['pending']:
            attempt=state['attempts'][state['pending']['invocationId']]
            if ((phase=='reserve' and not attempt['dispatchMarker']) or
                    (phase=='dispatch' and attempt['dispatchMarker']) or
                    (phase=='work' and attempt['contextWork']['reservedActiveMicros'])):
                raise OSError('after durable '+phase)
        return result
    monkeypatch.setattr(store,'save_session',lost)
    with pytest.raises((OSError,StoreUnavailable)):
        chat.send(session.session_id,message_id='first',message='Exact question',expected_revision=session.revision,context_pack=candidates())
    assert requests==[]
    monkeypatch.setattr(store,'save_session',save)
    monkeypatch.setattr(ContextPacker,'compose',lambda *a,**k:pytest.fail('recovery recomposed'))
    count=len(counts);recovered=Conversation(chat.bindings,store=store,scope=scope).recover(session.session_id)
    if phase=='reserve':
        assert recovered.document['status']=='completed' and len(requests)==1
    else:
        assert recovered.document['status']=='needsResolution' and len(counts)==count and requests==[]
        reply=Conversation(chat.bindings,store=store,scope=scope).retry_interrupted(session.session_id,
            expected_revision=recovered.document['revision'],acknowledge_effect_risk=True)
        assert reply.document['status']=='completed' and len(requests)==1
        state=store.load_session(session.session_id,scope=scope).state
        assert len(state['attempts'])==2
        frames=[state['contextPacks']['attempts'][aid] for aid in state['turns'][0]['attempts']]
        assert [frame['executionEpoch'] for frame in frames]==[1,2]
