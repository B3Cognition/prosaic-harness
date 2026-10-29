"""Direct tool calls require separate host permission and durable admission."""
import pytest
from prosaic_harness import Harness, WorkflowAdmissionError
from test_workflow_factory import factory, graph
from test_transport import endpoint


def direct():
    value = graph()
    value['steps']['find'] = {'kind': 'tool', 'tool': 'lookup_entity',
        'arguments': {'query': 'literal'}, 'schema': 'result', 'next': 'review'}
    return value


def test_direct_permission_is_explicit():
    with pytest.raises(WorkflowAdmissionError):
        factory().build(direct())
    workflow = factory(allowed_direct_tools={'lookup_entity'}).build(direct())
    assert workflow.tool_descriptors['lookup_entity']['version'] == 'v1'


def test_direct_executes_actual_callback_without_provider(tmp_path, monkeypatch):
    import json
    from prosaic_runtime import ProsaicRuntime
    workflow = factory(allowed_direct_tools={'lookup_entity'}).build(direct())
    runtime = ProsaicRuntime(workflow.config, custom_tools=workflow.custom_tools)
    monkeypatch.setattr(runtime, 'run', lambda *a, **k: pytest.fail('model invocation'))
    state = Harness(workflow, tmp_path/'run', runtime=runtime).run({})
    receipt = json.loads(next((tmp_path/'run/attempts').glob('*.json')).read_text())
    assert receipt['result']['cost_usd'] == 0
    assert receipt['result']['metadata']['direct_tool_v1'] == {'model_free': True, 'provider_requests': 0}
    completed = [event for event in receipt['events'] if event['event'] == 'tool_completed']
    assert len(completed) == 1 and completed[0]['tool_version'] == 'v1'
    assert state['status'] == 'waiting'
    assert state['outputs']['find'] == {'found': True}
    assert state['calls'] == 1 and state['invocations'][0]['token_usage'] == 0


def registered(handler, *, version='v1', parameters=None, authorize=None):
    from prosaic_runtime import CustomTool
    from test_workflow_factory import tools
    original = tools()['lookup_entity']
    return {'lookup_entity': CustomTool(original.name, original.description,
        parameters or original.parameters, handler, version, authorize=authorize)}


def admitted(handler=lambda args: {'found': True}, **options):
    return factory(allowed_direct_tools={'lookup_entity'}, registry=registered(handler), **options).build(direct())


@pytest.mark.parametrize('change', ['argument', 'permission', 'descriptor', 'schema'])
def test_mutation_is_rejected_before_effects(tmp_path, change):
    from prosaic_runtime import ProsaicRuntime
    effects=[]
    workflow=admitted(lambda args: effects.append(args) or {'found': True})
    runtime=ProsaicRuntime(workflow.config, custom_tools=workflow.custom_tools)
    if change=='argument': workflow.definition['steps']['find']['arguments']['query']='changed'
    elif change=='permission': workflow.allowed_direct_tools=frozenset()
    elif change=='schema': workflow.schemas['find']['required']=[]
    else: runtime=ProsaicRuntime(workflow.config, custom_tools=registered(lambda args: effects.append(args),version='v2'))
    with pytest.raises(ValueError): Harness(workflow,tmp_path/'run',runtime=runtime)
    assert effects==[] and not (tmp_path/'run').exists()


@pytest.mark.parametrize('arguments', [None, [], 'query', 1])
def test_only_literal_object_arguments_are_admitted(arguments):
    proposal=direct();proposal['steps']['find']['arguments']=arguments
    with pytest.raises(WorkflowAdmissionError): factory(allowed_direct_tools={'lookup_entity'}).build(proposal)


@pytest.mark.parametrize('key', ['handler','endpoint','eval','template','max_attempts','tools','allowed_direct_tools'])
def test_proposal_cannot_supply_execution_or_permission_fields(key):
    proposal=direct();proposal['steps']['find'][key]='forbidden'
    with pytest.raises(WorkflowAdmissionError): factory(allowed_direct_tools={'lookup_entity'}).build(proposal)


def test_policy_direct_permission_must_be_subset():
    with pytest.raises(WorkflowAdmissionError): factory(allowed_direct_tools={'ungranted'})


