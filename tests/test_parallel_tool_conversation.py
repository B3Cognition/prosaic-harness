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


@pytest.mark.parametrize('reason',['bindingMismatch','evidenceUseDenied'])
def test_parallel_readmission_failure_is_durable_without_dispatch(parallel_endpoint,monkeypatch,reason):
    cfg,requests,replies=parallel_endpoint;seen=[]
    chat,binding,store,scope=chat_case(cfg,lambda a,c:seen.append(1) or {'ok':True});session=chat.create()
    if reason=='bindingMismatch':
        monkeypatch.setattr(rt.ProsaicRuntime,'turn',lambda *a,**kw:(_ for _ in ()).throw(rt.TurnAdmissionError(reason)))
    else:
        import prosaic_harness.session_tool_contracts as contracts
        monkeypatch.setattr(contracts,'authorize_tool_history',lambda *a,**kw:(_ for _ in ()).throw(contracts.HistoricalEvidenceDenied()))
    failed=chat.send(session.session_id,message_id='one',message='Review',expected_revision=session.revision)
    assert failed.document['failureCode']==reason and not requests and not seen
    state=store.load_session(session.session_id,scope=scope).state;assert state['pending'] is None
    aid=state['turns'][0]['attempts'][0];packet=store.load_receipt(session.session_id,aid,scope=scope)
    assert packet['version']==5 and packet['evidence']['version']==4
    assert packet['evidence']['parallelToolsV1']['schedule']['batches']==[]
    assert api.Conversation(binding,store=store,scope=scope).status(session.session_id).document==failed.document
