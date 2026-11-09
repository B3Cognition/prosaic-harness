import pytest
from prosaic_harness import Harness
from test_workflow_rules_execution import rule_endpoint
from test_context_pack_workflow import markdown_flow,controller


def test_saved_pack_receipt_is_adopted_without_source_composition_or_guard_execution(rule_endpoint,tmp_path,monkeypatch):
    from prosaic_harness import ContextPacker
    cfg,requests,replies=rule_endpoint;replies.extend(['{"ok":true}','{"ok":true}'])
    workflow,guards=markdown_flow(tmp_path,cfg,guarded=True)
    harness=controller(workflow,tmp_path)
    monkeypatch.setattr(harness,'_accept',lambda *a:(_ for _ in ()).throw(OSError('crash after receipt')))
    with pytest.raises(OSError): harness.run({'task':'work','private':'UNRELATED-BUSINESS-419'})
    assert len(requests)==1 and len(guards)==1
    # Recovery may compose the next node, so fail only for a recapture of build.
    original=ContextPacker.compose
    def compose(self,spec,snapshot,*args,**kwargs):
        assert spec.spec_identity!='implementation'
        return original(self,spec,snapshot,*args,**kwargs)
    monkeypatch.setattr(ContextPacker,'compose',compose)
    resumed=Harness(workflow,store=harness.store,run_id='a'*32).resume()
    assert resumed['status']=='completed' and len(requests)==2 and len(guards)==2


def test_durable_pre_dispatch_attempt_restores_without_recomposition(rule_endpoint,tmp_path,monkeypatch):
    from prosaic_harness import ContextPacker
    cfg,requests,replies=rule_endpoint;replies.extend(['{"ok":true}','{"ok":true}'])
    workflow,guards=markdown_flow(tmp_path,cfg,guarded=True)
    harness=controller(workflow,tmp_path);save=harness.store.save_run
    def interrupted(run_id,state,revision,lease):
        result=save(run_id,state,revision,lease)
        if state['pending'] is not None:
            frame=state['contextPacks']['attempts'][state['pending']['id']]
            if frame['stage']=='prepared': raise OSError('crash after frozen pending save')
        return result
    monkeypatch.setattr(harness.store,'save_run',interrupted)
    with pytest.raises(OSError): harness.run({'task':'work','private':'UNRELATED-BUSINESS-419'})
    assert requests==[] and guards==[]
    monkeypatch.setattr(harness.store,'save_run',save)
    original=ContextPacker.compose
    def compose(self,spec,snapshot,*args,**kwargs):
        assert spec.spec_identity!='implementation'
        return original(self,spec,snapshot,*args,**kwargs)
    monkeypatch.setattr(ContextPacker,'compose',compose)
    restored=Harness(workflow,store=harness.store,run_id='a'*32).resume()
    assert restored['status']=='completed' and len(requests)==2 and len(guards)==2


def test_acknowledged_unknown_retry_uses_same_frozen_selection_in_new_epoch(rule_endpoint,tmp_path,monkeypatch):
    from prosaic_harness import ContextPacker
    cfg,requests,replies=rule_endpoint;replies.extend(['{"ok":true}']*3)
    workflow,guards=markdown_flow(tmp_path,cfg,guarded=True)
    harness=controller(workflow,tmp_path);save=harness.store.save_receipt
    monkeypatch.setattr(harness.store,'save_receipt',lambda *a:(_ for _ in ()).throw(OSError('lost receipt before save')))
    with pytest.raises(OSError): harness.run({'task':'work','private':'UNRELATED-BUSINESS-419'})
    monkeypatch.setattr(harness.store,'save_receipt',save)
    fresh=Harness(workflow,store=harness.store,run_id='a'*32)
    pending=fresh.resume()
    assert pending['reason']=='interrupted_call' and len(requests)==1
    old=pending['contextPacks']['attempts'][pending['pending']['id']]
    compose=ContextPacker.compose
    def no_recapture(self,spec,snapshot,*args,**kwargs):
        assert spec.spec_identity!='implementation'
        return compose(self,spec,snapshot,*args,**kwargs)
    monkeypatch.setattr(ContextPacker,'compose',no_recapture)
    state=fresh.resume(retry_interrupted=True,expected_revision=fresh.status().revision)
    assert state['status']=='completed' and len(requests)==3 and len(guards)==3
    assert state['contextPacks']['attempts'][old['invocationId']]['stage']=='abandoned'
    second=state['contextPacks']['attempts'][state['invocations'][1]['id']]
    assert second['executionEpoch']==old['executionEpoch']+1
    assert second['selectedPackReference']==old['selectedPackReference']
    assert second['frozenInput']['contextIdentity']==old['frozenInput']['contextIdentity']
