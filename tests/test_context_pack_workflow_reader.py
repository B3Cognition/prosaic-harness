import json
from dataclasses import replace
from prosaic_harness import (ContextPackReader,ContextPackBindings,ContextAuthorizer,ContextPackSpec,ContextSlot,
    InputSource,ContextPacker,WorkflowFactory,WorkflowBindings,WorkflowCatalog,WorkflowPolicy)
import prosaic_runtime as api
from support.context_pack_cases import scope_case
from test_workflow_rules_execution import rule_endpoint
from test_context_pack_workflow import controller
from prosaic_harness.context_packs.sources import capture_sources


def test_workflow_activates_reader_only_for_the_durable_selected_pack(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint;cfg=replace(cfg,allowed_tools=frozenset({'read_context_item'}))
    reader=ContextPackReader();tool=reader.as_tool()
    spec=ContextPackSpec('work','1',[ContextSlot('task',required=True),ContextSlot('facts',availability='discoverable')],task_source='task')
    bindings=ContextPackBindings(specs={'work':spec},sources={'task':InputSource('/task'),'facts':InputSource('/facts')},
        scope=scope_case(),authorizer=ContextAuthorizer('access','1',lambda use:True),agent_defaults={'worker':'work'})
    artifact=api.ProsaicArtifact('worker','subagent',{'name':'worker','description':'Reader fixture','tools':['read_context_item']},
        'ALWAYS use captured context and return JSON. NEVER invent facts.')
    factory=WorkflowFactory(catalog=WorkflowCatalog(agents={'worker':artifact},schemas={'result':{'type':'object'}}),
        bindings=WorkflowBindings(config=cfg,custom_tools={'read_context_item':tool},context_packs=bindings),
        policy=WorkflowPolicy(allowed_agents={'worker'},allowed_schemas={'result'},allowed_tools={'read_context_item'},
            max_provider_requests_per_invocation=3,max_tool_calls_per_invocation=2))
    workflow=factory.build({'version':1,'start':'build','steps':{'build':{'kind':'agent','agent':'worker',
        'schema':'result','tools':['read_context_item'],'require_tools':['read_context_item'],'next':'done'},'done':{'kind':'finish'}}})
    inputs={'task':'Review','facts':'DISCOVERED-719'}
    candidates=ContextPacker().compose(spec,capture_sources(spec,
        {'request':inputs,'artifacts':{},'artifact_bindings':{},'sources':{},'validation_feedback':None},{},bindings))
    citation=candidates.variants[0]['index'][0]['citationId']
    replies.extend([{'name':'read_context_item','input':{'citationId':citation}},'{"ok":true}'])
    harness=controller(workflow,tmp_path)
    state=harness.run(inputs)
    assert state['status']=='completed' and reader.active_count==0
    assert 'DISCOVERED-719' not in json.dumps(requests[0]) and 'DISCOVERED-719' in json.dumps(requests[1])
    receipt=harness.store.load_receipt(state['run_id'],state['invocations'][0]['id'])
    assert receipt['contextPackResult']['evidence']['toolAttempts']==1
    assert any(e['disclosure']=='read' for e in receipt['contextPack']['exposureBindings']['entries'])
    reserved=state['contextPacks']['reservations'][receipt['id']]
    assert reserved['toolResultBytes']==[24576,24576]
