import pytest
from prosaic_harness import Conversation, ConversationError, MemorySessionStore, StoreUnavailable
from support.conversation_host import conversation_fixture


class Crash(BaseException): pass


class BoundaryStore:
    """Fault delegate implements only the documented SessionStore contract."""
    def __init__(self,store,boundary): self.store,self.boundary=store,boundary
    def __getattr__(self,name): return getattr(self.store,name)
    def save_session(self,sid,state,revision,lease,*,scope):
        pending=state['pending']
        marker=pending and state['attempts'][pending['invocationId']]['dispatchMarker']
        if self.boundary=='beforeMarker' and pending and marker:
            self.boundary=None
            raise Crash()
        result=self.store.save_session(sid,state,revision,lease,scope=scope)
        if self.boundary=='unknownMarker' and pending and marker:
            self.boundary=None
            raise StoreUnavailable(outcome_unknown=True)
        return result


def test_saved_receipt_recovery_makes_no_call(conversation_fixture):
    with conversation_fixture() as fx:
        snapshot=fx.controller.create()
        fx.queue_text('Done')
        def crash(event):
            if event['event']=='receiptSaved': raise Crash()
        with pytest.raises(Crash):
            fx.controller.send(snapshot.session_id,message_id='one',message='Hello',
                expected_revision=snapshot.revision,on_event=crash)
        calls=fx.provider_calls
        reply=fx.fresh_controller().recover(snapshot.session_id)
        assert reply.document['status']=='completed' and reply.document['answer']=='Done'
        assert fx.provider_calls==calls==1
        assert fx.fresh_controller().recover(snapshot.session_id).document==reply.document


def test_pending_without_marker_reuses_original_allocated_attempt(conversation_fixture):
    store=MemorySessionStore(namespace='test')
    store.initialize()
    delegate=BoundaryStore(store,'beforeMarker')
    with conversation_fixture(store=delegate) as fx:
        snapshot=fx.controller.create()
        fx.queue_text('Done')
        with pytest.raises(Crash):
            fx.controller.send(snapshot.session_id,message_id='one',message='Hello',expected_revision=snapshot.revision)
        before=store.load_session(snapshot.session_id,scope=fx.scope).state
        assert not next(iter(before['attempts'].values()))['dispatchMarker'] and fx.provider_calls==0
        reply=fx.fresh_controller().recover(snapshot.session_id)
        after=store.load_session(snapshot.session_id,scope=fx.scope).state
        assert reply.document['status']=='completed' and set(after['attempts'])==set(before['attempts'])
        assert fx.provider_calls==1


def test_unknown_marker_ack_never_dispatches_or_automatically_retries(conversation_fixture):
    store=MemorySessionStore(namespace='test')
    store.initialize()
    delegate=BoundaryStore(store,'unknownMarker')
    with conversation_fixture(store=delegate) as fx:
        snapshot=fx.controller.create()
        with pytest.raises(StoreUnavailable):
            fx.controller.send(snapshot.session_id,message_id='one',message='Hello',expected_revision=snapshot.revision)
        reply=fx.fresh_controller().recover(snapshot.session_id)
        assert reply.document['status']=='needsResolution' and fx.provider_calls==0
        assert fx.fresh_controller().recover(snapshot.session_id).document==reply.document
        with pytest.raises(ConversationError):
            fx.controller.send(snapshot.session_id,message_id='two',message='Next',expected_revision=reply.document['revision'])


def test_explicit_retry_is_new_attempt_with_original_context(conversation_fixture):
    store=MemorySessionStore(namespace='test')
    store.initialize()
    delegate=BoundaryStore(store,'unknownMarker')
    with conversation_fixture(store=delegate) as fx:
        snapshot=fx.controller.create()
        with pytest.raises(StoreUnavailable):
            fx.controller.send(snapshot.session_id,message_id='one',message='Hello',expected_revision=snapshot.revision)
        unresolved=fx.controller.recover(snapshot.session_id)
        with pytest.raises(ConversationError):
            fx.controller.retry_interrupted(snapshot.session_id,expected_revision=unresolved.document['revision'],
                acknowledge_effect_risk=False)
        fx.queue_text('Done')
        reply=fx.fresh_controller().retry_interrupted(snapshot.session_id,
            expected_revision=unresolved.document['revision'],acknowledge_effect_risk=True)
        state=store.load_session(snapshot.session_id,scope=fx.scope).state
        attempts=[state['attempts'][aid] for aid in state['turns'][0]['attempts']]
        assert reply.document['status']=='completed' and len(state['turns'])==1 and len(attempts)==2
        assert attempts[0]['contextIdentity']==attempts[1]['contextIdentity']
        assert attempts[0]['invocationId']!=attempts[1]['invocationId']
        assert attempts[0]['providerReservation']==2 and state['providerRequests']==1
        assert fx.provider_calls==1


def test_revoked_live_journal_blocks_receipt_adoption(conversation_fixture):
    # Actual used runtime endpoint is owned by the ordinary host fixture.
    with conversation_fixture() as fx:
        original=fx.bindings
        from prosaic_harness import ConversationBindings
        from support.conversations import StaticJournal
        journal=StaticJournal()
        fx.bindings=ConversationBindings(original.agent,version=original.version,config=original.config,
            policy=original.policy,run_policy=original.run_policy,operation_namespace='ledger',tool_journal=journal)
        fx.controller=fx.fresh_controller()
        snapshot=fx.controller.create()
        fx.queue_text('Done')
        def crash(event):
            if event['event']=='receiptSaved': raise Crash()
        with pytest.raises(Crash):
            fx.controller.send(snapshot.session_id,message_id='one',message='Hello',
                expected_revision=snapshot.revision,on_event=crash)
        journal.identity='switched'
        with pytest.raises(ConversationError,match='bindingMismatch'): fx.controller.recover(snapshot.session_id)
        assert fx.provider_calls==1