@pytest.mark.parametrize('output', [{'found':'invalid'}, {'other':True}])
def test_schema_failure_is_single_attempt_and_resume_does_not_retry(tmp_path, output):
    effects=[]
    h=Harness(admitted(lambda args: effects.append(args) or output),tmp_path/'run')
    state=h.run({})
    assert state['reason']=='attempt_limit' and state['calls']==1 and len(effects)==1
    assert h.resume()['reason']=='attempt_limit' and len(effects)==1
    assert state['outputs']=={}


def test_validator_failure_never_retries_callback(tmp_path):
    from prosaic_harness import WorkflowCatalog, WorkflowBindings, WorkflowPolicy, WorkflowFactory, Validator
    from test_workflow_factory import config
    effects=[];proposal=direct();proposal['steps']['find']['validators']=['reject']
    f=WorkflowFactory(catalog=WorkflowCatalog(schemas={'result':{'type':'object'}}),
        bindings=WorkflowBindings(config=config(),custom_tools=registered(lambda args: effects.append(args) or {'found':True}),
            validators={'reject':Validator('v1',lambda output,context:['host rejected output'])}),
        policy=WorkflowPolicy(allowed_tools={'lookup_entity'},allowed_direct_tools={'lookup_entity'},
            allowed_schemas={'result'},allowed_validators={'reject'}))
    h=Harness(f.build(proposal),tmp_path/'run');state=h.run({})
    assert state['reason']=='attempt_limit' and len(effects)==1
    assert h.resume()['reason']=='attempt_limit' and len(effects)==1


def test_receipt_recovery_does_not_repeat_callback(tmp_path,monkeypatch):
    effects=[];h=Harness(admitted(lambda args: effects.append(args) or {'found':True}),tmp_path/'run')
    accept=h._accept
    monkeypatch.setattr(h,'_accept',lambda *a: (_ for _ in ()).throw(OSError('after receipt')))
    with pytest.raises(OSError):h.run({})
    monkeypatch.setattr(h,'_accept',accept)
    assert h.resume()['status']=='waiting' and len(effects)==1
    assert h.interaction(review_outputs=['find']).review_outputs=={'find':{'found':True}}


def test_missing_receipt_stays_fenced_even_with_retry_flag(tmp_path,monkeypatch):
    effects=[];h=Harness(admitted(lambda args: effects.append(args) or {'found':True}),tmp_path/'run')
    monkeypatch.setattr(h.store,'save_receipt',lambda *a: (_ for _ in ()).throw(OSError('before receipt')))
    with pytest.raises(OSError):h.run({})
    assert h.resume()['reason']=='interrupted_call'
    assert h.resume(retry_interrupted=True)['reason']=='interrupted_call'
    assert len(effects)==1 and h.status().state['pending'] is not None


@pytest.mark.parametrize('when', ['before','during'])
def test_cancellation_stops_advancement(tmp_path,when):
    effects=[];cancel=[when=='before']
    def callback(args):
        effects.append(args);cancel[0]=True;return {'found':True}
    h=Harness(admitted(callback),tmp_path/'run',cancelled=lambda:cancel[0])
    assert h.run({})['reason']=='cancelled'
    assert len(effects)==(0 if when=='before' else 1)
    assert h.status().state['outputs']=={}


def test_lease_loss_keeps_pending_and_fences_replay(tmp_path):
    from prosaic_harness import LeaseLost
    effects=[];holder={}
    def callback(args):
        effects.append(args);holder['h']._lease.active=False;return {'found':True}
    h=holder['h']=Harness(admitted(callback),tmp_path/'run')
    with pytest.raises(LeaseLost):h.run({})
    assert h.status().state['pending'] is not None
    assert h.resume()['reason']=='interrupted_call' and len(effects)==1


def test_direct_identity_includes_arguments_permission_contract_and_preserves_empty_policy():
    ordinary=factory().build(graph())
    assert 'allowed_direct_tools' not in factory()._policy._identity()
    extra=factory(allowed_direct_tools={'lookup_entity'}).build(graph())
    assert ordinary.fingerprint!=extra.fingerprint
    base=factory(allowed_direct_tools={'lookup_entity'}).build(direct())
    changed=direct();changed['steps']['find']['arguments']['query']='different'
    assert base.fingerprint!=factory(allowed_direct_tools={'lookup_entity'}).build(changed).fingerprint
    assert base.fingerprint!=factory(allowed_direct_tools={'lookup_entity'},registry=registered(lambda args:{'found':True},version='v2')).build(direct()).fingerprint


