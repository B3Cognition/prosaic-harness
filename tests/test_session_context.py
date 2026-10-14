"""V2 seals context selection, bounded resource reservations and safe receipts."""
from dataclasses import replace
import pytest
import prosaic_runtime as api
from prosaic_harness import ConversationError, StoreCorrupt, ConversationPolicy
from prosaic_harness.session_contracts import (new_session, reserve_attempt,
    verify_session, verify_receipt, mark_dispatch, make_receipt, adopt_receipt,
    validate_session_transition, seal, history_of)
from support.conversations import binding_factory, scope, session_document
from support.context_counter import fixture_context

SID, AID = 'a'*32, 'b'*32


def allocated(binding_factory, scope, *, purpose='ordinary', storage_policy=None, prepared=None):
    policy, counters = fixture_context(count=lambda request: 10)
    binding = binding_factory(context_policy=policy, token_counters=counters,
        **({'policy': storage_policy} if storage_policy is not None else {}))
    state = new_session(SID, scope, binding)
    if prepared is None:
        prepared = binding.runtime().prepare_turn(binding.agent, message='Hello',
            policy=binding.run_policy, limits=binding.turn_limits,
            context_policy=policy, token_counters=counters)
    state = reserve_attempt(state, message_id='message', message='Hello', invocation_id=AID,
        context_identity=prepared.context_identity, encoding_version=prepared.encoding_version,
        input_bytes=prepared.input_bytes, provider_allowance=2, tool_allowance=0,
        purpose=purpose, context_selection=prepared.context_selection,
        context_report=prepared.context_report, context_work=prepared.context_work)
    return binding, state, prepared


def failed(prepared, code='contextLimit'):
    evidence = api.TurnEvidence.from_dict({'version': 1, 'providerAttempts': 0,
        'toolAttempts': 0, 'knownUsage': {}, 'usageComplete': True,
        'toolOutcomes': [], 'failureCode': code, 'accounting': None})
    return api.TurnResult(api.Result(1, '', code), None, evidence,
        context_report=prepared.context_report, context_work=prepared.context_work)


def test_legacy_session_seal_is_unchanged(session_document):
    state = session_document()
    assert state['version'] == 1
    assert state['sha256'] == '766bddfa0d98c9fbe7077dc346bc0943f7769c0d02a9abf61a79b7fb291bb2f6'
    from test_session_contracts import reserve, receipt
    packet = receipt(mark_dispatch(reserve(state), AID))
    assert packet['sha256'] == 'f7e65f2cd1eac77256e425e8d2a81dfaea961b86b74a74a53a7ddbcdeb22e4bf'


def test_v2_admits_source_and_selection_without_changing_history(binding_factory, scope):
    _, state, prepared = allocated(binding_factory, scope)
    assert state['version'] == 2
    assert state['contextBindings']['ordinary']['policy']['counterIdentity'] == 'synthetic-byte-v1'
    attempt = state['attempts'][AID]
    assert attempt['contextSelection'] == prepared.context_selection.to_dict()
    assert attempt['initialContextReport'] == prepared.context_report.to_dict()
    assert attempt['contextWork'] == prepared.context_work.to_dict()
    assert history_of(state) == []
    assert verify_session(state) == state


def test_context_work_cannot_be_reset():
    from prosaic_harness.session_context import validate_work_transition
    before = api.ContextWorkState.from_dict({'version': 1, 'candidateChecks': 2,
        'candidateBytes': 300, 'activeAssemblyMicros': 10,
        'reservedActiveMicros': 0, 'readmissionCandidateBytes': 150,
        'readmissionPending': True, 'checkpointSequence': 2})
    for change in ({'candidateChecks': 0}, {'candidateBytes': 0},
                   {'activeAssemblyMicros': 0}, {'checkpointSequence': 2}):
        after = api.ContextWorkState.from_dict({**before.to_dict(), 'checkpointSequence': 3, **change})
        with pytest.raises(ConversationError):
            validate_work_transition(before, after)


