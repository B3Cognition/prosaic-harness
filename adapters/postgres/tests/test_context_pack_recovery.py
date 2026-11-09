import uuid
from dataclasses import replace
import psycopg
import pytest
from prosaic_harness import ConversationScope,LeaseLost,ReceiptConflict,SessionNotFound
from prosaic_harness.session_contracts import make_receipt,adopt_receipt,seal
from prosaic_harness.session_context import checkpoint_context_work
from prosaic_harness_postgres import PostgresSessionStore
from support.session_documents import pack_document,pack_failure
from support.session_workers import SessionWorker


def test_pack_receipt_is_adopted_in_fresh_process_without_recapture(db_admin_dsn):
    scope=ConversationScope('conversation-workers','sandbox','chat','tenant','actor');sid=uuid.uuid4().hex
    state,frame=pack_document(scope,session_id=sid)
    packet=make_receipt(state,frame.invocation_id,pack_failure(frame))
    with PostgresSessionStore(db_admin_dsn,namespace=scope.namespace) as store:
        store.initialize(context_packs=True)
        with store.lease(sid,scope=scope) as lease:
            store.create_session(sid,state,lease,scope=scope)
            store.save_receipt(sid,frame.invocation_id,packet,lease,scope=scope)
    with SessionWorker(db_admin_dsn,sid,'recover') as worker:
        assert worker.result()['receiptAdopted'] is True
    with PostgresSessionStore(db_admin_dsn,namespace=scope.namespace) as restarted:
        loaded=restarted.load_session(sid,scope=scope).state
        assert loaded==adopt_receipt(state,packet)


def test_pack_context_checkpoint_is_fenced_and_owner_filtered(db_admin_dsn):
    from prosaic_runtime import ContextWorkState
    scope=ConversationScope('pack-tests','sandbox','chat','tenant','actor');sid=uuid.uuid4().hex
    state,frame=pack_document(scope,session_id=sid,counted=True)
    with PostgresSessionStore(db_admin_dsn,namespace=scope.namespace) as store:
        store.initialize(context_packs=True)
        with store.lease(sid,scope=scope) as lease:
            revision=store.create_session(sid,state,lease,scope=scope)
            before=frame.context_work.to_dict()
            work=ContextWorkState.from_dict({**before,'checkpointSequence':before['checkpointSequence']+1,
                'reservedActiveMicros':2000000-before['activeAssemblyMicros']})
            changed=checkpoint_context_work(state,frame.invocation_id,work)
            current=store.save_session(sid,changed,revision,lease,scope=scope)
            with pytest.raises(SessionNotFound): store.load_session(sid,scope=replace(scope,actor='foreign'))
            with psycopg.connect(db_admin_dsn) as admin:
                admin.execute('UPDATE prosaic_harness_conversations.leases SET generation=generation+1 WHERE namespace=%s AND session_id=%s',(scope.namespace,sid))
            with pytest.raises(LeaseLost): store.save_session(sid,changed,current,lease,scope=scope)


def test_pack_receipt_survives_database_restart(owned_cluster):
    scope=ConversationScope('pack-tests','sandbox','chat','tenant','actor');sid=uuid.uuid4().hex
    state,frame=pack_document(scope,session_id=sid)
    packet=make_receipt(state,frame.invocation_id,pack_failure(frame))
    with PostgresSessionStore(owned_cluster.dsn,namespace=scope.namespace) as store:
        store.initialize(context_packs=True)
        with store.lease(sid,scope=scope) as lease:
            store.create_session(sid,state,lease,scope=scope)
            store.save_receipt(sid,frame.invocation_id,packet,lease,scope=scope)
    owned_cluster.crash_restart()
    with PostgresSessionStore(owned_cluster.dsn,namespace=scope.namespace) as store:
        assert store.load_receipt(sid,frame.invocation_id,scope=scope)==packet
        with store.lease(sid,scope=scope) as lease:
            snapshot=store.load_session(sid,scope=scope)
            store.save_session(sid,adopt_receipt(snapshot.state,packet),snapshot.revision,lease,scope=scope)
            forged=seal({**packet,'result':{**packet['result'],'timedOut':True}})
            with pytest.raises(ReceiptConflict): store.save_receipt(sid,frame.invocation_id,forged,lease,scope=scope)


