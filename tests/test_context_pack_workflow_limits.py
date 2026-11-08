from prosaic_harness import (WorkflowFactory,WorkflowCatalog,WorkflowBindings,WorkflowPolicy,ContextPackBindings,ContextAuthorizer)
import prosaic_runtime as api
from test_context_pack_authoring import pack_bindings,graph
from test_context_pack_workflow import controller
from test_workflow_rules_execution import rule_endpoint


def bounded_flow(cfg,definition=None,**caps):
    base=pack_bindings()
    bindings=ContextPackBindings(specs=base.specs,sources=base.sources,scope=base.scope,
        agent_defaults=base.agent_defaults,authorizer=ContextAuthorizer('access','1',lambda use:True))
    artifact=api.ProsaicArtifact('worker','subagent',{'name':'worker','description':'Bounded fixture'},
        'ALWAYS return JSON. NEVER invent facts.')
    return WorkflowFactory(catalog=WorkflowCatalog(agents={'worker':artifact},schemas={'result':{'type':'object'}}),
        bindings=WorkflowBindings(config=cfg,context_packs=bindings),
        policy=WorkflowPolicy(allowed_agents={'worker'},allowed_schemas={'result'},allow_agent_composition=True,
            max_provider_requests_per_invocation=2,max_tool_calls_per_invocation=0,**caps)).build(definition or graph())


def test_minimum_profile_evidence_must_fit_before_provider_dispatch(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint;replies.extend(['{"ok":true}']*2)
    harness=controller(bounded_flow(cfg,max_metadata_bytes=300),tmp_path)
    state=harness.run({'task':'work'})
    assert state['status']=='blocked' and requests==[]


def test_tiny_receipt_capacity_fails_before_provider_dispatch(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint;replies.extend(['{"ok":true}']*2)
    harness=controller(bounded_flow(cfg,max_receipt_bytes=65536),tmp_path)
    state=harness.run({'task':'work'})
    assert state['status']=='blocked' and requests==[]


def test_event_overflow_is_bounded_before_retention_and_stops_execution(rule_endpoint,tmp_path,monkeypatch):
    cfg,requests,replies=rule_endpoint;replies.append('{"ok":true}')
    harness=controller(bounded_flow(cfg),tmp_path)
    original=harness.runtime.turn
    def noisy(prepared,**options):
        options['on_event']({'event':'tool_started','name':'x','payload':'x'*70000})
        return original(prepared,**options)
    monkeypatch.setattr(harness.runtime,'turn',noisy)
    state=harness.run({'task':'work'})
    assert state['status']=='blocked' and requests==[] and state['pending'] is None
    packet=harness.store.load_receipt(state['run_id'],state['invocations'][0]['id'])
    assert all('payload' not in event for event in packet['events'])


def test_large_guard_proofs_are_reserved_or_refused_before_spend(rule_endpoint,tmp_path):
    from prosaic_harness.session_codec import node_count
    from prosaic_harness import ContextPackBindings,ContextAuthorizer
    cfg,requests,replies=rule_endpoint;replies.extend(['{"ok":true}']*2)
    names=['check_'+str(i)+'_'+'x'*35 for i in range(200)]
    guards=[api.Guard(name,'1',('final',),lambda stage,context:api.Verdict(True),input_access='authoritativeAndModel') for name in names]
    body='\n'.join(f'ALWAYS check facts. <!-- enforce: {name}(stage=final, on_violation=fail) -->' for name in names)
    artifact=api.ProsaicArtifact.from_inspection({'id':'worker.md','type':'subagent',
        'frontmatter':{'name':'worker','description':'Large guarded profile'},'body':body})
    base=pack_bindings()
    bindings=ContextPackBindings(specs=base.specs,sources=base.sources,scope=base.scope,
        agent_defaults=base.agent_defaults,authorizer=ContextAuthorizer('access','1',lambda use:True))
    workflow=WorkflowFactory(catalog=WorkflowCatalog(agents={'worker':artifact},schemas={'result':{'type':'object'}}),
        bindings=WorkflowBindings(config=cfg,guards=guards,context_packs=bindings),
        policy=WorkflowPolicy(allowed_agents={'worker'},allowed_schemas={'result'},allowed_guards=set(names),
            max_provider_requests_per_invocation=2,max_tool_calls_per_invocation=0)).build({'version':1,'start':'build',
                'steps':{'build':{'kind':'agent','agent':'worker','schema':'result','next':'done'},'done':{'kind':'finish'}}})
    harness=controller(workflow,tmp_path)
    state=harness.run({'task':'work'})
    if state['status']=='blocked':
        assert requests==[]
        return
    assert state['status']=='completed'
    invocation=state['invocations'][0];packet=harness.store.load_receipt(state['run_id'],invocation['id'])
    reservation=state['contextPacks']['reservations'][invocation['id']]
    metadata={'metadata':packet['result']['metadata'],**packet['contextPackResult']}
    assert node_count(metadata)<=reservation['metadataNodes']
