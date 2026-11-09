import hashlib
from pathlib import Path
import pytest
from prosaic_harness import (ContextPackBindings,ContextAuthorizer,ContextPackSpec,ContextSlot,
    InputSource,EvidenceSource,ArtifactSource,ContextPacker,ContextPackError)
from prosaic_harness.context_packs.sources import capture_sources,resolve_pack
from prosaic_harness.workflow import digest as workflow_digest
from support.context_pack_cases import scope_case

FIXTURE=Path(__file__).parent/'fixtures/context_packs/markdown'


def evidence_case():
    result={}
    for name in ('requirements.md','constraints.md'):
        content=(FIXTURE/name).read_bytes()
        result[name]={'text':content.decode(),'sha256':hashlib.sha256(content).hexdigest()}
    return result


def source_case():
    output={'candidate':'accepted build'}
    arguments={'request':{'task':'Review service impact','unrelated':'UNSELECTED-419'},
        'artifacts':{'build':output},'artifact_bindings':{'build':{'id':'a'*32,'sha256':workflow_digest(output),'dependencies':{}}},
        'sources':evidence_case(),'validation_feedback':None}
    spec=ContextPackSpec('review','1',[ContextSlot('task',required=True),ContextSlot('requirements',required=True),ContextSlot('candidate',required=True)],task_source='task')
    binding=ContextPackBindings(specs={'review':spec},sources={'task':InputSource('/task'),
        'requirements':EvidenceSource('requirements.md'),'constraints':EvidenceSource('constraints.md'),
        'candidate':ArtifactSource('build')},scope=scope_case(),authorizer=ContextAuthorizer('access','1',lambda use:pytest.fail('capture invoked permission callback')))
    return spec,arguments,binding


def test_sources_normalize_only_declared_captured_roots_with_exact_provenance():
    spec,arguments,binding=source_case()
    snapshot=capture_sources(spec,arguments,evidence_case(),binding)
    by_alias={i.source_alias:i for i in snapshot.items}
    assert set(by_alias)=={'task','requirements','candidate'}
    assert by_alias['task'].content=='Review service impact'
    assert by_alias['requirements'].content==(FIXTURE/'requirements.md').read_text()
    assert by_alias['requirements'].content_sha256==evidence_case()['requirements.md']['sha256']
    assert by_alias['candidate'].locator=={'kind':'record','id':'build'}
    assert 'UNSELECTED-419' not in str(snapshot.to_dict())
    assert resolve_pack({'kind':'agent','agent':'reviewer','contextPack':'review'},'reviewer',binding).identity==spec.identity


def test_capture_reads_only_owned_ledger_even_after_original_file_changes(tmp_path,monkeypatch):
    spec,arguments,binding=source_case(); ledger=evidence_case()
    original=tmp_path/'requirements.md'; original.write_text('Changed after capture')
    def forbidden(*a,**k): pytest.fail('capture refreshed a file')
    monkeypatch.setattr(Path,'read_bytes',forbidden)
    monkeypatch.setattr(Path,'read_text',forbidden)
    snapshot=capture_sources(spec,arguments,ledger,binding)
    assert next(i for i in snapshot.items if i.source_alias=='requirements').content==ledger['requirements.md']['text']


def test_missing_and_mismatched_capture_does_not_refresh_or_invent_acceptance():
    spec,arguments,binding=source_case()
    snapshot=capture_sources(spec,arguments,{},binding)
    assert next(s for s in snapshot.sources if s.alias=='requirements').outcome=='unavailable'
    with pytest.raises(ContextPackError,match='requiredContextMissing'): ContextPacker().compose(spec,snapshot)
    wrong=evidence_case();wrong['requirements.md']['sha256']='0'*64
    with pytest.raises(ContextPackError): capture_sources(spec,arguments,wrong,binding)
    wrong=evidence_case();wrong['requirements.md']['text']='\ud800'
    with pytest.raises(ContextPackError): capture_sources(spec,arguments,wrong,binding)
    arguments['artifacts']['build']={'candidate':'changed'}
    with pytest.raises(ContextPackError): capture_sources(spec,arguments,evidence_case(),binding)


def test_input_pointer_arrays_and_escapes_are_exact():
    spec=ContextPackSpec('task','1',[ContextSlot('task',required=True)],task_source='task')
    binding=ContextPackBindings(specs={'task':spec},sources={'task':InputSource('/a~1b/~0x/0')},scope=scope_case(),authorizer=ContextAuthorizer('access','1',lambda use:True))
    snapshot=capture_sources(spec,{'request':{'a/b':{'~x':['assignment']}}}, {},binding)
    assert snapshot.items[0].content=='assignment'
    assert snapshot.items[0].locator=={'kind':'jsonPointer','pointer':'/a~1b/~0x/0'}


def test_input_revision_binds_the_declared_value_without_hashing_undeclared_siblings():
    spec,arguments,binding=source_case()
    before=capture_sources(spec,arguments,evidence_case(),binding)
    arguments['request']['unrelated']='different private value'
    after=capture_sources(spec,arguments,evidence_case(),binding)
    assert before.identity==after.identity


def test_partial_structured_results_retain_their_explicit_domain_status():
    spec,arguments,binding=source_case()
    arguments['artifacts']['build']={'records':[],'complete':False}
    arguments['artifact_bindings']['build']['sha256']=workflow_digest(arguments['artifacts']['build'])
    snapshot=capture_sources(spec,arguments,evidence_case(),binding)
    candidate=next(i for i in snapshot.items if i.source_alias=='candidate')
    assert candidate.content=={'records':[],'complete':False}
