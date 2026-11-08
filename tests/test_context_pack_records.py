"""Data-only reconstruction never reruns composition or native fitting."""
import pytest
from prosaic_harness import ContextPacker,ContextPackCandidates,ContextPackError
from support.context_pack_cases import required_optional_case


def invocation_case(*,counted=False,validation_bindings=None):
    import prosaic_runtime as api
    from prosaic_harness.context_packs.codec import digest
    from prosaic_harness.context_packs.records import ContextPackInvocation
    spec,snapshot=required_optional_case();packer=ContextPacker();candidates=packer.compose(spec,snapshot)
    index=len(candidates.variants)-1
    pack=packer.select(candidates,index,digest(candidates.variants[index]))
    runtime=api.ProsaicRuntime(api.RuntimeConfig({'local':api.EndpointConfig('http://127.0.0.1:9/v1','synthetic',features={'streaming':False})},{},'local',frozenset()))
    options={}
    if counted:
        from support.context_counter import fixture_context
        policy,counters=fixture_context(count=lambda request:10)
        options=dict(context_policy=policy,token_counters=counters)
    prepared=runtime.prepare_turn(api.ProsaicArtifact('approved','subagent',{},'ALWAYS use supplied evidence. NEVER invent facts.'),message='Exact current message',
        input_data={'contextPack':pack.envelope},input_profile='context-pack-input-v1',
        policy=api.RunPolicy(max_provider_requests=1,max_tool_calls=0),
        limits=api.TurnLimits(max_metadata_bytes=8192,max_evidence_bytes=8192),**options)
    return ContextPackInvocation.from_prepared('b'*32,candidates,pack,prepared,runtime_input_mapping=[index],validation_bindings=validation_bindings)


def test_saved_candidate_plan_restores_without_recomposition(monkeypatch):
    spec,snapshot=required_optional_case()
    candidates=ContextPacker().compose(spec,snapshot)
    record=candidates.to_dict()
    def forbidden(*a,**k): pytest.fail('durable restoration recomposed candidates')
    monkeypatch.setattr(ContextPacker,'compose',forbidden)
    restored=ContextPackCandidates.from_dict(record)
    assert restored.candidate_identity==candidates.candidate_identity
    assert restored.to_dict()==record


def test_saved_candidate_plan_refuses_forged_projection_and_required_base():
    spec,snapshot=required_optional_case();candidates=ContextPacker().compose(spec,snapshot)
    forged=candidates.to_dict();forged['variants'][0]['items'][0]['content']='forged'
    with pytest.raises(ContextPackError): ContextPackCandidates.from_dict(forged)
    forged=candidates.to_dict();forged['variants'][-1]=forged['variants'][0];forged['reports'][-1]=forged['reports'][0]
    with pytest.raises(ContextPackError): ContextPackCandidates.from_dict(forged)


def test_byte_only_mapping_keeps_runtime_zero_distinct_from_original_pack_index():
    frame=invocation_case()
    assert frame.runtime_input_mapping==[1]
    assert frame.frozen_input.to_dict()['inputVariantSelection']['selectedIndex']==0
    assert frame.prepared_pack.reference['selectedVariantIndex']==1
    assert frame.frozen_input.to_dict()['selectedInputData']['contextPack']==frame.prepared_pack.envelope


def test_invocation_record_is_owned_closed_and_restores_without_composition(monkeypatch):
    from prosaic_harness.context_packs.records import ContextPackInvocation
    frame=invocation_case();value=frame.to_dict()
    def forbidden(*a,**k): pytest.fail('restoration optimized the candidate plan')
    monkeypatch.setattr(ContextPacker,'compose',forbidden)
    restored=ContextPackInvocation.from_dict(value)
    assert restored.frozen_identity==frame.frozen_identity
    value['candidatePlan']['variants'][0]['items'].clear()
    assert restored.to_dict()==frame.to_dict()
    with pytest.raises(ContextPackError): ContextPackInvocation.from_dict(frame.to_dict()|{'foreign':True})


@pytest.mark.parametrize('field',['message','locator','profile','mapping'])
def test_invocation_tampering_cannot_rebind_saved_inputs(field):
    from prosaic_harness.context_packs.records import ContextPackInvocation
    value=invocation_case().to_dict()
    if field=='message': value['frozenInput']['message']='different'
    elif field=='locator': value['candidatePlan']['snapshot']['items'][0]['locator']={'kind':'record','id':'foreign'}
    elif field=='profile': value['frozenInput']['inputProfile']='foreign-profile'
    else: value['runtimeInputMapping']=[0]
    with pytest.raises(ContextPackError): ContextPackInvocation.from_dict(value)


def test_work_checkpoints_do_not_change_frozen_selection_or_allow_resets():
    import prosaic_runtime as api
    frame=invocation_case(counted=True)
    before=frame.context_work.to_dict()
    reserved=api.ContextWorkState.from_dict({**before,'checkpointSequence':before['checkpointSequence']+1,'reservedActiveMicros':2000000-before['activeAssemblyMicros']})
    updated=frame.checkpoint(reserved)
    assert updated.frozen_identity==frame.frozen_identity
    assert updated.context_work.to_dict()==reserved.to_dict()
    with pytest.raises(ContextPackError): updated.checkpoint(frame.context_work)


