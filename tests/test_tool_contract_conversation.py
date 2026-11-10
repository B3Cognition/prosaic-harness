from dataclasses import replace
import json
import re
import pytest
import prosaic_harness as api
import prosaic_runtime as runtime_api
from test_workflow_rules_execution import rule_endpoint
from test_tool_contract_workflow import flow,queue_answer


def chat_case(cfg,*,calls,grant=lambda use:True):
    workflow=flow(cfg,calls=calls,grant=grant)
    bindings=api.ConversationBindings(workflow.artifacts['review'],version='chat-contract-v1',config=workflow.config,
        policy=api.ConversationPolicy(),run_policy=runtime_api.RunPolicy(allowed_tools=frozenset({'lookup'}),
            max_provider_requests=2,max_tool_calls=1),custom_tools=workflow.custom_tools,
        tool_contracts=workflow._tool_contracts,operation_namespace='tenant')
    store=api.MemorySessionStore(namespace='test');store.initialize(tool_contracts=True)
    scope=api.ConversationScope('test','sandbox','app','tenant','actor')
    return api.Conversation(bindings,store=store,scope=scope),bindings,store,scope


def test_conversation_answer_and_citations_are_saved_together(rule_endpoint):
    cfg,requests,replies=rule_endpoint;calls=[]
    chat,bindings,store,scope=chat_case(cfg,calls=calls)
    created=chat.create();queue_answer(replies)
    result=chat.send(created.session_id,message_id='one',message='Review',expected_revision=created.revision)
    assert result.document['status']=='completed' and result.document['citations']['markers']
    assert 'PRIVATE-LOCATOR' not in json.dumps(result.document)
    state=store.load_session(created.session_id,scope=scope).state
    aid=state['turns'][0]['attempts'][0];receipt=store.load_receipt(created.session_id,aid,scope=scope)
    assert state['version']==receipt['version']==4 and receipt['toolContractV1'] is not None
    assert len(requests)==2 and calls==[1]


def test_old_id_in_text_grants_nothing(rule_endpoint):
    cfg,requests,replies=rule_endpoint;calls=[]
    chat,_,_,_=chat_case(cfg,calls=calls)
    created=chat.create();queue_answer(replies)
    first=chat.send(created.session_id,message_id='one',message='Review',expected_revision=created.revision)
    evidence_id=first.document['citations']['markers'][0]['evidenceId']
    replies.append(f'Old source [cite:{evidence_id}]')
    second=chat.send(created.session_id,message_id='two',message=f'Reuse {evidence_id}',expected_revision=first.document['revision'])
    assert second.document['status']=='failed' and second.document['failureCode']=='citationViolation'
    assert len(requests)==3 and calls==[1]


def test_saved_conversation_receipt_adopts_without_new_work(rule_endpoint):
    cfg,requests,replies=rule_endpoint;calls=[]
    chat,bindings,store,scope=chat_case(cfg,calls=calls)
    created=chat.create();queue_answer(replies)
    def crash(event):
        if event['event']=='receiptSaved': raise OSError('crash after receipt')
    with pytest.raises(OSError): chat.send(created.session_id,message_id='one',message='Review',expected_revision=created.revision,on_event=crash)
    result=api.Conversation(bindings,store=store,scope=scope).recover(created.session_id)
    assert result.document['status']=='completed' and result.document['citations']['markers']
    assert len(requests)==2 and calls==[1]


def test_next_turn_requires_explicit_retained_import(rule_endpoint):
    cfg,requests,replies=rule_endpoint;calls=[]
    chat,_,store,scope=chat_case(cfg,calls=calls)
    created=chat.create();queue_answer(replies)
    first=chat.send(created.session_id,message_id='one',message='Review',expected_revision=created.revision)
    state=store.load_session(created.session_id,scope=scope).state
    aid=state['turns'][0]['attempts'][0]
    old_id=first.document['citations']['markers'][0]['evidenceId']
    retained=chat.retain_citation(created.session_id,aid,old_id)
    def answer(payload):
        source=re.findall(r'ev_[0-9a-f]{64}',json.dumps(payload))[-1]
        assert source!=old_id
        return f'Retained source [cite:{source}]'
    replies.append(answer)
    second=chat.send(created.session_id,message_id='two',message='Use retained evidence',expected_revision=first.document['revision'],
        retained_evidence=(retained,))
    assert second.document['status']=='completed' and len(requests)==3 and calls==[1]


