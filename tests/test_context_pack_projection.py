import json
import pytest
from prosaic_harness import ContextPacker,ContextPackSpec,ContextSlot,ContextPackError,CheckContext
from prosaic_harness.context_packs.sources import capture_sources
from prosaic_harness.context_packs.projection import project_step,StepPackProjection
from prosaic_harness.context_packs.codec import digest
from prosaic_harness.workflow import digest as workflow_digest
from test_context_pack_sources import source_case,evidence_case


def context_case(arguments):
    return CheckContext('review',arguments['request'],arguments['artifacts']|{'other':{'private':'GLOBAL-517'}},evidence_case(),arguments['artifact_bindings'],{'approval':{'choice':'approve','response':{'private':'HUMAN-219'}}})


def test_only_declared_evidence_reaches_model_but_all_controller_facts_are_frozen():
    spec,arguments,binding=source_case()
    arguments['human_responses']={'approval':{'choice':'approve','response':{'private':'HUMAN-219'}}}
    candidates=ContextPacker().compose(spec,capture_sources(spec,arguments,evidence_case(),binding))
    original=workflow_digest(arguments)
    projection=project_step('review',arguments,candidates,controller_validation_context=context_case(arguments),required_dependencies=['build'])
    model=json.dumps(projection.variants)
    assert all(value not in model for value in ('UNSELECTED-419','GLOBAL-517','HUMAN-219','# Constraints'))
    assert 'accepted build' in model and 'Review service impact' in model
    assert projection.original_arguments_digest==original
    assert projection.authoritative_input_data['workflow']['request']['unrelated']=='UNSELECTED-419'
    frozen=projection.controller_validation_context
    assert frozen['artifacts']['other']=={'private':'GLOBAL-517'}
    assert frozen['humanResponses']['approval']['response']=={'private':'HUMAN-219'}
    root=projection.variants[0]
    assert root['workflow']['request']['citationId'] in {i['citationId'] for i in root['contextPack']['items']}
    assert 'candidate' not in root['workflow']['artifacts']['build']
    assert StepPackProjection.from_dict(projection.to_dict()).identity==projection.identity


def test_pack_envelope_and_complete_input_have_distinct_bound_digest_mapping():
    spec,arguments,binding=source_case()
    candidates=ContextPacker().compose(spec,capture_sources(spec,arguments,evidence_case(),binding))
    projection=project_step('review',arguments,candidates,controller_validation_context=context_case(arguments))
    entry=projection.pack_index_mapping[0]
    assert entry['envelopeDigest']==digest(candidates.variants[0])
    assert entry['inputDataDigest']==digest(projection.variants[0])
    assert entry['envelopeDigest']!=entry['inputDataDigest']
    selected=ContextPacker().select(candidates,entry['packIndex'],entry['envelopeDigest'])
    assert selected.envelope==projection.variants[0]['contextPack']


def test_filter_to_empty_required_dependency_cannot_claim_coverage():
    spec,arguments,binding=source_case()
    spec=ContextPackSpec('review','1',[ContextSlot('task',required=True),ContextSlot('candidate',required=True,min_items=0,labels={'absent':['yes']})],task_source='task')
    candidates=ContextPacker().compose(spec,capture_sources(spec,arguments,evidence_case(),binding))
    with pytest.raises(ContextPackError,match='requiredContextMissing'): project_step('review',arguments,candidates,controller_validation_context=context_case(arguments))


def test_complete_empty_json_artifact_can_be_actually_selected():
    spec,arguments,binding=source_case()
    arguments['artifacts']['build']=[]
    arguments['artifact_bindings']['build']['sha256']=workflow_digest([])
    candidates=ContextPacker().compose(spec,capture_sources(spec,arguments,evidence_case(),binding))
    projection=project_step('review',arguments,candidates,controller_validation_context=context_case(arguments))
    assert any(i['content']==[] for i in projection.variants[0]['contextPack']['items'])


def test_full_controller_validation_context_cannot_be_inferred_from_selected_arguments():
    spec,arguments,binding=source_case()
    candidates=ContextPacker().compose(spec,capture_sources(spec,arguments,evidence_case(),binding))
    with pytest.raises(ContextPackError): project_step('review',arguments,candidates)


def test_projection_restore_rejects_business_fallthrough_even_with_recomputed_digests():
    spec,arguments,binding=source_case()
    candidates=ContextPacker().compose(spec,capture_sources(spec,arguments,evidence_case(),binding))
    value=project_step('review',arguments,candidates,controller_validation_context=context_case(arguments)).to_dict()
    value['variants'][0]['workflow']['request']=arguments['request']
    value['packIndexMapping'][0]['inputDataDigest']=digest(value['variants'][0])
    with pytest.raises(ContextPackError): StepPackProjection.from_dict(value)
