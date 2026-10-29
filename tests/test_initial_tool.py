"""A declared first tool narrows existing authority; it never grants tools."""
from dataclasses import replace
import pytest
from prosaic_harness import Harness, WorkflowAdmissionError
from prosaic_runtime import ProsaicRuntime
from test_workflow_factory import factory, graph, tools, config
from test_transport import endpoint

@pytest.mark.parametrize('value', ['', 'not_granted', 1, None])
def test_first_tool_must_be_a_granted_name(value):
    proposal=graph();proposal['steps']['find']['initial_tool']=value
    with pytest.raises(WorkflowAdmissionError):factory().build(proposal)

def test_first_tool_changes_identity_and_missing_support_fails_closed(tmp_path):
    proposal=graph();proposal['steps']['find']['initial_tool']='lookup_entity'
    workflow=factory().build(proposal)
    assert workflow.fingerprint!=factory().build(graph()).fingerprint
    runtime=ProsaicRuntime(workflow.config,custom_tools=tools())
    runtime.capabilities=runtime.capabilities-{'initial_tool_enforcement_v1'}
    with pytest.raises(ValueError,match='initial_tool'):Harness(workflow,tmp_path/'run',runtime=runtime)
    assert not (tmp_path/'run').exists()

def test_native_first_tool_is_forced_then_released(endpoint,tmp_path):
    url,requests,replies=endpoint
    cfg=config();cfg=replace(cfg,profiles={'local':replace(cfg.profiles['local'],base_url=url)})
    proposal=graph();proposal['steps']['find']['initial_tool']='lookup_entity'
    workflow=factory(cfg=cfg).build(proposal)
    replies.extend([{'role':'assistant','content':None,'tool_calls':[{'id':'call1','type':'function',
        'function':{'name':'lookup_entity','arguments':'{"query":"synthetic"}'}}]},
        {'role':'assistant','content':'{"found":true}'}])
    result=Harness(workflow,tmp_path/'run').run({})
    assert result['status']=='waiting'
    assert requests[0]['tool_choice']=={'type':'function','function':{'name':'lookup_entity'}}
    assert requests[1]['tool_choice']=='auto'
    assert len(result['invocations'])==1


def test_proposal_schema_exposes_only_permitted_first_tool():
    schema=factory().proposal_schema()
    agent=next(s for s in schema['properties']['definition']['properties']['steps']['additionalProperties']['oneOf']
               if s['properties']['kind'].get('const')=='agent')
    assert agent['properties']['initial_tool']['enum']==['lookup_entity']


def test_bounded_recovery_retries_completed_zero_effect_choice_failure(endpoint,tmp_path):
    url,requests,replies=endpoint
    cfg=config();cfg=replace(cfg,profiles={'local':replace(cfg.profiles['local'],base_url=url)})
    proposal=graph();proposal['steps']['find'].update(initial_tool='lookup_entity',max_attempts=2)
    from prosaic_runtime import CustomTool
    effects=[];registry=tools();original=registry['lookup_entity']
    registry['lookup_entity']=CustomTool(original.name,original.description,original.parameters,
        lambda value:effects.append(value) or {'found':True},original.version)
    workflow=factory(cfg=cfg,registry=registry,bounded_tool_recovery=True).build(proposal)
    replies.extend([{'role':'assistant','content':'{"found":true}'},
        {'role':'assistant','content':None,'tool_calls':[{'id':'call1','type':'function',
        'function':{'name':'lookup_entity','arguments':'{"query":"synthetic"}'}}]},
        {'role':'assistant','content':'{"found":true}'}])
    state=Harness(workflow,tmp_path/'run').run({})
    assert state['status']=='waiting'
    assert len(effects)==1 and len(state['invocations'])==2
    assert len(requests)==3
    assert requests[0]['tool_choice']==requests[1]['tool_choice']=={'type':'function','function':{'name':'lookup_entity'}}
    assert 'validation_feedback' in requests[1]['messages'][-1]['content']
    assert 'first native tool' in requests[1]['messages'][-1]['content']
    assert requests[2]['tool_choice']=='auto'


@pytest.mark.parametrize('change', ['timeout','cancelled','unknown_usage','wrong_expected','missing_count',
    'boolean_count','executed','started','wrong_reason','wrong_provider_code'])
def test_first_tool_repair_rejects_uncertain_or_unproven_work(tmp_path,change):
    proposal=graph();proposal['steps']['find']['initial_tool']='lookup_entity'
    harness=Harness(factory(bounded_tool_recovery=True).build(proposal),tmp_path/'run')
    metadata={'failure_reason':'tool_choice_not_honored','provider_error_code':'tool_choice_not_honored',
              'expected_tool':'lookup_entity','tool_call_count':0,'tool_rounds':0}
    result={'exit_code':1,'timed_out':False,'token_usage':12,'metadata':metadata};events=[]
    if change=='timeout':result['timed_out']=True
    if change=='cancelled':result['exit_code']=130
    if change=='unknown_usage':result['token_usage']=None
    if change=='wrong_expected':metadata['expected_tool']='another_tool'
    if change=='missing_count':metadata.pop('tool_call_count')
    if change=='boolean_count':metadata['tool_call_count']=False
    if change=='executed':metadata['tool_call_count']=1
    if change=='started':events=[{'event':'tool_started'}]
    if change=='wrong_reason':metadata['failure_reason']='runtime_failure'
    if change=='wrong_provider_code':metadata['provider_error_code']='timeout'
    assert harness._first_tool_recovery(proposal['steps']['find'],result,events) is None


@pytest.mark.parametrize('enabled,attempts,calls,reason',[(False,2,1,'tool_choice_not_honored'),
    (True,1,1,'attempt_limit'),(True,2,2,'attempt_limit')])
def test_first_tool_repair_is_opt_in_and_bounded(endpoint,tmp_path,enabled,attempts,calls,reason):
    url,requests,replies=endpoint
    cfg=config();cfg=replace(cfg,profiles={'local':replace(cfg.profiles['local'],base_url=url)})
    proposal=graph();proposal['steps']['find'].update(initial_tool='lookup_entity',max_attempts=attempts)
    workflow=factory(cfg=cfg,bounded_tool_recovery=enabled).build(proposal)
    replies.extend([{'role':'assistant','content':'{"found":true}'}]*2)
    state=Harness(workflow,tmp_path/'run').run({})
    assert state['status']=='blocked' and state['reason']==reason
    assert len(requests)==calls and len(state['invocations'])==calls
