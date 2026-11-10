from threading import Barrier
import pytest
import prosaic_harness as api
import prosaic_runtime as rt
from support.parallel_tools import parallel_endpoint,queue_batch
from test_parallel_tool_workflow import factory,proposal


def chat_case(cfg,handler,store=None):
    workflow=factory(cfg,handler=handler).build(proposal())
    binding=api.ConversationBindings(workflow.artifacts['review'],version='parallel-v1',config=workflow.config,policy=api.ConversationPolicy(),run_policy=rt.RunPolicy(allowed_tools=frozenset({'lookup'}),max_provider_requests=3,max_tool_calls=4,parallel_tools=rt.ParallelToolPolicyV1(max_concurrency=2)),custom_tools=workflow.custom_tools,tool_contracts=workflow._tool_contracts)
    if store is None:store=api.MemorySessionStore(namespace='test');store.initialize(parallel_tools=True)
    scope=api.ConversationScope('test','sandbox','app','tenant','actor')
    return api.Conversation(binding,store=store,scope=scope),binding,store,scope


def test_parallel_session_receipt_retains_and_reopens(parallel_endpoint):
    cfg,requests,replies=parallel_endpoint;seen=[];gate=Barrier(2)
    def read(a,c):seen.append(c.call_index);gate.wait(timeout=2);return {'ok':True}
    chat,binding,store,scope=chat_case(cfg,read);session=chat.create();queue_batch(replies)
    result=chat.send(session.session_id,message_id='one',message='Review',expected_revision=session.revision)
    assert result.document['status']=='completed' and sorted(seen)==[0,1]
    state=store.load_session(session.session_id,scope=scope).state;assert state['version']==5
    receipt=store.load_receipt(session.session_id,state['turns'][0]['attempts'][0],scope=scope)
    assert receipt['version']==5 and receipt['evidence']['version']==4
    before=len(requests);assert api.Conversation(binding,store=store,scope=scope).status(session.session_id).document==result.document
    assert len(requests)==before
