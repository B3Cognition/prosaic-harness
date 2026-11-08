import json
import pytest
import prosaic_runtime as api
from prosaic_harness import (ContextPackBindings,ContextAuthorizer,ContextPackSpec,ContextSlot,InputSource,
    WorkflowFactory,WorkflowBindings,WorkflowCatalog,WorkflowPolicy)
from support.context_pack_cases import scope_case
from support.context_counter import fixture_context
from test_workflow_rules_execution import rule_endpoint
from test_context_pack_workflow import controller


@pytest.mark.parametrize('fits',[True,False])
def test_workflow_variants_share_one_budget_and_checkpoint_execution_work(rule_endpoint,tmp_path,fits):
    cfg,requests,replies=rule_endpoint;replies.append('{"ok":true}')
    spec=ContextPackSpec('work','1',[ContextSlot('task',required=True),ContextSlot('optional')],task_source='task')
    bindings=ContextPackBindings(specs={'work':spec},sources={'task':InputSource('/task'),'optional':InputSource('/optional')},
        scope=scope_case(),authorizer=ContextAuthorizer('access','1',lambda use:True),agent_defaults={'worker':'work'})
    artifact=api.ProsaicArtifact('worker','subagent',{'name':'worker','description':'Counted fixture'},'ALWAYS return JSON. NEVER invent evidence.')
    factory=WorkflowFactory(catalog=WorkflowCatalog(agents={'worker':artifact},schemas={'result':{'type':'object'}}),
        bindings=WorkflowBindings(config=cfg,context_packs=bindings),
        policy=WorkflowPolicy(allowed_agents={'worker'},allowed_schemas={'result'},max_provider_requests_per_invocation=1,max_tool_calls_per_invocation=0))
    workflow=factory.build({'version':1,'start':'build','steps':{'build':{'kind':'agent','agent':'worker','schema':'result','next':'done'},'done':{'kind':'finish'}}})
    calls=[]
    def count(request):
        calls.append(request)
        return 10 if fits or 'OPTIONAL-719' not in json.dumps(request) else 5000
    policy,counters=fixture_context(cfg.profiles['local'].provider,count=count)
    harness=controller(workflow,tmp_path,context_policy=policy,token_counters=counters)
    state=harness.run({'task':'work','optional':'OPTIONAL-719'})
    assert state['status']=='completed' and len(requests)==1
    frame=state['contextPacks']['attempts'][state['invocations'][0]['id']]
    assert frame['selectedPackReference']['selectedVariantIndex']==(0 if fits else 1)
    assert ('OPTIONAL-719' in json.dumps(requests[0]))==fits
    assert frame['contextWork']['candidateChecks']>frame['frozenInput']['initialContextWork']['candidateChecks']
    assert frame['contextWork']['checkpointSequence']>=2 and len(calls)>=3
