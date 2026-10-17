"""Only authoritative pre-dispatch failures permit another bounded attempt."""
import json
import pytest
from prosaic_harness import Harness,WorkflowPolicy
from prosaic_runtime import ProsaicRuntime,Result,ToolOutcome
from test_workflow_factory import factory,graph,tools

def bound(tmp_path,monkeypatch,events,proposal=None,**caps):
    workflow=factory(bounded_tool_recovery=True,**caps).build(proposal or graph())
    runtime=ProsaicRuntime(workflow.config,custom_tools=caps.get('registry',tools()));calls=[]
    def run(artifact,arguments,**options):
        calls.append((json.loads(arguments),options['policy']))
        assert options['policy'].bounded_tool_recovery is True
        for event in events if len(calls)==1 else [completion('ok')]:options['on_event'](event)
        return Result(0,'{"found":true}','',token_usage=3)
    monkeypatch.setattr(runtime,'run',run)
    return Harness(workflow,tmp_path/'run',runtime=runtime),calls

def completion(code,**changes):
    return dict(event='tool_completed',name='lookup_entity',tool_version='v1',call_id='call1',
        status='ok' if code=='ok' else 'error',tool_outcome=ToolOutcome(code).to_dict())|changes

def test_default_identity_and_strict_boolean():
    assert 'bounded_tool_recovery' not in WorkflowPolicy()._identity()
    assert WorkflowPolicy(bounded_tool_recovery=True)._identity()['bounded_tool_recovery'] is True
    for value in [None,1,'true']:
        with pytest.raises(ValueError):WorkflowPolicy(bounded_tool_recovery=value)

@pytest.mark.parametrize('events',[[],[completion('invalid_arguments')]])
def test_safe_correction_uses_existing_attempt_only(tmp_path,monkeypatch,events):
    h,calls=bound(tmp_path,monkeypatch,events)
    assert h.run({})['status']=='waiting' and len(calls)==2
    assert 'toolRecovery' in json.dumps(calls[1][0])
    assert len(h.status().state['invocations'])==2

@pytest.mark.parametrize('event',[
    completion('handler_error'),completion('controlled_failure'),completion('authorization_denied'),
    completion('invalid_arguments',tool_version='foreign'),
    completion('invalid_arguments',tool_outcome=None),
    completion('invalid_arguments',tool_outcome={'recovery':'correct_arguments','private':'SECRET'}),
    completion('unclassified'),
    dict(event='tool_started',name='lookup_entity',tool_version='v1',call_id='call1')])
def test_uncertain_missing_or_foreign_evidence_cannot_retry(tmp_path,monkeypatch,event):
    h,calls=bound(tmp_path,monkeypatch,[event])
    state=h.run({})
    assert state['reason']=='tool_recovery_blocked' and len(calls)==1
    assert h.resume()['reason']=='tool_recovery_blocked' and len(calls)==1
    assert 'SECRET' not in (state.get('feedback') or '')

def test_completed_correction_does_not_repeat_required_tool(tmp_path,monkeypatch):
    h,calls=bound(tmp_path,monkeypatch,[completion('invalid_arguments'),completion('ok',call_id='call2')])
    assert h.run({})['status']=='waiting' and len(calls)==1

def test_existing_attempt_limit_is_not_raised(tmp_path,monkeypatch):
    proposal=graph();proposal['steps']['find']['max_attempts']=1
    workflow=factory(bounded_tool_recovery=True).build(proposal)
    runtime=ProsaicRuntime(workflow.config,custom_tools=tools());calls=[]
    def run(*args,**kw):
        calls.append(1);kw['on_event'](completion('invalid_arguments'))
        return Result(0,'{"found":true}','',token_usage=3)
    monkeypatch.setattr(runtime,'run',run)
    h=Harness(workflow,tmp_path/'run',runtime=runtime)
    assert h.run({})['reason']=='attempt_limit' and calls==[1]

def test_capabilities_are_required_before_execution(tmp_path):
    workflow=factory(bounded_tool_recovery=True).build(graph())
    runtime=ProsaicRuntime(workflow.config,custom_tools=tools())
    runtime.capabilities=runtime.capabilities-{'tool_outcomes_v1'}
    with pytest.raises(ValueError):Harness(workflow,tmp_path/'run',runtime=runtime)
    assert not (tmp_path/'run').exists()

@pytest.mark.parametrize('result,reason',[(Result(130,'','',token_usage=1),'cancelled'),
    (Result(1,'','',timed_out=True,token_usage=1),'runtime_timeout'),
    (Result(1,'','',token_usage=1,metadata={'failure_reason':'tool_call_limit'}),'runtime_failure')])
def test_runtime_terminal_failure_keeps_precedence_without_retry(tmp_path,monkeypatch,result,reason):
    h,calls=bound(tmp_path,monkeypatch,[])
    def run(*args,**kw):
        calls.append(1)
        kw['on_event'](dict(event='tool_started',name='lookup_entity',call_id='call1'))
        return result
    monkeypatch.setattr(h.runtime,'run',run)
    assert h.run({})['reason']==reason and calls==[1]

@pytest.mark.parametrize('start,completed',[
    (dict(name='other_entity',tool_version='v1',call_id='call1'),completion('invalid_arguments')),
    (dict(name={},tool_version='v1',call_id='call1'),completion('invalid_arguments')),
    (dict(name='lookup_entity',tool_version='v1',call_id=[]),completion('invalid_arguments')),
    (dict(name='lookup_entity',tool_version='foreign',call_id='call1'),completion('invalid_arguments')),
    (dict(name='lookup_entity',tool_version='v1',call_id='call1'),completion('invalid_arguments',name={})),
    (dict(name='lookup_entity',tool_version='v1',call_id='call1',turn=1),completion('invalid_arguments',turn=2)),
])
def test_malformed_or_contradictory_call_identity_blocks_durably(tmp_path,monkeypatch,start,completed):
    from dataclasses import replace
    from test_workflow_factory import agent,config
    from prosaic_runtime import CustomTool
    registry=tools();base=registry['lookup_entity']
    registry['other_entity']=CustomTool('other_entity','Other lookup',base.parameters,base.handler,'v1')
    grants={'lookup_entity','other_entity'}
    proposal=graph();proposal['steps']['find']['tools']=sorted(grants)
    h,calls=bound(tmp_path,monkeypatch,[dict(event='tool_started',**start),completed],
        proposal=proposal,registry=registry,assets={'finder':agent(tools=tuple(grants))},allowed_tools=grants,
        cfg=replace(config(),allowed_tools=frozenset(grants)))
    state=h.run({})
    assert state['reason']=='tool_recovery_blocked' and len(calls)==1
    assert h.status().state['reason']=='tool_recovery_blocked'
    assert h.resume()['reason']=='tool_recovery_blocked' and len(calls)==1

def test_builtin_success_and_reused_provider_ids_in_separate_turns_are_valid():
    from types import SimpleNamespace
    from prosaic_harness.engine import Harness
    h=SimpleNamespace(workflow=SimpleNamespace(tool_descriptors={}))
    events=[]
    for turn in (1,2):
        identity=dict(name='list_files',call_id='provider-local-id',turn=turn)
        events.extend([dict(event='tool_started',**identity),dict(event='tool_completed',**identity,
            status='ok',tool_outcome=ToolOutcome('ok').to_dict())])
    assert Harness._tool_recovery(h,events,{'list_files'})==''
