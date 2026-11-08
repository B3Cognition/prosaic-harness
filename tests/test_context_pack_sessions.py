"""V3 wrappers preserve the ordinary session reducer and frozen pack bindings."""
import pytest
from prosaic_harness import StoreCorrupt
from prosaic_harness.session_contracts import (verify_session,verify_receipt,seal,
    mark_dispatch,make_receipt,adopt_receipt,validate_session_transition)
from support.conversations import session_document,binding_factory,scope
from test_context_pack_records import invocation_case,result_case


def allocated(session_document,*,counted=False):
    from prosaic_harness.context_packs.records import upgrade_pack_session,reserve_pack_attempt
    frame=invocation_case(counted=counted)
    state=upgrade_pack_session(session_document(),frame.candidates.snapshot.scope_binding,'d'*64)
    state=reserve_pack_attempt(state,frame,message_id='message')
    return state,frame


def test_v3_session_and_receipt_pair_preserve_exact_frozen_input(session_document):
    state,frame=allocated(session_document)
    assert state['version']==3 and verify_session(state)==state
    packet=make_receipt(state,frame.invocation_id,result_case(frame))
    assert packet['version']==3 and verify_receipt(packet)==packet
    assert packet['contextPack']['frozenInput']==frame.frozen_input.to_dict()
    final=adopt_receipt(state,packet)
    assert final['pending'] is None and final['turns'][0]['status']=='failed'
    assert final['contextPacks']['attempts'][frame.invocation_id]['stage']=='adopted'
    assert adopt_receipt(final,packet)==final
    assert validate_session_transition(state,final)==final


def test_v3_receipts_cannot_be_downgraded_or_rebound(session_document):
    state,frame=allocated(session_document)
    packet=make_receipt(state,frame.invocation_id,result_case(frame))
    for forged in (seal({**packet,'version':2}),seal({**packet,'contextPack':None}),
                   seal({**packet,'contextPack':{**packet['contextPack'],'invocationId':'e'*32}})):
        with pytest.raises(StoreCorrupt): adopt_receipt(state,forged)


def test_v3_dispatch_is_bound_to_the_pack_frame(session_document):
    state,frame=allocated(session_document)
    with pytest.raises((StoreCorrupt,ValueError)):
        make_receipt(state,frame.invocation_id,result_case(frame,providers=1,failure='providerFailure'))
    dispatched=mark_dispatch(state,frame.invocation_id)
    assert dispatched['contextPacks']['attempts'][frame.invocation_id]['stage']=='dispatched'
    packet=make_receipt(dispatched,frame.invocation_id,result_case(frame,providers=1,failure='providerFailure'))
    assert adopt_receipt(dispatched,packet)['providerRequests']==1


def test_v3_sealed_tampering_cannot_replace_current_message(session_document):
    state,frame=allocated(session_document)
    forged=seal({**state,'turns':[{**state['turns'][0],'message':'other'}]})
    with pytest.raises(StoreCorrupt): verify_session(forged)


def test_pack_free_purpose_uses_nullable_v3_extension(session_document):
    from prosaic_harness.context_packs.records import reserve_pack_attempt
    state,frame=allocated(session_document)
    state=adopt_receipt(state,make_receipt(state,frame.invocation_id,result_case(frame)))
    from prosaic_harness.session_contracts import reserve_attempt
    state=reserve_attempt(state,message_id='plain',message='Hello',invocation_id='c'*32,
        context_identity='f'*64,encoding_version='conversation-turn-v1',input_bytes=10,
        provider_allowance=2,tool_allowance=0)
    assert state['contextPacks']['attempts']['c'*32] is None
    import prosaic_runtime as api
    evidence=api.TurnEvidence.from_dict(dict(version=1,providerAttempts=1,toolAttempts=0,
        knownUsage={},usageComplete=True,toolOutcomes=[],failureCode='providerFailure',accounting=None))
    packet=make_receipt(mark_dispatch(state,'c'*32),'c'*32,api.TurnResult(api.Result(1,'','failed'),None,evidence))
    assert packet['version']==3 and packet['contextPack'] is None


def test_pack_session_receipt_work_cannot_erase_unknown_reservation(session_document):
    from prosaic_harness.session_context import checkpoint_context_work
    import prosaic_runtime as api
    state,frame=allocated(session_document)
    # Byte-only records cannot acquire a context-work ledger after admission.
    work=api.ContextWorkState.from_dict(dict(version=1,candidateChecks=1,candidateBytes=10,
        activeAssemblyMicros=1,reservedActiveMicros=10,readmissionCandidateBytes=10,
        readmissionPending=True,checkpointSequence=1))
    with pytest.raises((StoreCorrupt,ValueError)):
        checkpoint_context_work(state,frame.invocation_id,work)


def test_pack_retry_requires_explicit_new_epoch(session_document):
    from prosaic_harness.context_packs.records import reserve_pack_attempt
    state,frame=allocated(session_document)
    state=mark_dispatch(state,frame.invocation_id)
    value=frame.to_dict();value['invocationId']='c'*32
    from prosaic_harness.context_packs.records import ContextPackInvocation
    duplicate=ContextPackInvocation.from_dict(value)
    with pytest.raises(ValueError): reserve_pack_attempt(state,duplicate,message_id='message',retry=True)


def test_acknowledged_unknown_attempt_gets_separate_epoch(session_document):
    from prosaic_harness.context_packs.records import reserve_pack_attempt,ContextPackInvocation,_frozen_identity
    state,frame=allocated(session_document);state=mark_dispatch(state,frame.invocation_id)
    value=frame.to_dict();value['invocationId']='c'*32
    value['frozenInput']['executionAttempt']=2;value['executionEpoch']=2
    value['frozenIdentity']=_frozen_identity(value)
    fresh=ContextPackInvocation.from_dict(value)
    with pytest.raises(ValueError): reserve_pack_attempt(state,fresh,message_id='message',retry=True)
    retried=reserve_pack_attempt(state,fresh,message_id='message',retry=True,acknowledge_unknown=True)
    assert len(retried['attempts'])==2
    assert retried['contextPacks']['attempts'][frame.invocation_id]['executionEpoch']==1
    assert retried['contextPacks']['attempts'][fresh.invocation_id]['executionEpoch']==2


def test_counted_pack_session_checkpoints_owned_work(binding_factory,scope):
    from prosaic_harness.session_contracts import new_session
    from prosaic_harness.context_packs.records import upgrade_pack_session,reserve_pack_attempt
    from prosaic_harness.session_context import checkpoint_context_work
    from support.context_counter import fixture_context
    import prosaic_runtime as api
    policy,counters=fixture_context(count=lambda request:10)
    binding=binding_factory(context_policy=policy,token_counters=counters)
    frame=invocation_case(counted=True)
    state=upgrade_pack_session(new_session('a'*32,scope,binding),frame.candidates.snapshot.scope_binding,'d'*64)
    state=reserve_pack_attempt(state,frame,message_id='message')
    before=frame.context_work.to_dict()
    work=api.ContextWorkState.from_dict({**before,'checkpointSequence':before['checkpointSequence']+1,
        'reservedActiveMicros':2000000-before['activeAssemblyMicros']})
    changed=checkpoint_context_work(state,frame.invocation_id,work)
    assert changed['contextPacks']['attempts'][frame.invocation_id]['contextWork']==work.to_dict()
    assert validate_session_transition(state,changed)==changed