def test_checkpoints_preserve_context_identity_and_charge_before_counter(binding_factory, scope):
    from prosaic_harness.session_context import checkpoint_context_work
    _, state, prepared = allocated(binding_factory, scope)
    before = prepared.context_work.to_dict()
    after = api.ContextWorkState.from_dict({**before,
        'reservedActiveMicros': 2_000_000 - before['activeAssemblyMicros'],
        'checkpointSequence': 1})
    changed = checkpoint_context_work(state, AID, after)
    assert changed['attempts'][AID]['contextIdentity'] == state['attempts'][AID]['contextIdentity']
    assert changed['attempts'][AID]['contextWork'] == after.to_dict()
    assert validate_session_transition(state, changed) == changed
    forged = seal({**changed, 'attempts': {AID: {**changed['attempts'][AID], 'contextWork': before}}})
    with pytest.raises(StoreCorrupt):
        validate_session_transition(changed, forged)


@pytest.mark.parametrize('field', ['contextSelection', 'initialContextReport'])
def test_frozen_context_material_cannot_drift(binding_factory, scope, field):
    _, state, _ = allocated(binding_factory, scope)
    attempt = state['attempts'][AID]
    forged = seal({**state, 'attempts': {AID: {**attempt, field:
        {**attempt[field], 'sourceHistoryDigest': 'f'*64}}}})
    with pytest.raises(StoreCorrupt):
        verify_session(forged)


def test_zero_effect_readmission_failure_has_adoptable_receipt_without_marker(binding_factory, scope):
    _, state, prepared = allocated(binding_factory, scope)
    packet = make_receipt(state, AID, failed(prepared))
    assert packet['version'] == 2
    assert packet['finalContextReport']['inputTokens'] == 10
    final = adopt_receipt(state, packet)
    assert final['turns'][0]['status'] == 'failed'
    assert final['attempts'][AID]['dispatchMarker'] is False
    assert final['pending'] is None
    assert final['providerRequests'] == final['toolCalls'] == 0


def test_predispatch_receipt_cannot_claim_provider_effect(binding_factory, scope):
    _, state, prepared = allocated(binding_factory, scope)
    result = failed(prepared)
    evidence = api.TurnEvidence.from_dict({**result.evidence.to_dict(), 'providerAttempts': 1,
        'usageComplete': False})
    result = replace(result, evidence=evidence)
    with pytest.raises(StoreCorrupt):
        make_receipt(state, AID, result)


def test_v1_cannot_be_upgraded_by_sealing_new_fields(session_document, binding_factory, scope):
    old = session_document()
    _, new, _ = allocated(binding_factory, scope)
    with pytest.raises(StoreCorrupt):
        validate_session_transition(old, new)
    with pytest.raises(StoreCorrupt):
        verify_session(seal({**old, 'contextBindings': new['contextBindings']}))


def test_v2_interpreter_only_session_keeps_ordinary_legacy_encoding(binding_factory, scope):
    policy, counters = fixture_context(count=lambda request: 10)
    interpreter = api.ProsaicArtifact('interpreter', 'subagent',
        {'name': 'interpreter', 'description': 'Synthetic interpreter'},
        'ALWAYS interpret current choices. NEVER authorize effects.')
    binding = binding_factory(interpreter=interpreter,
        interpretation_context_policy=policy, token_counters=counters)
    state = new_session(SID, scope, binding)
    prepared = binding.runtime().prepare_turn(binding.agent, message='Hello',
        policy=binding.run_policy, limits=binding.turn_limits)
    assert prepared.encoding_version == 'conversation-turn-v1'
    state = reserve_attempt(state, message_id='ordinary', message='Hello', invocation_id=AID,
        context_identity=prepared.context_identity, encoding_version=prepared.encoding_version,
        input_bytes=prepared.input_bytes, provider_allowance=2, tool_allowance=0)
    assert state['version'] == 2
    assert state['attempts'][AID]['contextSelection'] is None
    state = mark_dispatch(state, AID)
    packet = make_receipt(state, AID, failed(prepared, 'providerFailure'))
    assert packet['version'] == 2
    assert packet['encodingVersion'] == 'conversation-turn-v1'
    assert adopt_receipt(state, packet)['turns'][0]['status'] == 'failed'


