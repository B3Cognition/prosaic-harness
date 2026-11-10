from threading import Barrier
import pytest
import prosaic_harness as api
from support.parallel_tools import parallel_endpoint,queue_batch
from test_parallel_tool_workflow import factory,proposal


def test_parallel_workflow_receipt_adopts_without_redispatch(parallel_endpoint,tmp_path,monkeypatch):
    cfg,requests,replies=parallel_endpoint;seen=[];gate=Barrier(2)
    def read(a,c):seen.append(c.call_index);gate.wait(timeout=2);return {'ok':True}
    workflow=factory(cfg,handler=read).build(proposal());store=api.FileRunStore(tmp_path,namespace='test');store.initialize(parallel_tools=True)
    ctl=api.Harness(workflow,store=store,run_id='a'*32);queue_batch(replies)
    monkeypatch.setattr(ctl,'_accept',lambda *args:(_ for _ in ()).throw(OSError('after receipt')))
    with pytest.raises(OSError):ctl.run({})
    before=(len(requests),len(seen));assert before==(2,2)
    state=api.Harness(workflow,store=store,run_id='a'*32).resume()
    assert state['status']=='completed' and state['version']==5 and (len(requests),len(seen))==before
    packet=store.load_receipt('a'*32,state['invocations'][0]['id']);assert packet['version']==4
    assert packet['toolContractV1']['evidence']['version']==4


def test_unprepared_store_rejects_parallel_before_provider(parallel_endpoint,tmp_path):
    cfg,requests,replies=parallel_endpoint;workflow=factory(cfg).build(proposal());store=api.FileRunStore(tmp_path,namespace='test');store.initialize(tool_contracts=True)
    with pytest.raises((ValueError,api.StoreIncompatible)):api.Harness(workflow,store=store,run_id='a'*32).run({})
    assert not requests


def test_parallel_workflow_with_pack_and_citations_adopts(parallel_endpoint,tmp_path,monkeypatch):
    import re,json
    import prosaic_runtime as rt
    from support.context_pack_cases import scope_case
    cfg,requests,replies=parallel_endpoint;seen=[];gate=Barrier(2)
    packs=api.ContextPackBindings(specs={'selected':api.ContextPackSpec('selected','1',[api.ContextSlot('task',required=True)],task_source='task')},sources={'task':api.InputSource('/task')},scope=scope_case(),authorizer=api.ContextAuthorizer('packs','1',lambda use:True),agent_defaults={'analyst':'selected'})
    contracts=api.ToolContracts('host','1',evidence_authorizer=rt.EvidenceAuthorizerV1('sources','1',lambda use:True),citations=rt.CitationPolicyV1('required'))
    def read(a,c):seen.append(c.call_index);gate.wait(timeout=2);return {'ok':True}
    workflow=factory(cfg,handler=read,packs=packs,contracts=contracts).build(proposal())
    store=api.FileRunStore(tmp_path,namespace='test');store.initialize(parallel_tools=True);ctl=api.Harness(workflow,store=store,run_id='a'*32)
    queue_batch(replies);replies[-1]=lambda payload:json.dumps({'ok':True,'citation':'[cite:'+re.search(r'ctx_[0-9a-f]{64}',json.dumps(payload)).group()+']'})
    monkeypatch.setattr(ctl,'_accept',lambda *args:(_ for _ in ()).throw(OSError('after receipt')))
    with pytest.raises(OSError):ctl.run({'task':'Review'})
    assert api.Harness(workflow,store=store,run_id='a'*32).resume()['status']=='completed'
    assert len(requests)==2 and len(seen)==2


def test_parallel_cancellation_drains_and_blocks_later_window(parallel_endpoint,tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    cfg,requests,replies=parallel_endpoint;entered=Barrier(3);release=Event();cancel=Event();seen=[]
    def read(a,c):seen.append(c.call_index);entered.wait(timeout=3);assert release.wait(4);return {'ok':True}
    workflow=factory(cfg,handler=read).build(proposal());store=api.FileRunStore(tmp_path,namespace='test');store.initialize(parallel_tools=True)
    ctl=api.Harness(workflow,store=store,run_id='a'*32,cancelled=cancel.is_set);queue_batch(replies,n=3)
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(ctl.run,{})
        try:
            entered.wait(timeout=4);cancel.set();assert not future.done()
        finally:release.set()
        state=future.result(timeout=5)
    assert state['status']=='blocked' and sorted(seen)==[0,1] and len(requests)==1
    packet=store.load_receipt('a'*32,state['invocations'][0]['id'])
    assert len(packet['toolContractV1']['evidence']['toolOutcomes'])==2
