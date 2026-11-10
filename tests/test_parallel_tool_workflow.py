from dataclasses import replace
import pytest
import prosaic_harness as api
import prosaic_runtime as rt
from test_workflow_rules_execution import rule_endpoint


def factory(cfg,*,host=True,parallel=True,contracts=True,version='1',handler=None,packs=None):
    schema={'type':'object','properties':{'ok':{'type':'boolean'},'citation':{'type':'string'}},'required':['ok'],'additionalProperties':False}
    tool=rt.CustomTool('lookup','Read',{'type':'object','additionalProperties':False},handler or (lambda a,c:{'ok':True}),version,with_context=True,parallel_read=parallel,max_result_bytes=8192)
    agent=rt.ProsaicArtifact('approved','subagent',{'name':'analyst','description':'Read','tools':['lookup']},'Return JSON with ok.')
    options=dict(allowed_agents={'analyst'},allowed_schemas={'result'},allowed_tools={'lookup'},max_provider_requests_per_invocation=3,max_tool_calls_per_invocation=4,max_receipt_bytes=8388608,max_state_bytes=8388608,max_json_nodes=262144)
    if host:options['parallel_tools']=rt.ParallelToolPolicyV1(max_concurrency=4)
    return api.WorkflowFactory(catalog=api.WorkflowCatalog(agents={'analyst':agent},schemas={'result':schema}),bindings=api.WorkflowBindings(config=replace(cfg,allowed_tools=frozenset({'lookup'})),custom_tools={'lookup':tool},context_packs=packs,tool_contracts=api.ToolContracts('host','1') if contracts is True else contracts if contracts else None),policy=api.WorkflowPolicy(**options))


def proposal(request=2):
    node=dict(kind='agent',agent='analyst',schema='result',tools=['lookup'],next='done')
    if request is not None:node['parallel_tools']={'max_concurrency':request}
    return {'version':1,'start':'review','steps':{'review':node,'done':{'kind':'finish','requires':['review']}}}


def test_host_ceiling_node_narrowing_and_default_omission(rule_endpoint):
    from prosaic_harness.parallel_tools import parallel_material,parallel_policy
    cfg,_,_=rule_endpoint
    wf=factory(cfg).build(proposal())
    assert parallel_policy(wf,'review').max_concurrency==2 and parallel_policy(wf,'done') is None
    assert parallel_material(wf)['parallelToolsV1']['host']['maxConcurrency']==4
    assert parallel_material(factory(cfg,host=False).build(proposal(None)))=={}
    assert parallel_policy(factory(cfg).build(proposal(None)),'review') is None
    assert wf.fingerprint!=factory(cfg).build(proposal(1)).fingerprint
    assert wf.fingerprint!=factory(cfg,version='2').build(proposal()).fingerprint


@pytest.mark.parametrize('host,selection,contracts',[(False,2,True),(True,5,True),(True,True,True),(True,2,False)])
def test_parallel_proposal_requires_explicit_host_authority(rule_endpoint,host,selection,contracts):
    cfg,_,_=rule_endpoint
    with pytest.raises(ValueError):factory(cfg,host=host,contracts=contracts).build(proposal(selection))


def test_nonagent_cannot_request_parallel_tools(rule_endpoint):
    cfg,_,_=rule_endpoint;p=proposal(None);p['steps']['done']['parallel_tools']={'max_concurrency':2}
    with pytest.raises(ValueError):factory(cfg).build(p)


def test_discovery_schema_and_json_follow_same_admission(rule_endpoint):
    import json
    from jsonschema import validate
    cfg,_,_=rule_endpoint;f=factory(cfg)
    validate({'definition':proposal()},f.proposal_schema())
    assert f.build_json(json.dumps({'definition':proposal()})).fingerprint==f.build(proposal()).fingerprint