def test_final_receipt_cannot_replace_frozen_initial_report(binding_factory, scope):
    _, state, prepared = allocated(binding_factory, scope)
    packet = make_receipt(state, AID, failed(prepared))
    forged = seal({**packet, 'initialContextReport': {
        **packet['initialContextReport'], 'inputTokens': 11}})
    with pytest.raises(StoreCorrupt):
        verify_receipt(forged)


def test_checkpoint_cannot_release_reservation_while_adding_unpaid_work():
    from prosaic_harness.session_context import validate_work_transition
    before = api.ContextWorkState.from_dict({'version': 1, 'candidateChecks': 2,
        'candidateBytes': 300, 'activeAssemblyMicros': 10,
        'reservedActiveMicros': 1000, 'readmissionCandidateBytes': 0,
        'readmissionPending': False, 'checkpointSequence': 2})
    after = api.ContextWorkState.from_dict({**before.to_dict(),
        'candidateChecks': 3, 'reservedActiveMicros': 0, 'checkpointSequence': 3})
    with pytest.raises(ConversationError):
        validate_work_transition(before, after)


def test_context_capacity_reservation_covers_enclosing_material():
    from prosaic_harness.session_context import context_reservation_bounds, receipt_context_bounds
    state_bytes, state_nodes = context_reservation_bounds()
    receipt_bytes, receipt_nodes = receipt_context_bounds()
    assert state_bytes > 2*16384 + 8192 + 2*16384 + 4096
    assert state_nodes > 2*512 + 256 + 2*512 + 128
    assert receipt_bytes > 16384 + 8192 + 2*16384 + 4096
    assert receipt_nodes > 512 + 256 + 2*512 + 128


def test_insufficient_state_capacity_rejects_before_attempt(binding_factory, scope):
    from prosaic_harness.session_codec import encode
    from prosaic_harness.session_contracts import policy_document
    _, generous, prepared = allocated(binding_factory, scope)
    needed = len(encode(generous)) + generous['reservedStateBytes']
    # Changing maxStateBytes can change its own encoded digit count. Reuse the
    # same prepared resource snapshot and calibrate with a same-width limit.
    _, calibrated, _ = allocated(binding_factory, scope, prepared=prepared,
        storage_policy=replace(ConversationPolicy(), max_state_bytes=needed + 1024))
    exact = len(encode(calibrated)) + calibrated['reservedStateBytes']
    allocated(binding_factory, scope, prepared=prepared,
        storage_policy=replace(ConversationPolicy(), max_state_bytes=exact))
    policy = replace(ConversationPolicy(), max_state_bytes=exact - 1)
    with pytest.raises(ConversationError) as caught:
        allocated(binding_factory, scope, storage_policy=policy, prepared=prepared)
    assert caught.value.code == 'sessionLimit'


def test_context_node_reservation_rejects_small_session_before_effect(binding_factory, scope):
    with pytest.raises(ConversationError) as caught:
        allocated(binding_factory, scope,
            storage_policy=replace(ConversationPolicy(), max_json_nodes=10_000))
    assert caught.value.code == 'sessionLimit'
    assert caught.value.limit == 'maxJsonNodes'


def test_receipt_headroom_reserves_failure_context_material(binding_factory):
    policy, counters = fixture_context(count=lambda request: 10)
    storage_policy = replace(ConversationPolicy(), max_receipt_bytes=300_000)
    # The same storage policy is large enough for legacy failure evidence.
    binding_factory(policy=storage_policy)
    with pytest.raises(ConversationError) as caught:
        binding_factory(policy=storage_policy, context_policy=policy, token_counters=counters)
    assert caught.value.code == 'sessionLimit'
    assert caught.value.limit == 'maxReceiptBytes'