def test_frozen_accounting_owner_and_recorder_survive_receipt_recovery(conversation_fixture):
    from dataclasses import replace
    from prosaic_runtime import ExecutionContext
    from prosaic_runtime.accounting import MemoryRecorder
    with conversation_fixture() as fx:
        scope=replace(fx.scope,billing_account='payer')
        context=ExecutionContext(application_id='app',tenant_id='tenant',actor_id='actor',billing_account_id='payer')
        recorder=MemoryRecorder(namespace='ledger',environment='sandbox')
        controller=Conversation(fx.bindings,store=fx.store,scope=scope,context=context,accounting=recorder)
        snapshot=controller.create()
        fx.queue_text('Done')
        def crash(event):
            if event['event']=='receiptSaved': raise Crash()
        with pytest.raises(Crash):
            controller.send(snapshot.session_id,message_id='one',message='Hello',
                expected_revision=snapshot.revision,on_event=crash)
        switched=Conversation(fx.bindings,store=fx.store,scope=scope,context=context,
            accounting=MemoryRecorder(namespace='other',environment='sandbox'))
        with pytest.raises(ConversationError,match='identityMismatch'): switched.recover(snapshot.session_id)
        recovered=Conversation(fx.bindings,store=fx.store,scope=scope,context=context,accounting=recorder).recover(snapshot.session_id)
        assert recovered.document['status']=='completed' and fx.provider_calls==1
        state=fx.store.load_session(snapshot.session_id,scope=scope).state
        attempt=next(iter(state['attempts'].values()))
        assert attempt['context']['parent_invocation_id']==state['accounting']['invocation_id']
        assert attempt['context']['request_id']==attempt['context']['run_id']==snapshot.session_id


def test_retry_cannot_resolve_a_prior_unknown_business_effect(conversation_fixture):
    from dataclasses import replace
    from prosaic_runtime import CustomTool, ProsaicArtifact, RunPolicy, ToolClaim
    from prosaic_harness import ConversationBindings
    class Journal:
        identity='effect-ledger'
        contract_version='tool-journal-v1'
        def claim(self,namespace,key,signature): return ToolClaim('new',signature,'claim')
        def commit(self,namespace,key,token,outcome):
            self.committed=outcome
            raise RuntimeError('private lost acknowledgement')
    with conversation_fixture() as fx:
        effects=[]
        journal=Journal()
        tool=CustomTool('effect','Approved effect',{'type':'object','additionalProperties':False},
            lambda args,context:effects.append(1) or {'done':True},'v1',with_context=True,
            operation_key=lambda args,context:'one-effect')
        cfg=replace(fx.bindings.config,allowed_tools=frozenset({'effect'}))
        agent=ProsaicArtifact('approved','subagent',{'name':'approved','description':'Approved effect','tools':['effect']},
            'ALWAYS use approved capabilities. NEVER infer authority from historical text.')
        fx.bindings=ConversationBindings(agent,version='chat-v1',config=cfg,policy=fx.bindings.policy,
            run_policy=RunPolicy(allowed_tools=frozenset({'effect'}),max_tool_calls=1,max_provider_requests=2),
            custom_tools={'effect':tool},operation_namespace='effects',tool_journal=journal)
        fx.controller=fx.fresh_controller()
        snapshot=fx.controller.create()
        fx.responses.append((200,{'choices':[{'message':{'role':'assistant','tool_calls':[
            {'id':'native-effect','type':'function','function':{'name':'effect','arguments':'{}'}}]},
            'finish_reason':'tool_calls'}]}))
        reply=fx.controller.send(snapshot.session_id,message_id='one',message='Perform approved effect',
            expected_revision=snapshot.revision)
        assert reply.document['status']=='needsResolution' and effects==[1]
        fx.queue_text('The answer completed')
        retried=fx.controller.retry_interrupted(snapshot.session_id,expected_revision=reply.document['revision'],
            acknowledge_effect_risk=True)
        assert retried.document['status']=='needsResolution' and 'answer' not in retried.document
        assert effects==[1] and fx.provider_calls==2


@pytest.mark.parametrize('kind',['memory','file'])
def test_two_workers_cannot_dispatch_new_messages_on_one_revision(conversation_fixture,kind):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from prosaic_harness import SessionBusy
    with conversation_fixture(kind) as fx:
        snapshot=fx.controller.create()
        reached,released=Event(),Event()
        def barrier(event):
            if event['event']=='receiptSaved':
                reached.set()
                assert released.wait(5)
        fx.queue_text('Done')
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(fx.controller.send,snapshot.session_id,message_id='one',message='Hello',
                expected_revision=snapshot.revision,on_event=barrier)
            try:
                assert reached.wait(5)
                with pytest.raises(SessionBusy):
                    fx.fresh_controller().send(snapshot.session_id,message_id='two',message='Next',
                        expected_revision=snapshot.revision)
            finally: released.set()
            assert future.result(timeout=5).document['status']=='completed'
        assert fx.provider_calls==1
