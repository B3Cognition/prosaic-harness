"""Closed v2 context data and resource transitions; no counting or effects."""
from prosaic_runtime import (ContextPolicy, TokenCounterDescriptor,
    ContextSelection, ContextAssemblyReport, ContextWorkState)
from .session_codec import encode, digest, node_count, owned
from .conversation_errors import ConversationError
from .run_store import StoreCorrupt


ATTEMPT_FIELDS = frozenset({'contextSelection', 'initialContextReport',
    'finalContextReport', 'contextWork'})
RECEIPT_FIELDS = ATTEMPT_FIELDS | {'contextCounter'}


def context_reservation_bounds():
    # Object caps include their own JSON, but not the containing field framing.
    fields = {'ordinaryCounter': None, 'interpretationCounter': None,
        'contextSelection': None, 'initialContextReport': None,
        'finalContextReport': None, 'contextWork': None,
        'contextIdentity': 'f'*64, 'sourceHistoryDigest': 'f'*64,
        'selectedHistoryDigest': 'f'*64}
    return (2*16384 + 8192 + 2*16384 + 4096 + len(encode(fields)),
            2*512 + 256 + 2*512 + 128 + node_count(fields))


def receipt_context_bounds():
    fields = dict.fromkeys(RECEIPT_FIELDS)
    return (16384 + 8192 + 2*16384 + 4096 + len(encode(fields)),
            512 + 256 + 2*512 + 128 + node_count(fields))


def binding_context(bindings):
    material = bindings.readmit()
    return {purpose: ({'policy': material[policy], 'counter': material[counter]}
            if policy in material else None) for purpose, policy, counter in (
        ('ordinary', 'contextPolicy', 'contextCounter'),
        ('interpretation', 'interpretationContextPolicy', 'interpretationContextCounter'))}


def validate_context_bindings(document):
    if type(document) is not dict or document.keys() != {'ordinary', 'interpretation'}:
        raise ValueError('context binding fields')
    if not any(document.values()):
        raise ValueError('context opt-in absent')
    for purpose in document.values():
        if purpose is None: continue
        if type(purpose) is not dict or purpose.keys() != {'policy', 'counter'}:
            raise ValueError('context purpose fields')
        policy = ContextPolicy.from_dict(purpose['policy'])
        counter = TokenCounterDescriptor.from_dict(purpose['counter'])
        if (policy.counter_identity != counter.identity or
                policy.context_window_tokens > counter.context_capacity_tokens):
            raise ValueError('context policy descriptor')


def validate_work_transition(before, after):
    try:
        if type(before) is not ContextWorkState or type(after) is not ContextWorkState:
            raise ValueError('work records')
        old, new = before.to_dict(), after.to_dict()
        if new['checkpointSequence'] != old['checkpointSequence'] + 1:
            raise ValueError('checkpoint sequence')
        for key in ('candidateChecks', 'candidateBytes', 'activeAssemblyMicros'):
            if new[key] < old[key]: raise ValueError('work reset')
        if old['reservedActiveMicros']:
            # Completion may reconcile the reserved slice, never reset consumption.
            if (new['reservedActiveMicros'] != 0 or
                    new['candidateChecks'] != old['candidateChecks'] or
                    new['candidateBytes'] != old['candidateBytes']):
                raise ValueError('reservation completion')
        elif new['reservedActiveMicros'] == 0 and new != old:
            # A no-counter candidate may debit bytes/checks without an active slice.
            if new['candidateChecks'] != old['candidateChecks'] + 1:
                raise ValueError('unreserved work')
        if not old['readmissionPending'] and new['readmissionPending']:
            raise ValueError('readmission rewound')
        if old['readmissionPending'] and not new['readmissionPending'] and (
                new['candidateChecks'] != old['candidateChecks'] + 1):
            raise ValueError('unpaid readmission')
        return after
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ConversationError('bindingMismatch') from None


