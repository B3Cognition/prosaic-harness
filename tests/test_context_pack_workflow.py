"""User milestone: two nodes authored in Markdown/YAML receive different packs."""
import json,sys
from pathlib import Path
import pytest,yaml
import prosaic_runtime as api
from prosaic_harness import (Workflow,Harness,FileRunStore,ContextPackBindings,ContextAuthorizer,
    InputSource,EvidenceSource,ArtifactSource,Validator)
from support.context_pack_cases import scope_case
from test_workflow_rules_execution import rule_endpoint


def markdown_flow(tmp_path,cfg,*,guarded=False,authorize=lambda use:True,validators=None,plain_review=False):
    (tmp_path/'.prosaic/subagents').mkdir(parents=True)
    (tmp_path/'requirements.md').write_text('REQUIREMENTS-214: return valid structured evidence.')
    (tmp_path/'constraints.md').write_text('CONSTRAINTS-317: preserve the accepted candidate.')
    body='ALWAYS use supplied context and return JSON. NEVER invent facts.'
    seen=[];guards=[]
    if guarded:
        body+='\nALWAYS check full facts. <!-- enforce: facts(stage=final, on_violation=fail) -->'
        def check(stage,context):
            assert context.authoritative_input_data['workflow']['request']['private']=='UNRELATED-BUSINESS-419'
            assert 'UNRELATED-BUSINESS-419' not in json.dumps(context.input_data)
            seen.append(stage);return api.Verdict(True)
        guards=[api.Guard('facts','1',('final',),check,input_access='authoritativeAndModel')]
    (tmp_path/'.prosaic/subagents/worker.md').write_text('---\nname: worker\ndescription: Context pack fixture\n---\n'+body+'\n')
    (tmp_path/'result.json').write_text(json.dumps({'type':'object','required':['ok'],'properties':{'ok':{'type':'boolean'}},'additionalProperties':False}))
    endpoint=cfg.profiles['local']
    (tmp_path/'runtime.yml').write_text(yaml.safe_dump({'default_profile':'local','profiles':{'local':{
        'base_url':endpoint.base_url,'model':'synthetic','provider':endpoint.provider,'features':{'streaming':False}}}}))
    specs={
        'implementation':{'version':'1','taskSource':'task','slots':[{'source':s,'required':True} for s in ('task','requirements','constraints')]},
        'review':{'version':'1','taskSource':'task','slots':[{'source':s,'required':True} for s in ('task','requirements','candidate')]}}
    definition={'version':1,'source':'.prosaic','runtime':'runtime.yml','evidence':['requirements.md','constraints.md'],
        'contextPacks':specs,'agentContextPacks':{'subagents/worker.md':'implementation'},'start':'build',
        'limits':{'timeout_s':10,'max_provider_requests_per_invocation':2,'max_tool_calls_per_invocation':0},
        'steps':{'build':{'kind':'agent','agent':'subagents/worker.md','schema':'result.json','next':'review'},
            'review':{'kind':'agent','agent':'subagents/worker.md','schema':'result.json','contextPack':'review','inputs':['build'],'next':'done'},
            'done':{'kind':'finish','requires':['review']}}}
    if validators:
        for step in ('build','review'): definition['steps'][step]['validators']=list(validators)
    if plain_review:
        (tmp_path/'.prosaic/subagents/plain.md').write_text('---\nname: plain\ndescription: Legacy payload fixture\n---\nReturn JSON for {{args}}.\n')
        definition['steps']['review'].update(agent='subagents/plain.md')
        del definition['steps']['review']['contextPack']
    path=tmp_path/'workflow.yml';path.write_text(yaml.safe_dump(definition))
    bindings=ContextPackBindings(specs={},sources={'task':InputSource('/task'),'requirements':EvidenceSource('requirements.md'),
        'constraints':EvidenceSource('constraints.md'),'candidate':ArtifactSource('build')},scope=scope_case(),
        authorizer=ContextAuthorizer('access','1',authorize))
    workflow=Workflow.load(path,executable=str(Path(sys.executable).parent/'prosaic'),context_packs=bindings,guards=guards,
        repeatable_validators=list(validators) if validators else None)
    return workflow,seen


