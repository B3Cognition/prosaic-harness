import json
from dataclasses import replace
import pytest
import prosaic_runtime as api
from prosaic_harness import (Conversation,ConversationBindings,ConversationScope,ConversationPolicy,
    MemorySessionStore,FileSessionStore,ContextPackBindings,ContextAuthorizer,ContextPackSpec,ContextSlot,
    ContextPacker,ContextPackReader,InputSource,ConversationError)
from prosaic_harness.context_packs.sources import capture_sources
from support.context_pack_cases import scope_case
from test_workflow_rules_execution import rule_endpoint


def pack_chat(cfg,tmp_path,*,kind='memory',authorize=lambda use:True,reader=None,guards=(),
              context_policy=None,token_counters=None,policy=None):
    spec=ContextPackSpec('chat','1',[ContextSlot('task',required=True),
        ContextSlot('facts',availability='discoverable' if reader else 'inline')],task_source='task')
    packs=ContextPackBindings(specs={'chat':spec},sources={'task':InputSource('/task'),'facts':InputSource('/facts')},
        scope=scope_case(),authorizer=ContextAuthorizer('access','1',authorize))
    tools={'read_context_item':reader.as_tool()} if reader else {}
    cfg=replace(cfg,allowed_tools=frozenset(tools))
    body='ALWAYS answer from selected evidence. NEVER invent facts.'
    if guards: body+='\nALWAYS check captured facts. <!-- enforce: facts(stage=final, on_violation=fail) -->'
    binding=ConversationBindings(api.ProsaicArtifact('chat','subagent',{'name':'chat','description':'Pack chat','tools':list(tools)},body),
        version='chat-pack-1',config=cfg,policy=policy or ConversationPolicy(),custom_tools=tools,guards=guards,
        run_policy=api.RunPolicy(allowed_tools=frozenset(tools),max_provider_requests=3,max_tool_calls=2 if reader else 0),
        context_policy=context_policy,token_counters=token_counters,context_packs=packs)
    store=MemorySessionStore(namespace='test') if kind=='memory' else FileSessionStore(tmp_path/'sessions',namespace='test')
    store.initialize(context_packs=True)
    scope=ConversationScope('test','sandbox','app','tenant','actor')
    chat=Conversation(binding,store=store,scope=scope)
    def candidates(task='Review',facts='OPTIONAL-FACT-719'):
        return ContextPacker().compose(spec,capture_sources(spec,{'request':{'task':task,'facts':facts}}, {},packs))
    return chat,candidates,store,scope


@pytest.mark.parametrize('kind',['memory','file'])
def test_send_accepts_host_candidates_without_workflow(rule_endpoint,tmp_path,kind):
    cfg,requests,replies=rule_endpoint;replies.append('Answer')
    chat,candidates,store,scope=pack_chat(cfg,tmp_path,kind=kind)
    session=chat.create();pack=candidates()
    reply=chat.send(session.session_id,message_id='first',message='Exact current question',
        expected_revision=session.revision,context_pack=pack)
    assert reply.document['answer']=='Answer'
    payload=json.dumps(requests[0]);assert 'Review' in payload and 'OPTIONAL-FACT-719' not in payload
    state=store.load_session(session.session_id,scope=scope).state
    assert state['version']==3 and state['turns'][0]['message']=='Exact current question'
    assert 'contextPack' not in json.dumps([m.to_dict() for m in chat.history(session.session_id)])
    aid=state['turns'][0]['attempts'][0]
    receipt=store.load_receipt(session.session_id,aid,scope=scope)
    assert receipt['version']==3 and receipt['encodingVersion']=='conversation-turn-v3'
    assert Conversation(chat.bindings,store=store,scope=scope).status(session.session_id).document==reply.document


