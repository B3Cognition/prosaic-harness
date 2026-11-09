import json
import pytest
import yaml
from prosaic_harness import (Workflow,WorkflowBindings,WorkflowCatalog,WorkflowFactory,WorkflowPolicy,
    WorkflowBundle,WorkflowAdmissionError,ContextPackError,ContextPackBindings,ContextAuthorizer,
    ContextPackSpec,ContextSlot,InputSource,ArtifactSource,EvidenceSource)
from prosaic_runtime import ProsaicArtifact,Guard,Verdict
from support.context_pack_cases import scope_case
from test_workflow_factory import config


def pack_bindings(*, defaults=True, sources=None):
    specs={'work':ContextPackSpec('work','1',[ContextSlot('task',required=True)],task_source='task'),
           'review':ContextPackSpec('review','1',[ContextSlot('task',required=True),ContextSlot('candidate',required=True)],task_source='task')}
    return ContextPackBindings(specs=specs,sources=sources or {'task':InputSource('/task'),'candidate':ArtifactSource('build')},scope=scope_case(),authorizer=ContextAuthorizer('access','1',lambda use:pytest.fail('admission called authorizer')),agent_defaults={'worker':'work'} if defaults else None)


def graph():
    return {'version':1,'start':'build','steps':{
        'build':{'kind':'agent','agent':'worker','schema':'result','next':'review'},
        'review':{'kind':'agent','agent':'worker','schema':'result','inputs':['build'],'contextPack':'review','next':'done'},
        'done':{'kind':'finish','requires':['review']}}}


def factory(*, packs=None, public=None, guards=(), body=None):
    artifact=ProsaicArtifact('worker','subagent',{'name':'worker','description':'Synthetic reviewer'},body or 'ALWAYS use declared task and context. NEVER invent facts.')
    catalog=WorkflowCatalog(agents={'worker':artifact},schemas={'result':{'type':'object'}},public_metadata=public)
    return WorkflowFactory(catalog=catalog,bindings=WorkflowBindings(config=config(),guards=guards,context_packs=packs or pack_bindings()),policy=WorkflowPolicy(allowed_agents=frozenset({'worker'}),allowed_schemas=frozenset({'result'}),allow_agent_composition=True,allowed_guards=frozenset(g.name for g in guards),max_provider_requests_per_invocation=2,max_tool_calls_per_invocation=0))


def test_same_agent_two_nodes_uses_different_context_and_bundle_preserves_bindings():
    f=factory(public={'contextPacks':{'review':{'description':'Review accepted candidate'}}})
    workflow=f.build(graph())
    assert workflow.context_pack_for('build')=='work'
    assert workflow.context_pack_for('review')=='review'
    bundle=WorkflowBundle('1',f)
    prepared=bundle.prepare_json(json.dumps({'definition':graph()}))
    restored=bundle.reconstruct(prepared.proposal_json,prepared.reference)
    assert restored.context_pack_for('review')=='review'
    assert restored.current_fingerprint()==workflow.current_fingerprint()


def test_model_proposals_choose_only_public_aliases_and_cannot_define_packs():
    f=factory()
    with pytest.raises(WorkflowAdmissionError): f.build_json(json.dumps({'definition':graph()}))
    declaration=graph()|{'contextPacks':{'new':{'version':'1','taskSource':'task','slots':[{'source':'task','required':True}]}}}
    with pytest.raises(WorkflowAdmissionError): factory(public={'contextPacks':{'review':{'description':'Review'}}}).build_json(json.dumps({'definition':declaration}))
    public=factory(public={'contextPacks':{'review':{'description':'Review'}}})
    doc=public.describe(); schema=public.proposal_schema()
    assert doc['contextPacks']=={'review':{'description':'Review'}}
    encoded=json.dumps([doc,schema])
    assert 'candidate' not in encoded and '/task' not in encoded and 'tenant' not in encoded
    assert 'contextPack' in encoded


def test_missing_task_or_required_artifact_coverage_is_rejected():
    sources={'task':ArtifactSource('build'),'candidate':ArtifactSource('build')}
    with pytest.raises((WorkflowAdmissionError,ContextPackError)): factory(packs=pack_bindings(sources=sources)).build(graph())
    definition=graph();definition['steps']['review']['contextPack']='work'
    with pytest.raises((WorkflowAdmissionError,ContextPackError)): factory().build(definition)