def test_discovery_projects_direct_permission_without_granting_it():
    from jsonschema import Draft202012Validator
    f=factory(allowed_direct_tools={'lookup_entity'})
    assert f.describe()['allowedDirectTools']==['lookup_entity']
    assert 'tool' in f.describe()['stepKinds']
    Draft202012Validator(f.proposal_schema()).validate({'definition':direct()})
    assert factory().describe()['allowedDirectTools']==[]
    assert not Draft202012Validator(factory().proposal_schema()).is_valid({'definition':direct()})


def test_unsupported_adapter_is_rejected_before_storage(tmp_path):
    from prosaic_runtime import ProsaicRuntime
    workflow=admitted();runtime=ProsaicRuntime(workflow.config,custom_tools=workflow.custom_tools)
    runtime.capabilities=runtime.capabilities-{'direct_tool_v1'}
    with pytest.raises(ValueError):Harness(workflow,tmp_path/'run',runtime=runtime)
    assert not (tmp_path/'run').exists()


def yaml_direct(tmp_path):
    import json,yaml
    (tmp_path/'runtime.yml').write_text(yaml.safe_dump({'default_profile':'local',
        'allowed_tools':['lookup_entity'],'profiles':{'local':{'base_url':'http://localhost:9/v1','model':'unused'}}}))
    (tmp_path/'result.json').write_text(json.dumps({'type':'object','required':['found'],
        'properties':{'found':{'type':'boolean'}},'additionalProperties':False}))
    proposal=direct();proposal['runtime']='runtime.yml';proposal['steps']['find']['schema']='result.json'
    path=tmp_path/'flow.yml';path.write_text(yaml.safe_dump(proposal));return path


def test_yaml_uses_same_permission_and_actual_execution(tmp_path):
    from prosaic_harness import Workflow
    effects=[];path=yaml_direct(tmp_path);registry=registered(lambda args:effects.append(args) or {'found':True})
    with pytest.raises(ValueError):Workflow.load(path,custom_tools=registry)
    w=Workflow.load(path,custom_tools=registry,allowed_direct_tools={'lookup_entity'})
    assert w.current_fingerprint()==w.fingerprint
    assert Harness(w,tmp_path/'run').run({})['status']=='waiting'
    assert effects==[{'query':'literal'}]
    w.allowed_direct_tools=frozenset()
    with pytest.raises(ValueError):Harness(w,tmp_path/'changed')


def test_tool_outputs_feed_gate_dependencies_and_finish(tmp_path):
    effects=[];proposal=direct()
    proposal['steps']['find']['next']='gate'
    proposal['steps']['gate']={'kind':'gate','from':'find','field':['found'],'equals':True,'pass':'second','fail':'rejected'}
    proposal['steps']['second']={'kind':'tool','tool':'lookup_entity','arguments':{'query':'second'},
        'schema':'result','inputs':['find'],'next':'review'}
    proposal['steps']['review']['requires']=['find','second']
    workflow=factory(allowed_direct_tools={'lookup_entity'},registry=registered(lambda a:effects.append(a) or {'found':True})).build(proposal)
    h=Harness(workflow,tmp_path/'run');state=h.run({})
    assert state['status']=='waiting' and state['calls']==2 and len(effects)==2
    assert state['bindings']['second']['dependencies']['find']==state['bindings']['find']
    assert h.resume(choice='accept')['status']=='completed'


def test_call_budget_counts_direct_invocations(tmp_path):
    effects=[];proposal=direct();proposal['limits']={'max_calls':1}
    proposal['steps']['find']['next']='second'
    proposal['steps']['second']={'kind':'tool','tool':'lookup_entity','arguments':{'query':'second'},'schema':'result','next':'review'}
    workflow=factory(allowed_direct_tools={'lookup_entity'},registry=registered(lambda a:effects.append(a) or {'found':True})).build(proposal)
    state=Harness(workflow,tmp_path/'run').run({})
    assert state['reason']=='call_limit' and state['calls']==1 and len(effects)==1


def test_invalid_arguments_and_authorizer_denial_have_no_effects(tmp_path):
    effects=[];proposal=direct();proposal['steps']['find']['arguments']={'wrong':'key'}
    workflow=factory(allowed_direct_tools={'lookup_entity'},registry=registered(lambda a:effects.append(a))).build(proposal)
    assert Harness(workflow,tmp_path/'invalid').run({})['status']=='blocked'
    workflow=factory(allowed_direct_tools={'lookup_entity'},registry=registered(lambda a:effects.append(a),authorize=lambda a:False)).build(direct())
    assert Harness(workflow,tmp_path/'denied').run({})['status']=='blocked'
    assert effects==[]