def controller(workflow,tmp_path,**kwargs):
    store=FileRunStore(tmp_path/'storage',namespace='test');store.initialize(context_packs=True)
    return Harness(workflow,store=store,run_id='a'*32,**kwargs)


@pytest.mark.parametrize('guarded',[False,True])
def test_markdown_two_nodes_select_different_context_and_keep_private_validation(rule_endpoint,tmp_path,guarded):
    cfg,requests,replies=rule_endpoint;replies.extend(['{"ok":true}','{"ok":true}'])
    checked=[]
    def validate(output,context):
        assert context.request['private']=='UNRELATED-BUSINESS-419'
        assert 'constraints.md' in context.evidence
        checked.append(context.step);return []
    validators={'controller':Validator('1',validate)}
    workflow,guards=markdown_flow(tmp_path,cfg,guarded=guarded,validators=validators)
    harness=controller(workflow,tmp_path,validators=validators)
    state=harness.run({'task':'TASK-101: assess the candidate','private':'UNRELATED-BUSINESS-419'})
    assert state['status']=='completed' and state['version']==3
    assert checked==['build','review'] and len(requests)==2
    first,second=map(json.dumps,requests)
    assert 'TASK-101' in first and 'REQUIREMENTS-214' in first and 'CONSTRAINTS-317' in first
    assert 'TASK-101' in second and 'REQUIREMENTS-214' in second and 'CONSTRAINTS-317' not in second
    assert 'UNRELATED-BUSINESS-419' not in first+second
    assert len(guards)==(2 if guarded else 0)
    for item in state['invocations']:
        receipt=harness.store.load_receipt(state['run_id'],item['id'])
        from prosaic_harness.context_packs.records import ContextPackInvocation
        assert receipt['version']==2 and ContextPackInvocation.from_dict(receipt['contextPack']).projection['originalArguments']['request']['private']=='UNRELATED-BUSINESS-419'
        if guarded: assert 'workflow_rules_v2' in receipt['result']['metadata']
        binding=state['bindings'][item['step']]
        assert binding['contextPackIdentity']==receipt['contextPack']['selectedPackReference']['packIdentity']
        assert binding['contextSourceRevisions']


def test_pack_workflow_refuses_legacy_storage_before_provider(rule_endpoint,tmp_path):
    from prosaic_harness import StoreIncompatible
    cfg,requests,replies=rule_endpoint;workflow,_=markdown_flow(tmp_path,cfg)
    store=FileRunStore(tmp_path/'storage',namespace='test')
    with pytest.raises(StoreIncompatible):
        Harness(workflow,store=store,run_id='a'*32).run({'task':'work'})
    assert requests==[]


def test_opted_in_run_wraps_pack_free_nodes_without_changing_their_input(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint;replies.extend(['{"ok":true}','{"ok":true}'])
    workflow,_=markdown_flow(tmp_path,cfg,plain_review=True)
    harness=controller(workflow,tmp_path)
    state=harness.run({'task':'work','private':'UNRELATED-BUSINESS-419'})
    assert state['status']=='completed' and len(requests)==2
    first,second=[harness.store.load_receipt(state['run_id'],i['id']) for i in state['invocations']]
    assert first['version']==second['version']==2 and second['contextPack'] is None and second['contextPackResult'] is None
    assert state['bindings']['review']['contextPackIdentity'] is None
    assert 'UNRELATED-BUSINESS-419' not in json.dumps(requests[0])
    assert 'UNRELATED-BUSINESS-419' in json.dumps(requests[1])
    assert Harness(workflow,store=harness.store,run_id=state['run_id']).resume()['status']=='completed'