def validate_attempt_context(state, attempt):
    purpose = state['contextBindings'][attempt['purpose']]
    if purpose is None:
        if attempt['encodingVersion'] != 'conversation-turn-v1' or any(attempt[key] is not None for key in ATTEMPT_FIELDS):
            raise ValueError('legacy purpose context')
        return
    if attempt['encodingVersion'] != 'conversation-turn-v2':
        raise ValueError('context encoding')
    policy = ContextPolicy.from_dict(purpose['policy'])
    selection = ContextSelection.from_dict(attempt['contextSelection'])
    report = ContextAssemblyReport.from_dict(attempt['initialContextReport'])
    work = ContextWorkState.from_dict(attempt['contextWork'])
    from .session_contracts import history_of
    history = history_of(state, before_sequence=attempt['turnSequence'])
    starts = [i for i, message in enumerate(history) if message['role'] == 'user']
    if report.omitted_turn_count > len(starts): raise ValueError('omission count')
    index = starts[report.omitted_turn_count] if report.omitted_turn_count < len(starts) else len(history)
    selected = history[index:]
    expected = {'version': 1, 'contextPolicyIdentity': digest(purpose['policy']),
        'counterDescriptorIdentity': digest(purpose['counter']),
        'sourceHistoryDigest': digest(history), 'selectedHistoryDigest': digest(selected),
        'retainedRange': report.retained_range, 'omittedRange': report.omitted_range,
        'initialReportIdentity': digest(report.to_dict())}
    if (selection.to_dict() != expected or report.source_history_digest != digest(history)
            or report.selected_history_digest != digest(selected)
            or report.retained_turn_count + report.omitted_turn_count != len(starts)
            or report.mode != policy.mode or report.counter_identity != policy.counter_identity
            or report.counting_kind != purpose['counter']['countingKind']
            or report.input_capacity_tokens != policy.input_capacity_tokens
            or report.reserved_output_tokens != policy.reserved_output_tokens
            or report.safety_margin_tokens != policy.safety_margin_tokens
            or report.encoded_input_bytes != attempt['inputBytes']
            or work.candidate_checks < report.candidate_checks
            or work.candidate_bytes < report.candidate_bytes
            or work.candidate_checks > policy.max_candidate_checks
            or work.candidate_bytes > policy.max_assembly_bytes
            or work.reserved_active_micros > policy.assembly_timeout_ms * 1000):
        raise ValueError('context attempt correlation')
    if attempt['finalContextReport'] is not None:
        validate_final_report(report, attempt['finalContextReport'], work)
    elif attempt['receiptAdopted']:
        raise ValueError('final report absent')


def validate_final_report(initial, final, work):
    final = ContextAssemblyReport.from_dict(final)
    static = initial.to_dict()
    static.update(candidateChecks=final.candidate_checks, candidateBytes=final.candidate_bytes)
    if (final.to_dict() != static or final.candidate_checks != work.candidate_checks
            or final.candidate_bytes != work.candidate_bytes
            or final.candidate_checks < initial.candidate_checks
            or final.candidate_bytes < initial.candidate_bytes):
        raise ValueError('final context correlation')


def checkpoint_context_work(document, invocation_id, work):
    from .session_contracts import verify_session, _consume_headroom
    state = verify_session(document)
    if (state['version'] != 2 or state['pending'] is None or
            state['pending']['invocationId'] != invocation_id):
        raise ConversationError('messageConflict')
    before_bytes, before_nodes = len(encode(state)), node_count(state)
    attempt = state['attempts'][invocation_id]
    validate_work_transition(ContextWorkState.from_dict(attempt['contextWork']), work)
    attempt['contextWork'] = work.to_dict()
    return verify_session(_consume_headroom(state, before_bytes, before_nodes))


def validate_receipt_context(value):
    if value['contextSelection'] is None:
        if value['encodingVersion'] != 'conversation-turn-v1' or any(value[key] is not None for key in RECEIPT_FIELDS):
            raise ValueError('legacy receipt context')
        return
    if value['encodingVersion'] != 'conversation-turn-v2': raise ValueError('context receipt encoding')
    selection = ContextSelection.from_dict(value['contextSelection'])
    initial = ContextAssemblyReport.from_dict(value['initialContextReport'])
    counter = TokenCounterDescriptor.from_dict(value['contextCounter'])
    work = ContextWorkState.from_dict(value['contextWork'])
    if (selection.initial_report_identity != digest(initial.to_dict())
            or selection.counter_descriptor_identity != digest(counter.to_dict())):
        raise ValueError('receipt descriptor correlation')
    validate_final_report(initial, value['finalContextReport'], work)


def match_context_receipt(state, attempt, value):
    if state['version'] != value['version']: raise ValueError('receipt record version')
    for key in ('contextSelection', 'initialContextReport'):
        if value[key] != attempt[key]: raise ValueError('receipt selection changed')
    purpose = state['contextBindings'][attempt['purpose']]
    if value['contextCounter'] != (purpose['counter'] if purpose else None):
        raise ValueError('receipt counter changed')
    if purpose is not None:
        work = ContextWorkState.from_dict(value['contextWork'])
        previous = ContextWorkState.from_dict(attempt['contextWork'])
        if work.to_dict() != previous.to_dict():
            validate_work_transition(previous, work)
    if not attempt['dispatchMarker']:
        evidence = value['evidence']
        if (purpose is None or value['result']['exitCode'] == 0
                or value['result']['failureCode'] not in {'contextLimit', 'bindingMismatch', 'cancelled', 'timeout'}
                or evidence['providerAttempts'] or evidence['toolAttempts'] or evidence['toolOutcomes']):
            raise ValueError('undispatched receipt claims effects')
