import json
import pytest
from prosaic_harness import (WorkflowFactory, WorkflowCatalog, WorkflowBindings,
    WorkflowPolicy, Validator, ContextPackBindings, ContextAuthorizer)
from prosaic_runtime import ProsaicArtifact
from test_context_pack_authoring import pack_bindings
from test_context_pack_workflow import controller
from test_workflow_rules_execution import rule_endpoint


def test_approval_after_packed_step_gets_current_context(rule_endpoint, tmp_path):
    cfg, requests, replies = rule_endpoint
    replies.append('{"ok":true}')
    seen = []
    def approval(output, context):
        seen.append((context.step, context.artifacts))
        return []
    validators = {'approval': Validator('1', approval)}
    original = pack_bindings()
    packs = ContextPackBindings(specs=original.specs, sources=original.sources, scope=original.scope,
        agent_defaults=original.agent_defaults, authorizer=ContextAuthorizer('access', '1', lambda use: True))
    artifact = ProsaicArtifact('worker', 'subagent', {'name': 'worker', 'description': 'Review fixture'},
        'ALWAYS return JSON. NEVER invent facts.')
    workflow = WorkflowFactory(
        catalog=WorkflowCatalog(agents={'worker': artifact}, schemas={'result': {'type': 'object'}}),
        bindings=WorkflowBindings(config=cfg, validators=validators, context_packs=packs,
            repeatable_validators=['approval']),
        policy=WorkflowPolicy(allowed_agents={'worker'}, allowed_schemas={'result'}, allowed_validators={'approval'},
            max_provider_requests_per_invocation=1, max_tool_calls_per_invocation=0),
    ).build({'version': 1, 'start': 'build', 'steps': {
        'build': {'kind': 'agent', 'agent': 'worker', 'schema': 'result', 'next': 'approve'},
        'approve': {'kind': 'pause', 'question': 'Approve?', 'choices': {'yes': 'done'},
            'response_schema': 'result', 'validators': ['approval']},
        'done': {'kind': 'finish'},
    }})
    harness = controller(workflow, tmp_path, validators=validators)
    state = harness.run({'task': 'Review'})
    assert state['status'] == 'waiting'
    reply = harness.resume(choice='yes', response={}, expected_revision=harness.status().revision)
    assert reply['status'] == 'completed'
    assert seen == [('approve', {'build': {'ok': True}})]


def test_private_facts_are_independent_of_model_input_byte_budget(rule_endpoint, tmp_path):
    from prosaic_runtime import Guard, Verdict
    cfg, requests, replies = rule_endpoint
    replies.append('{"ok":true}')
    checked = []
    def check(stage, context):
        checked.append(len(context.authoritative_input_data['workflow']['request']['private']))
        return Verdict(True)
    guard = Guard('facts', '1', ('final',), check, input_access='authoritativeAndModel')
    original = pack_bindings()
    packs = ContextPackBindings(specs=original.specs, sources=original.sources, scope=original.scope,
        agent_defaults=original.agent_defaults, authorizer=ContextAuthorizer('access', '1', lambda use: True))
    artifact = ProsaicArtifact('worker', 'subagent', {'name': 'worker', 'description': 'Review fixture'},
        'ALWAYS check facts. <!-- enforce: facts(stage=final, on_violation=fail) -->')
    workflow = WorkflowFactory(
        catalog=WorkflowCatalog(agents={'worker': artifact}, schemas={'result': {'type': 'object'}}),
        bindings=WorkflowBindings(config=cfg, guards=[guard], context_packs=packs),
        policy=WorkflowPolicy(allowed_agents={'worker'}, allowed_schemas={'result'}, allowed_guards={'facts'},
            max_provider_requests_per_invocation=1, max_tool_calls_per_invocation=0, max_invocation_bytes=4096),
    ).build({'version': 1, 'start': 'build', 'steps': {
        'build': {'kind': 'agent', 'agent': 'worker', 'schema': 'result', 'next': 'done'},
        'done': {'kind': 'finish'},
    }})
    harness = controller(workflow, tmp_path)
    state = harness.run({'task': 'Review', 'private': 'x'*8192})
    assert state['status'] == 'completed', state['reason']
    assert checked == [8192]
    assert 'x'*100 not in json.dumps(requests)


@pytest.mark.parametrize('packed',[True,False])
def test_model_input_bound_and_legacy_argument_bound_remain_enforced(rule_endpoint,tmp_path,packed):
    cfg,requests,_=rule_endpoint
    original=pack_bindings()
    packs=ContextPackBindings(specs=original.specs,sources=original.sources,scope=original.scope,
        agent_defaults=original.agent_defaults,authorizer=ContextAuthorizer('access','1',lambda use:True))
    artifact=ProsaicArtifact('worker','subagent',{'name':'worker','description':'Bounded fixture'},
        'ALWAYS return JSON. NEVER invent facts.')
    workflow=WorkflowFactory(catalog=WorkflowCatalog(agents={'worker':artifact},schemas={'result':{'type':'object'}}),
        bindings=WorkflowBindings(config=cfg,context_packs=packs if packed else None),
        policy=WorkflowPolicy(allowed_agents={'worker'},allowed_schemas={'result'},max_invocation_bytes=4096,
            max_provider_requests_per_invocation=1,max_tool_calls_per_invocation=0)).build({
        'version':1,'start':'build','steps':{'build':{'kind':'agent','agent':'worker','schema':'result','next':'done'},
            'done':{'kind':'finish'}}})
    state=controller(workflow,tmp_path).run({'task':'t'*5000 if packed else 'work','private':'p'*8192})
    assert state['status']=='blocked' and requests==[]
    if not packed:assert state['reason']=='invocation_limit'