def test_zero_provider_budget_still_allows_one_direct_invocation(tmp_path):
    state=Harness(admitted(max_provider_requests_per_invocation=0,
        max_tool_calls_per_invocation=1),tmp_path/'run').run({})
    assert state['status']=='waiting' and state['calls']==1


def test_tool_outputs_feed_agent_without_dispatch_provider_call(endpoint,tmp_path):
    from dataclasses import replace
    from test_workflow_factory import config
    url,requests,replies=endpoint
    cfg=config();cfg=replace(cfg,profiles={'local':replace(cfg.profiles['local'],base_url=url)})
    proposal=direct();proposal['steps']['find']['next']='second'
    proposal['steps']['second']={'kind':'agent','agent':'finder','schema':'result',
        'inputs':['find'],'tools':[],'next':'review'}
    workflow=factory(cfg=cfg,allowed_direct_tools={'lookup_entity'}).build(proposal)
    replies.append({'role':'assistant','content':'{"found":true}'})
    h=Harness(workflow,tmp_path/'run');state=h.run({})
    assert state['status']=='waiting' and state['calls']==2
    assert len(requests)==1
    assert '"artifacts": {"find": {"found": true}}' in requests[0]['messages'][-1]['content']
    assert h.resume(choice='accept')['status']=='completed'


def test_tool_output_is_available_to_check_context(tmp_path):
    from prosaic_harness import WorkflowCatalog, WorkflowBindings, WorkflowPolicy, WorkflowFactory, Validator
    from test_workflow_factory import config
    seen=[];proposal=direct();proposal['steps']['find']['next']='check'
    proposal['steps']['check']={'kind':'check','from':'find','validators':['verify'],'pass':'review','fail':'rejected'}
    def verify(output,context):
        seen.append((output,context.artifacts['find']));return []
    f=WorkflowFactory(catalog=WorkflowCatalog(schemas={'result':{'type':'object'}}),
        bindings=WorkflowBindings(config=config(),custom_tools=registered(lambda args:{'found':True}),
            validators={'verify':Validator('v1',verify)}),
        policy=WorkflowPolicy(allowed_tools={'lookup_entity'},allowed_direct_tools={'lookup_entity'},
            allowed_schemas={'result'},allowed_validators={'verify'}))
    assert Harness(f.build(proposal),tmp_path/'run').run({})['status']=='waiting'
    assert seen==[({'found':True},{'found':True})]


def test_argument_strings_are_literal_and_proposal_mutation_is_detached(tmp_path):
    seen=[];proposal=direct();literal='{{request.secret}} ${lookup} $.artifacts.find'
    proposal['steps']['find']['arguments']={'query':literal}
    workflow=factory(allowed_direct_tools={'lookup_entity'},registry=registered(lambda args:seen.append(args) or {'found':True})).build(proposal)
    proposal['steps']['find']['arguments']['query']='mutated caller data'
    assert Harness(workflow,tmp_path/'run').run({'secret':'private'})['status']=='waiting'
    assert seen==[{'query':literal}]


def test_stale_tool_dependency_is_rejected_before_callback(tmp_path):
    effects=[];find_calls=[0];proposal=direct()
    proposal['steps']['find']['next']='gate'
    proposal['steps']['gate']={'kind':'gate','from':'find','field':['found'],'equals':True,'pass':'second','fail':'use'}
    proposal['steps']['second']={'kind':'tool','tool':'lookup_entity','arguments':{'query':'second'},
        'schema':'result','inputs':['find'],'next':'review'}
    proposal['steps']['review']['choices']['accept']='find'
    proposal['steps']['use']={'kind':'tool','tool':'lookup_entity','arguments':{'query':'must-not-run'},
        'schema':'result','inputs':['second'],'next':'done'}
    def callback(args):
        effects.append(args['query'])
        if args['query']=='literal':
            find_calls[0]+=1
            return {'found':find_calls[0]==1}
        return {'found':True}
    workflow=factory(allowed_direct_tools={'lookup_entity'},registry=registered(callback)).build(proposal)
    h=Harness(workflow,tmp_path/'run')
    assert h.run({})['status']=='waiting'
    state=h.resume(choice='accept')
    assert state['reason']=='stale_artifact' and state['current']=='use'
    assert effects==['literal','second','literal']