def test_two_workers_cannot_advance_v3_revision_twice(db_admin_dsn):
    scope=ConversationScope('conversation-workers','sandbox','chat','tenant','actor');sid=uuid.uuid4().hex
    state,frame=pack_document(scope,session_id=sid)
    packet=make_receipt(state,frame.invocation_id,pack_failure(frame))
    with PostgresSessionStore(db_admin_dsn,namespace=scope.namespace) as store:
        store.initialize(context_packs=True)
        with store.lease(sid,scope=scope) as lease:
            revision=store.create_session(sid,state,lease,scope=scope)
            store.save_receipt(sid,frame.invocation_id,packet,lease,scope=scope)
            revision=store.save_session(sid,adopt_receipt(state,packet),revision,lease,scope=scope)
    with SessionWorker(db_admin_dsn,sid,'advance',revision=revision) as first,SessionWorker(db_admin_dsn,sid,'advance',revision=revision) as second:
        results=[first.result(allow_error=True),second.result(allow_error=True)]
    assert sum(result.get('status')=='pending' for result in results)==1
    assert any(result.get('error') in {'session_busy','revision_conflict'} for result in results)


def test_public_pack_conversation_reopens_and_replays_without_dispatch(db_admin_dsn,model_server,monkeypatch):
    from prosaic_runtime import RuntimeConfig,EndpointConfig,ProsaicArtifact,RunPolicy
    from prosaic_harness import (Conversation,ConversationBindings,ConversationPolicy,ContextScope,
        ContextPackBindings,ContextAuthorizer,ContextPackSpec,ContextSlot,InputSource,ContextPacker)
    from prosaic_harness.context_packs import capture_sources
    from prosaic_harness import StoreUnavailable
    scope=ConversationScope('pack-controller','sandbox','chat','tenant','actor')
    spec=ContextPackSpec('chat','1',[ContextSlot('task',required=True)],task_source='task')
    packs=ContextPackBindings(specs={'chat':spec},sources={'task':InputSource('/task')},
        scope=ContextScope.from_conversation(scope),authorizer=ContextAuthorizer('access','1',lambda use:True))
    config=RuntimeConfig({'local':EndpointConfig(model_server.url,'synthetic',features={'streaming':False})},{},'local',frozenset())
    binding=ConversationBindings(ProsaicArtifact('chat','subagent',{'name':'chat','description':'Captured chat'},
        'ALWAYS use supplied evidence. NEVER invent facts.'),version='pack-chat-1',config=config,
        policy=ConversationPolicy(),run_policy=RunPolicy(max_provider_requests=2,max_tool_calls=0),context_packs=packs)
    candidates=ContextPacker().compose(spec,capture_sources(spec,{'request':{'task':'Review retained facts'}},{},packs))
    with PostgresSessionStore(db_admin_dsn,namespace=scope.namespace) as store:
        store.initialize(context_packs=True)
        chat=Conversation(binding,store=store,scope=scope);session=chat.create()
        monkeypatch.setattr(chat,'_adopt',lambda *a,**k:(_ for _ in ()).throw(OSError('after receipt')))
        with pytest.raises((OSError,StoreUnavailable)):
            chat.send(session.session_id,message_id='first',message='Exact question',expected_revision=session.revision,context_pack=candidates)
    monkeypatch.setattr(ContextPacker,'compose',lambda *a,**k:pytest.fail('SQL recovery recomposed'))
    with PostgresSessionStore(db_admin_dsn,namespace=scope.namespace) as store:
        chat=Conversation(binding,store=store,scope=scope)
        reply=chat.recover(session.session_id)
        assert reply.document['status']=='completed' and model_server.request_count==1
        assert chat.send(session.session_id,message_id='first',message='Exact question',expected_revision=session.revision,
            context_pack=candidates).document==reply.document
        saved=store.load_session(session.session_id,scope=scope).state
        assert saved['version']==3 and saved['pending'] is None and len(chat.history(session.session_id))==2
