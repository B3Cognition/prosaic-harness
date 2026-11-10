from dataclasses import replace
import json
import pytest
import prosaic_runtime as runtime_api
from prosaic_harness.tool_contract_views import (VerifiedToolReceipt, ToolContractViewBindings,
    resolve_citation_view, project_retained_tool_event)
from test_workflow_rules_execution import rule_endpoint
from test_tool_contract_workflow import flow, controller, queue_answer


def receipt_case(cfg,replies,tmp_path,*,pack=False):
    workflow=flow(cfg,pack=pack)
    queue_answer(replies,pack=pack)
    harness=controller(workflow,tmp_path)
    state=harness.run({'task':'Review','private':'PRIVATE-FACT'})
    receipt=harness.store.load_receipt(state['run_id'],state['invocations'][0]['id'])
    verified=VerifiedToolReceipt.from_workflow_store(harness.store,state['run_id'],receipt['id'],workflow=workflow)
    evidence_id=receipt['toolContractV1']['citations']['markers'][0]['evidenceId']
    scope=runtime_api.InvocationScope(**receipt['toolContractV1']['scope'])
    bindings=ToolContractViewBindings(scope,evidence_authorizer=runtime_api.EvidenceAuthorizerV1('viewer','1',lambda use:True),
        display_authorizer=runtime_api.ToolDisplayAuthorizerV1('display','1',lambda use:True),context_packs=getattr(workflow,'_context_packs',None))
    return workflow,receipt,verified,evidence_id,bindings


@pytest.mark.parametrize('pack',[False,True])
def test_view_returns_only_exact_captured_selection(rule_endpoint,tmp_path,pack):
    cfg,requests,replies=rule_endpoint
    workflow,receipt,verified,evidence_id,bindings=receipt_case(cfg,replies,tmp_path,pack=pack)
    view=resolve_citation_view(verified,evidence_id,bindings)
    assert view['available'] is True and view['content']==('Review' if pack else 14)
    assert 'PRIVATE-LOCATOR' not in json.dumps(view) and 'PRIVATE-FACT' not in json.dumps(view)
    assert len(requests)==2


def test_view_revocation_does_not_rewrite_accepted_answer(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint
    _,receipt,verified,evidence_id,bindings=receipt_case(cfg,replies,tmp_path)
    answer=receipt['result']['stdout']
    denied=replace(bindings,evidence_authorizer=runtime_api.EvidenceAuthorizerV1('viewer','2',lambda use:False))
    assert resolve_citation_view(verified,evidence_id,denied)==dict(version=1,available=False,evidenceId=evidence_id)
    assert receipt['result']['stdout']==answer and len(requests)==2
    with pytest.raises(ValueError): resolve_citation_view(receipt,evidence_id,bindings)


def test_cross_scope_and_unknown_source_are_unavailable(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint
    _,_,verified,evidence_id,bindings=receipt_case(cfg,replies,tmp_path)
    foreign=replace(bindings,scope=replace(bindings.scope,run_id='other'))
    assert resolve_citation_view(verified,evidence_id,foreign)['available'] is False
    assert resolve_citation_view(verified,'ev_'+'0'*64,bindings)['available'] is False


def test_retained_event_needs_current_display_grant(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint
    workflow,receipt,verified,_,bindings=receipt_case(cfg,replies,tmp_path)
    index=next(i for i,event in enumerate(receipt['events']) if event.get('toolEventV1',{}).get('phase')=='completed')
    shown=project_retained_tool_event(verified,index,bindings,workflow.custom_tools)
    assert shown['event']['toolEventV1']['display']=={'count':14}
    denied=replace(bindings,display_authorizer=runtime_api.ToolDisplayAuthorizerV1('display','2',lambda use:False))
    hidden=project_retained_tool_event(verified,index,denied,workflow.custom_tools)
    assert 'display' not in hidden['event']['toolEventV1'] and len(requests)==2