def test_cross_tenant_receipt_is_refused(rule_endpoint):
    cfg,requests,replies=rule_endpoint;calls=[]
    chat,bindings,store,scope=chat_case(cfg,calls=calls)
    created=chat.create();queue_answer(replies)
    result=chat.send(created.session_id,message_id='one',message='Review',expected_revision=created.revision)
    state=store.load_session(created.session_id,scope=scope).state
    aid=state['turns'][0]['attempts'][0]
    foreign=api.Conversation(bindings,store=store,scope=replace(scope,tenant='other'))
    with pytest.raises(api.SessionNotFound): foreign.retain_citation(created.session_id,aid,result.document['citations']['markers'][0]['evidenceId'])
    assert len(requests)==2


def test_revoked_source_cannot_be_viewed_or_imported(rule_endpoint):
    cfg,requests,replies=rule_endpoint;calls=[];allowed=[True]
    chat,_,store,scope=chat_case(cfg,calls=calls,grant=lambda use:allowed[0])
    created=chat.create();queue_answer(replies)
    first=chat.send(created.session_id,message_id='one',message='Review',expected_revision=created.revision)
    state=store.load_session(created.session_id,scope=scope).state;aid=state['turns'][0]['attempts'][0]
    eid=first.document['citations']['markers'][0]['evidenceId'];ref=chat.retain_citation(created.session_id,aid,eid)
    assert chat.citation_view(created.session_id,aid,eid)['available']
    allowed[0]=False
    assert not chat.citation_view(created.session_id,aid,eid)['available']
    replies.append('Should never be requested')
    denied=chat.send(created.session_id,message_id='two',message='Reuse',expected_revision=first.document['revision'],retained_evidence=(ref,))
    assert denied.document['failureCode']=='evidenceUseDenied' and len(requests)==2 and calls==[1]


def test_undispatched_turn_restores_without_new_identity(rule_endpoint,monkeypatch):
    cfg,requests,replies=rule_endpoint;calls=[]
    chat,bindings,store,scope=chat_case(cfg,calls=calls);created=chat.create();queue_answer(replies)
    original=chat._execute
    monkeypatch.setattr(chat,'_execute',lambda *args: (_ for _ in ()).throw(OSError('before dispatch')))
    with pytest.raises(OSError):chat.send(created.session_id,message_id='one',message='Review',expected_revision=created.revision)
    result=api.Conversation(bindings,store=store,scope=scope).recover(created.session_id)
    assert result.document['status']=='completed' and len(requests)==2 and calls==[1]


def test_pack_conversation_uses_selected_citable_bytes(rule_endpoint,tmp_path):
    from test_context_pack_conversation import pack_chat
    from prosaic_harness.session_contracts import seal
    cfg,requests,replies=rule_endpoint
    legacy,candidates,_,scope=pack_chat(cfg,tmp_path)
    contracts=api.ToolContracts('packs','1',evidence_authorizer=runtime_api.EvidenceAuthorizerV1('evidence','1',lambda use:True),citations=runtime_api.CitationPolicyV1('required'))
    bindings=api.ConversationBindings(legacy.bindings.agent,version='cited-pack',config=legacy.bindings.config,policy=api.ConversationPolicy(),
        run_policy=legacy.bindings.run_policy,context_packs=legacy.bindings.context_packs,tool_contracts=contracts)
    store=api.MemorySessionStore(namespace='test');store.initialize(context_packs=True,tool_contracts=True)
    chat=api.Conversation(bindings,store=store,scope=scope);session=chat.create()
    replies.append(lambda payload:'Selected [cite:'+re.search(r'ctx_[0-9a-f]{64}',json.dumps(payload)).group()+']')
    result=chat.send(session.session_id,message_id='one',message='Review',expected_revision=session.revision,context_pack=candidates())
    assert result.document['status']=='completed' and len(requests)==1
    state=store.load_session(session.session_id,scope=scope).state;aid=state['turns'][0]['attempts'][0]
    assert chat.citation_view(session.session_id,aid,result.document['citations']['markers'][0]['evidenceId'])['content']=='Review'


