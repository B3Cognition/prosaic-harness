from dataclasses import asdict
import pytest
import prosaic_runtime as api
from prosaic_harness import ContextPacker,CheckContext
from prosaic_harness.contracts import seal,validate_state,validate_receipt
from prosaic_harness.context_packs.codec import digest
from prosaic_harness.context_packs.records import ContextPackInvocation
from prosaic_harness.context_packs.sources import capture_sources
from prosaic_harness.context_packs.projection import project_step
from test_context_pack_authoring import factory,graph
from test_context_pack_records import result_case


def workflow_case(*,private_source=False):
    from test_context_pack_authoring import pack_bindings
    from prosaic_harness import InputSource
    bindings=pack_bindings()
    if private_source:
        bindings=pack_bindings(sources={**bindings.sources,'private':InputSource('/private')})
    workflow=factory(packs=bindings).build(graph())
    state=seal(dict(version=2,run_id='a'*32,fingerprint=workflow.fingerprint,validators={},
        inputs={'task':'Review the selected context','private':'private-517'},status='running',reason=None,
        current='build',calls=0,visits={'build':1},outputs={},bindings={},history=[],pending=None,
        entered=True,attempt=0,feedback=None,invocations=[],evidence={},started_at=0,deadline=None))
    arguments=dict(request=state['inputs'],artifacts={},artifact_bindings={},sources={},validation_feedback=None)
    bindings=workflow._context_packs
    spec=bindings.specs['work'];packer=ContextPacker()
    candidates=packer.compose(spec,capture_sources(spec,arguments,{},bindings))
    check_context=CheckContext('build',state['inputs'],{},{},{},{})
    projection=project_step('build',arguments,candidates,controller_validation_context=check_context)
    pack=packer.select(candidates,0,digest(candidates.variants[0]))
    runtime=api.ProsaicRuntime(workflow.config)
    prepared=runtime.prepare_turn(workflow.artifacts['build'],message='Return JSON',
        input_data=projection.variants[0],input_profile=projection.profile,
        authoritative_input_data=projection.authoritative_input_data,authoritative_input_profile=projection.authoritative_input_profile,
        policy=api.RunPolicy(max_provider_requests=2,max_tool_calls=0),
        limits=api.TurnLimits(max_metadata_bytes=16384,max_evidence_bytes=16384))
    from prosaic_harness.context_packs.projection import validation_exposures
    from prosaic_harness import ExposureBindings
    frame=ContextPackInvocation.from_prepared('b'*32,candidates,pack,prepared,projection=projection,
        validation_bindings=validation_exposures(bindings,check_context).union(ExposureBindings.from_snapshot(candidates.snapshot)))
    return workflow,state,arguments,frame


def allocated(*,private_source=False):
    from prosaic_harness.context_packs.records import upgrade_pack_workflow,reserve_workflow_pack_attempt
    workflow,state,arguments,frame=workflow_case(private_source=private_source)
    state=upgrade_pack_workflow(state,workflow)
    state=reserve_workflow_pack_attempt(state,workflow,'build',arguments,frame)
    return workflow,state,arguments,frame


def test_workflow_v3_and_receipt_v2_are_a_closed_pair():
    from prosaic_harness.context_packs.records import make_workflow_pack_receipt,adopt_workflow_pack_receipt
    workflow,state,arguments,frame=allocated()
    validate_state(state,workflow)
    assert state['version']==3 and state['pending']['arguments']==arguments
    receipt=make_workflow_pack_receipt(state,workflow,result_case(frame),events=[])
    assert receipt['version']==2
    validate_receipt(receipt,state,state['pending'],workflow)
    final=adopt_workflow_pack_receipt(state,receipt,workflow)
    assert final['pending'] is None and final['invocations'][0]['status']=='complete'
    assert final['contextPacks']['attempts'][frame.invocation_id]['stage']=='adopted'
    validate_state(final,workflow)


def test_workflow_wrapper_cannot_be_downgraded_or_use_session_receipt():
    from prosaic_harness.context_packs.records import make_workflow_pack_receipt
    workflow,state,arguments,frame=allocated()
    receipt=make_workflow_pack_receipt(state,workflow,result_case(frame),events=[])
    for forged in (seal({**receipt,'version':1}),seal({**receipt,'contextPack':None}),
                   seal({**receipt,'recordType':'receipt'})):
        with pytest.raises(ValueError): validate_receipt(forged,state,state['pending'],workflow)


def test_workflow_frozen_private_facts_cannot_be_replaced_by_pending_arguments():
    workflow,state,arguments,frame=allocated()
    from prosaic_harness.workflow import digest as legacy_digest
    changed={**arguments,'request':{'task':'other'}}
    state['pending'].update(arguments=changed,arguments_sha256=legacy_digest(changed))
    state['invocations'][0]['arguments_sha256']=legacy_digest(changed)
    with pytest.raises(ValueError): validate_state(seal(state),workflow)


def test_workflow_receipt_cannot_claim_success_with_failed_evidence():
    from prosaic_harness.context_packs.records import make_workflow_pack_receipt
    workflow,state,arguments,frame=allocated()
    packet=make_workflow_pack_receipt(state,workflow,result_case(frame),events=[])
    packet['result'].update(exit_code=0,stdout='{}',stderr='')
    with pytest.raises(ValueError): validate_receipt(seal(packet),state,state['pending'],workflow)


def test_workflow_receipt_cannot_exceed_materialized_metadata_reservations():
    from prosaic_harness.context_packs.records import make_workflow_pack_receipt
    workflow,state,arguments,frame=allocated()
    packet=make_workflow_pack_receipt(state,workflow,result_case(frame),events=[])
    ceiling=state['contextPacks']['reservations'][frame.invocation_id]['metadataNodes']
    packet['result']['metadata']={'many':[0]*(ceiling+1)}
    with pytest.raises(ValueError): validate_receipt(seal(packet),state,state['pending'],workflow)


def test_saved_pack_attempt_cannot_drop_its_reservation():
    workflow,state,arguments,frame=allocated()
    state['contextPacks']['reservations'][frame.invocation_id]=None
    with pytest.raises(ValueError): validate_state(seal(state),workflow)


def test_restored_feedback_only_accepts_sealed_host_constants():
    workflow,state,arguments,frame=allocated()
    state['feedback']={'version':1,'policy':'safe-feedback-v1','code':'validationFailed',
        'count':1,'message':'PRIVATE FORGED DIAGNOSTIC'}
    with pytest.raises(ValueError): validate_state(seal(state),workflow)


def test_saved_validation_origins_cannot_omit_private_facts_after_resealing():
    from prosaic_harness import ExposureBindings
    from prosaic_harness.context_packs.records import _frozen_identity
    workflow,state,arguments,frame=allocated(private_source=True)
    value=state['contextPacks']['attempts'][frame.invocation_id]
    value['validationBindings']=ExposureBindings.from_snapshot(frame.candidates.snapshot).to_dict()
    value['frozenIdentity']=_frozen_identity(value)
    with pytest.raises(ValueError): validate_state(seal(state),workflow)