def result_case(frame,*,providers=0,failure='contextLimit'):
    import prosaic_runtime as api
    evidence=api.TurnEvidence.from_dict(dict(version=2,providerAttempts=providers,toolAttempts=0,
        knownUsage={},usageComplete=True,toolOutcomes=[],failureCode=failure,accounting=None,
        inputViews=frame.frozen_input.to_dict()['inputViews']))
    report=frame.frozen_input.to_dict()['contextReport']
    if report is not None:
        report=api.ContextAssemblyReport.from_dict({**report,'candidateChecks':frame.context_work.candidate_checks,'candidateBytes':frame.context_work.candidate_bytes})
    return api.TurnResult(api.Result(1,'',failure),None,evidence,context_report=report,context_work=frame.context_work)


def test_completed_record_binds_evidence_and_adoption_is_idempotent():
    from prosaic_harness.context_packs.codec import digest
    frame=invocation_case();result=result_case(frame)
    completed=frame.complete(result)
    assert completed.stage=='completed' and completed.result_evidence_digest==digest(result.evidence.to_dict())
    assert completed.frozen_identity==frame.frozen_identity
    adopted=completed.adopt('a'*64)
    assert adopted.stage=='adopted' and adopted.adopt('a'*64).to_dict()==adopted.to_dict()
    with pytest.raises(ContextPackError): adopted.adopt('c'*64)


def test_any_provider_effect_requires_durable_dispatch_marker():
    frame=invocation_case();result=result_case(frame,providers=1,failure='providerFailure')
    with pytest.raises(ContextPackError): frame.complete(result)
    dispatched=frame.mark_dispatched()
    assert dispatched.stage=='dispatched'
    assert dispatched.complete(result).stage=='completed'


def test_validation_use_cannot_drop_a_captured_source():
    from prosaic_harness.context_packs.authorization import ExposureBindings
    from support.context_pack_cases import scope_case
    # This frame has no private guard facts, but any separately supplied
    # validation binding must still cover the captured source snapshot.
    with pytest.raises(ContextPackError): invocation_case(validation_bindings=ExposureBindings(scope_case(),[]))


def test_outstanding_unknown_work_needs_an_acknowledged_completion_checkpoint():
    import prosaic_runtime as api
    from dataclasses import replace
    frame=invocation_case(counted=True)
    before=frame.context_work.to_dict()
    reserved=api.ContextWorkState.from_dict({**before,'checkpointSequence':before['checkpointSequence']+1,
        'reservedActiveMicros':2000000-before['activeAssemblyMicros']})
    outstanding=frame.checkpoint(reserved)
    released=api.ContextWorkState.from_dict({**before,'checkpointSequence':reserved.checkpoint_sequence+1,
        'activeAssemblyMicros':before['activeAssemblyMicros']+1})
    with pytest.raises(ContextPackError): outstanding.complete(replace(result_case(outstanding),context_work=released))
    acknowledged=outstanding.checkpoint(released)
    assert acknowledged.complete(result_case(acknowledged)).stage=='completed'


def test_workflow_frame_keeps_full_controller_context_and_separate_model_root():
    import prosaic_runtime as api
    from prosaic_harness.context_packs.records import ContextPackInvocation
    from prosaic_harness.context_packs.sources import capture_sources
    from prosaic_harness.context_packs.projection import project_step
    from prosaic_harness.context_packs.codec import digest
    from test_context_pack_sources import source_case,evidence_case
    from test_context_pack_projection import context_case
    spec,arguments,binding=source_case();packer=ContextPacker()
    candidates=packer.compose(spec,capture_sources(spec,arguments,evidence_case(),binding))
    projection=project_step('review',arguments,candidates,controller_validation_context=context_case(arguments))
    pack=packer.select(candidates,0,digest(candidates.variants[0]))
    runtime=api.ProsaicRuntime(api.RuntimeConfig({'local':api.EndpointConfig('http://127.0.0.1:9/v1','synthetic',features={'streaming':False})},{},'local',frozenset()))
    prepared=runtime.prepare_turn(api.ProsaicArtifact('approved','subagent',{},'Review declared evidence.'),message='Return the declared result',
        input_data=projection.variants[0],input_profile=projection.profile,
        authoritative_input_data=projection.authoritative_input_data,authoritative_input_profile=projection.authoritative_input_profile,
        policy=api.RunPolicy(max_provider_requests=1,max_tool_calls=0))
    frame=ContextPackInvocation.from_prepared('c'*32,candidates,pack,prepared,projection=projection)
    restored=ContextPackInvocation.from_dict(frame.to_dict())
    assert restored.projection['controllerValidationContext']['artifacts']['other']=={'private':'GLOBAL-517'}
    assert 'UNSELECTED-419' not in str(restored.frozen_input.to_dict()['selectedInputData'])
    assert 'UNSELECTED-419' in str(restored.frozen_input.to_dict()['authoritativeInputData'])