def test_cancelled_before_dispatch_can_retry_with_new_scope(rule_endpoint):
    cfg,requests,replies=rule_endpoint;calls=[]
    chat,_,store,scope=chat_case(cfg,calls=calls);session=chat.create()
    failed=chat.send(session.session_id,message_id='one',message='Review',expected_revision=session.revision,cancelled=lambda:True)
    assert failed.document['failureCode']=='cancelled' and requests==[]
    queue_answer(replies)
    result=chat.retry_failed(session.session_id,expected_revision=failed.document['revision'],acknowledge_effect_risk=True)
    assert result.document['status']=='completed' and calls==[1] and len(requests)==2
    attempts=list(store.load_session(session.session_id,scope=scope).state['attempts'].values())
    assert attempts[0]['contextIdentity']!=attempts[1]['contextIdentity']


def test_retained_events_require_a_current_separate_display_grant(rule_endpoint):
    cfg,requests,replies=rule_endpoint;calls=[]
    chat,bindings,store,scope=chat_case(cfg,calls=calls);session=chat.create();queue_answer(replies)
    chat.send(session.session_id,message_id='one',message='Review',expected_revision=session.revision)
    aid=store.load_session(session.session_id,scope=scope).state['turns'][0]['attempts'][0]
    receipt=api.VerifiedToolReceipt.from_session_store(store,session.session_id,aid,bindings=bindings,scope=scope)
    events=receipt.to_dict()['toolContractV1']['events'];index=next(i for i,e in enumerate(events) if e['event']=='tool_completed')
    granted=api.project_retained_tool_event(receipt,index,api.ToolContractViewBindings(scope,display_authorizer=bindings.tool_contracts.display_authorizer),bindings._tools)
    denied=api.project_retained_tool_event(receipt,index,api.ToolContractViewBindings(scope),bindings._tools)
    assert granted['event']['toolEventV1']['display']=={'count':14}
    assert 'display' not in denied['event']['toolEventV1']


def test_deferred_read_cites_exact_read_and_keeps_parent_private(rule_endpoint,tmp_path):
    from test_context_pack_conversation import pack_chat
    cfg,requests,replies=rule_endpoint
    legacy,candidates,_,scope=pack_chat(cfg,tmp_path,reader=api.ContextPackReader())
    reader=api.ContextPackReader(tool_contracts=True)
    contracts=api.ToolContracts('read','1',evidence_authorizer=runtime_api.EvidenceAuthorizerV1('access','1',lambda use:True),citations=runtime_api.CitationPolicyV1('required'))
    bindings=api.ConversationBindings(legacy.bindings.agent,version='cited-read',config=legacy.bindings.config,
        policy=api.ConversationPolicy(),custom_tools={'read_context_item':reader.as_tool()},
        run_policy=legacy.bindings.run_policy,context_packs=legacy.bindings.context_packs,tool_contracts=contracts)
    store=api.MemorySessionStore(namespace='test');store.initialize(tool_contracts=True,context_packs=True)
    chat=api.Conversation(bindings,store=store,scope=scope);session=chat.create();pack=candidates()
    parent=pack.variants[0]['index'][0]['citationId']
    replies.extend([{'name':'read_context_item','input':{'citationId':parent}},
        lambda payload:'Read [cite:'+re.findall(r'ev_[0-9a-f]{64}',json.dumps(payload))[-1]+']'])
    result=chat.send(session.session_id,message_id='one',message='Read selected source',expected_revision=session.revision,context_pack=pack)
    assert result.document['status']=='completed' and len(requests)==2 and reader.active_count==0
    assert 'OPTIONAL-FACT-719' not in json.dumps(requests[0]) and 'OPTIONAL-FACT-719' in json.dumps(requests[1])
    eid=result.document['citations']['markers'][0]['evidenceId'];assert eid!=parent