def test_same_message_id_changed_pack_conflicts(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint;replies.append('Answer')
    chat,candidates,store,scope=pack_chat(cfg,tmp_path);session=chat.create()
    args=dict(message_id='first',message='Question',expected_revision=session.revision)
    chat.send(session.session_id,context_pack=candidates(),**args)
    with pytest.raises(ConversationError,match='messageConflict'):
        chat.send(session.session_id,context_pack=candidates(facts='Changed capture'),**args)
    assert len(requests)==1


def test_exact_replay_never_recaptures_or_dispatches(rule_endpoint,tmp_path,monkeypatch):
    cfg,requests,replies=rule_endpoint;replies.append('Answer')
    chat,candidates,store,scope=pack_chat(cfg,tmp_path);session=chat.create();pack=candidates()
    args=dict(message_id='first',message='Question',expected_revision=session.revision,context_pack=pack)
    reply=chat.send(session.session_id,**args)
    monkeypatch.setattr(ContextPacker,'compose',lambda *a,**k:pytest.fail('replay recomposed'))
    replay=Conversation(chat.bindings,store=store,scope=scope).send(session.session_id,**args)
    assert replay.document==reply.document and len(requests)==1


def test_private_guards_receive_complete_capture_with_smaller_model_input(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint;replies.append('Answer');seen=[]
    guard=api.Guard('facts','1',('final',),lambda stage,context:seen.append(context) or api.Verdict(True),
        input_access='authoritativeAndModel')
    chat,candidates,store,scope=pack_chat(cfg,tmp_path,guards=[guard]);session=chat.create()
    reply=chat.send(session.session_id,message_id='first',message='Question',expected_revision=session.revision,context_pack=candidates())
    assert reply.document['status']=='completed' and len(seen)==1
    assert 'OPTIONAL-FACT-719' in json.dumps(seen[0].authoritative_input_data)
    assert 'OPTIONAL-FACT-719' not in json.dumps([requests,seen[0].input_data])


def test_counted_conversation_uses_one_variant_budget_and_durable_work(rule_endpoint,tmp_path):
    from support.context_counter import fixture_context
    cfg,requests,replies=rule_endpoint;replies.append('Answer');calls=[]
    policy,counters=fixture_context(cfg.profiles['local'].provider,count=lambda request:calls.append(request) or 10)
    chat,candidates,store,scope=pack_chat(cfg,tmp_path,context_policy=policy,token_counters=counters);session=chat.create()
    reply=chat.send(session.session_id,message_id='first',message='Question',expected_revision=session.revision,context_pack=candidates())
    assert reply.document['status']=='completed' and 'OPTIONAL-FACT-719' in json.dumps(requests[0])
    state=store.load_session(session.session_id,scope=scope).state
    frame=next(iter(state['contextPacks']['attempts'].values()))
    assert frame['contextWork']['checkpointSequence']>=2 and frame['contextWork']['reservedActiveMicros']==0
    assert len(calls)>=3


def test_request_identity_binds_full_candidate_plan(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint;replies.extend(['Answer']*2)
    chat,candidates,store,scope=pack_chat(cfg,tmp_path);identities=[]
    for value in ('First facts','Changed facts'):
        session=chat.create()
        chat.send(session.session_id,message_id='first',message='Same question',expected_revision=session.revision,context_pack=candidates(facts=value))
        identities.append(store.load_session(session.session_id,scope=scope).state['turns'][0]['requestIdentity'])
    assert identities[0]!=identities[1]


@pytest.mark.parametrize('damage',['scope','sourceIdentity','spec','dictionary'])
def test_unbound_pack_is_refused_before_provider_or_pending_write(rule_endpoint,tmp_path,damage):
    from prosaic_harness import ContextSnapshot,ContextScope
    cfg,requests,replies=rule_endpoint
    chat,candidates,store,scope=pack_chat(cfg,tmp_path);session=chat.create();pack=candidates()
    if damage=='dictionary': value=pack.to_dict()
    else:
        snapshot=pack.snapshot.to_dict();spec=pack.spec
        if damage=='scope': snapshot['scopeBinding']=ContextScope('test','sandbox','app','foreign','actor').to_dict()
        elif damage=='sourceIdentity': snapshot['sources'][0]['sourceIdentity']='unbound'
        else:
            raw=spec.to_dict();raw['specIdentity']='unbound';spec=ContextPackSpec.from_dict(raw)
        value=ContextPacker().compose(spec,ContextSnapshot.from_dict(snapshot))
    with pytest.raises(ConversationError):
        chat.send(session.session_id,message_id='first',message='Question',expected_revision=session.revision,context_pack=value)
    assert requests==[] and store.load_session(session.session_id,scope=scope)==session


def test_cancelled_pack_retains_exact_failed_user_and_can_retry_explicitly(rule_endpoint,tmp_path,monkeypatch):
    cfg,requests,replies=rule_endpoint;replies.append('Answer')
    chat,candidates,store,scope=pack_chat(cfg,tmp_path);session=chat.create();pack=candidates()
    failed=chat.send(session.session_id,message_id='first',message='Exact question',expected_revision=session.revision,
        context_pack=pack,cancelled=lambda:True)
    assert failed.document['status']=='failed' and failed.document['failureCode']=='cancelled' and requests==[]
    assert chat.history(session.session_id)[0].to_dict()['content']==[{'type':'text','text':'Exact question'}]
    monkeypatch.setattr(ContextPacker,'compose',lambda *a,**k:pytest.fail('retry recomposed'))
    reply=chat.retry_failed(session.session_id,expected_revision=failed.document['revision'],acknowledge_effect_risk=True)
    assert reply.document['status']=='completed' and len(requests)==1
