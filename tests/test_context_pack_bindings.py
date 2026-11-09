import pytest
from prosaic_harness import (ContextPackBindings,ContextAuthorizer,ContextPackError,
    ContextPackSpec,ContextSlot,InputSource,ArtifactSource,EvidenceSource)
from support.context_pack_cases import scope_case,spec_case


def bindings(**changes):
    return ContextPackBindings(**(dict(specs={'default':spec_case(),'task-only':ContextPackSpec('task-only','1',[ContextSlot('task',required=True)],task_source='task')},sources={'task':InputSource('/task')},scope=scope_case(),authorizer=ContextAuthorizer('access','1',lambda use:True),agent_defaults={'worker':'default'})|changes))


def test_node_override_agent_default_task_only_and_pins():
    registered=bindings()
    assert registered.resolve('build',{'kind':'agent','agent':'worker'})=='default'
    assert registered.resolve('review',{'kind':'agent','agent':'worker','contextPack':'task-only'})=='task-only'
    assert registered.resolve('build',{'kind':'agent','agent':'worker'})=='default'
    pinned=bindings(required_packs={'agents':{'worker':'default'},'nodes':{}})
    with pytest.raises(ContextPackError): pinned.resolve('review',{'kind':'agent','agent':'worker','contextPack':'task-only'})
    with pytest.raises(ContextPackError): bindings(required_packs={'agents':{'worker':'default'},'nodes':{'review':'task-only'}}).resolve('review',{'kind':'agent','agent':'worker'})


@pytest.mark.parametrize('value',[None,'missing',False,{},['default']])
def test_explicit_null_unknown_and_untyped_pack_refs_are_invalid(value):
    with pytest.raises(ContextPackError): bindings().resolve('build',{'kind':'agent','agent':'worker','contextPack':value})


def test_bindings_are_owned_and_authorizer_descriptor_drift_is_rejected():
    specs={'default':spec_case()};defaults={'worker':'default'}
    authorizer=ContextAuthorizer('access','1',lambda use:pytest.fail('admission called authorization'))
    registered=bindings(specs=specs,agent_defaults=defaults,authorizer=authorizer)
    identity=registered.identity
    specs.clear(); defaults.clear()
    assert registered.resolve('build',{'kind':'agent','agent':'worker'})=='default'
    assert registered.frozen_copy().identity==identity
    object.__setattr__(authorizer,'version','2')
    with pytest.raises(ContextPackError,match='contextBindingMismatch'): registered.readmit()


def test_registry_can_serve_many_nodes_without_capturing_every_source():
    from prosaic_harness.context_packs.sources import capture_sources
    sources={'task':InputSource('/task'),**{f'facts{i}':InputSource(f'/facts{i}') for i in range(24)}}
    registered=bindings(sources=sources)
    snapshot=capture_sources(spec_case(),{'request':{'task':'Review','facts23':'UNSELECTED'}},{},registered)
    assert len(registered.sources)==25
    assert len(snapshot.sources)==1 and snapshot.sources[0].alias=='task'