def test_static_markdown_workflow_admits_named_yaml_specs(tmp_path,monkeypatch):
    from test_harness import setup
    setup(tmp_path,monkeypatch)
    monkeypatch.setattr('prosaic_harness.workflow.inspect_artifact',lambda *a,**k:ProsaicArtifact('author','subagent',{'name':'author','description':'Synthetic'},'ALWAYS use declared context. NEVER infer missing facts.'))
    path=tmp_path/'flow.yml'; value=yaml.safe_load(path.read_text())
    value['contextPacks']={'task-only':{'version':'1','taskSource':'task','slots':[{'source':'task','required':True}]}}
    value['agentContextPacks']={'subagents/author.md':'task-only'}
    value['limits'].update(max_provider_requests_per_invocation=2,max_tool_calls_per_invocation=0)
    path.write_text(yaml.safe_dump(value))
    binding=ContextPackBindings(specs={},sources={'task':InputSource('/task')},scope=scope_case(),authorizer=ContextAuthorizer('access','1',lambda use:True))
    workflow=Workflow.load(path,context_packs=binding)
    assert workflow.context_pack_for('author')=='task-only'
    assert workflow.current_fingerprint()==workflow.fingerprint


def test_guard_access_is_preserved_by_factory_bundle_copies():
    guard=Guard('facts','1',('final',),lambda s,c:Verdict(True),input_access='authoritativeAndModel')
    f=factory(guards=[guard],body='- ALWAYS check facts. <!-- enforce: facts(stage=final, on_violation=fail) -->')
    assert f._frozen_copy()._rule_bindings.guards[0].input_access=='authoritativeAndModel'


def test_required_node_pin_cannot_be_omitted_and_yaml_defaults_cannot_misspell_agents():
    registered=pack_bindings()
    registered=ContextPackBindings(specs=registered.specs,sources=registered.sources,scope=registered.scope,authorizer=registered.authorizer,agent_defaults=registered.agent_defaults,required_packs={'agents':{},'nodes':{'missing':'work'}})
    with pytest.raises((ContextPackError,WorkflowAdmissionError)): factory(packs=registered).build(graph())
    definition=graph()|{'agentContextPacks':{'misspelled':'work'}}
    with pytest.raises((ContextPackError,WorkflowAdmissionError)): factory().build(definition)


def test_context_public_descriptions_do_not_change_bundle_identity_but_alias_permissions_do():
    a=factory(public={'contextPacks':{'review':{'description':'First'}}})
    b=factory(public={'contextPacks':{'review':{'description':'Second'}}})
    c=factory(public={'contextPacks':{'review':{'description':'Second'},'work':{'description':'Work'}}})
    assert WorkflowBundle('1',a).identity==WorkflowBundle('1',b).identity
    assert WorkflowBundle('1',a).identity!=WorkflowBundle('1',c).identity


def test_trusted_build_can_define_packs_using_only_registered_sources():
    registered=ContextPackBindings(specs={},sources={'task':InputSource('/task')},scope=scope_case(),authorizer=ContextAuthorizer('access','1',lambda use:True))
    definition={'version':1,'start':'build','contextPacks':{'assignment':{'version':'1','taskSource':'task','slots':[{'source':'task','required':True}]}},'agentContextPacks':{'worker':'assignment'},'steps':{'build':{'kind':'agent','agent':'worker','schema':'result','next':'done'},'done':{'kind':'finish','requires':['build']}}}
    assert factory(packs=registered).build(definition).context_pack_for('build')=='assignment'
    with pytest.raises(WorkflowAdmissionError): factory(packs=registered).build_json(json.dumps({'definition':definition}))


def test_file_sources_and_undeclared_artifacts_fail_during_admission():
    for source in (EvidenceSource('private.md'),ArtifactSource('undeclared')):
        registered=pack_bindings(sources={'task':InputSource('/task'),'candidate':source})
        with pytest.raises((ContextPackError,WorkflowAdmissionError)): factory(packs=registered).build(graph())


def test_declared_feedback_and_repeatable_validator_options_survive_bundle_copy():
    f=factory(public={'contextPacks':{'review':{'description':'Review'}}})
    f._feedback_catalog={'reviewFailed':'Review the declared constraints.'}
    f._repeatable_validators=('reviewer',)
    copy=f._frozen_copy()
    assert copy._feedback_catalog==f._feedback_catalog and copy._repeatable_validators==('reviewer',)
    assert WorkflowBundle('1',copy).identity==WorkflowBundle('1',f).identity


def test_pack_nodes_require_finite_host_invocation_caps():
    from dataclasses import replace
    f=factory();f._policy=replace(f._policy,max_provider_requests_per_invocation=None,max_tool_calls_per_invocation=None)
    with pytest.raises(WorkflowAdmissionError): f.build(graph())
