from dataclasses import replace
import json
import pytest
from prosaic_runtime import ConversationMessage, CompletedTurn, TurnEvidence, TurnResult, Result
from prosaic_harness import ConversationError, ConversationPolicy, StoreCorrupt
from prosaic_harness.session_contracts import (new_session, reserve_attempt, mark_dispatch,
    adopt_receipt, make_receipt, verify_session, seal)
from support.conversations import binding_factory, scope


SID='a'*32
AID='b'*32


@pytest.fixture
def state(scope,binding_factory):
    return new_session(SID,scope,binding_factory())


def reserve(state, **changes):
    values=dict(message_id='message',message='Hello',invocation_id=AID,
        context_identity='1'*64,encoding_version='conversation-turn-v1',input_bytes=500,
        provider_allowance=2,tool_allowance=0)
    return reserve_attempt(state,**(values|changes))


def receipt(state, *, failure=None, uncertain=False):
    completed=None if failure else CompletedTurn.from_dict({'version':1,'messages':[
        {'role':'user','turnStatus':'completed','content':[{'type':'text','text':'Hello'}]},
        {'role':'assistant','content':[{'type':'text','text':'Done'}]}]})
    evidence=TurnEvidence.from_dict({'version':1,'providerAttempts':1,'toolAttempts':0,
        'knownUsage':{'totalTokens':5},'usageComplete':not uncertain,'toolOutcomes':[],
        'failureCode':failure,'accounting':None})
    result=TurnResult(Result(1 if failure else 0,'' if failure else 'Done',failure or ''),completed,evidence)
    return make_receipt(state,AID,result)


def test_reservation_precedes_dispatch_and_is_owned(state):
    pending=reserve(state)
    assert state['turns']==[] and pending['turns'][0]['status']=='pending'
    assert pending['reservedReceiptBytes']==state['policy']['maxReceiptBytes']
    assert pending['reservedProviderRequests']==2
    assert pending['attempts'][AID]['dispatchMarker'] is False
    running=mark_dispatch(pending,AID)
    assert running['turns'][0]['status']=='running'
    assert pending['attempts'][AID]['dispatchMarker'] is False


def test_adoption_replaces_reserved_bytes_once(state):
    running=mark_dispatch(reserve(state),AID)
    saved=receipt(running)
    adopted=adopt_receipt(running,saved)
    assert adopted['reservedReceiptBytes']==0
    assert adopted['retainedReceiptBytes']==len(json.dumps(saved,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
    assert adopted['providerRequests']==1 and adopted['reservedProviderRequests']==0
    assert adopted['turns'][0]['answer']=='Done'
    assert adopt_receipt(adopted,saved)==adopted


def test_failed_correction_retains_only_complete_user_record(state):
    running=mark_dispatch(reserve(state),AID)
    adopted=adopt_receipt(running,receipt(running,failure='providerFailure',uncertain=True))
    assert adopted['turns'][0]['status']=='failed'
    assert adopted['turns'][0]['history']==[{'role':'user','turnStatus':'failed',
        'failureCode':'providerFailure','content':[{'type':'text','text':'Hello'}]}]


@pytest.mark.parametrize('field,value',[('max_turns',1),('max_attempts',1),
    ('max_provider_requests',1),('max_total_receipt_bytes',1024),
    ('max_history_bytes',1024),('max_state_bytes',4096)])
def test_capacity_admission_fails_before_reserving(scope,binding_factory,field,value):
    policy=replace(ConversationPolicy(),**{field:value})
    binding=binding_factory(policy=policy)
    state=new_session(SID,scope,binding)
    if field in {'max_turns','max_attempts'}:
        running=mark_dispatch(reserve(state),AID)
        state=adopt_receipt(running,receipt(running))
    with pytest.raises(ConversationError,match='sessionLimit'):
        reserve(state,message_id='next',invocation_id='c'*32)


def test_receipt_adoption_is_allowed_at_capacity(scope,binding_factory):
    binding=binding_factory(policy=replace(ConversationPolicy(),max_attempts=1,max_turns=1))
    state=mark_dispatch(reserve(new_session(SID,scope,binding)),AID)
    assert adopt_receipt(state,receipt(state))['turns'][0]['status']=='completed'


def test_interpretation_adoption_consumes_only_materialized_headroom(state):
    running=mark_dispatch(reserve(state,purpose='interpretation'),AID)
    running['policy']['maxStateBytes']=len(encode_for_test(running))+running['reservedStateBytes']
    running=seal(running)
    # The policy number changes the encoding length; settle its exact bound.
    running['policy']['maxStateBytes']=len(encode_for_test(running))+running['reservedStateBytes']
    running=seal(running)
    before=verify_session(running)
    adopted=adopt_receipt(before,receipt(before),finalize=False)
    assert adopted['pending'] is not None and adopted['reservedStateBytes']>0
    assert len(encode_for_test(adopted))+adopted['reservedStateBytes']<=adopted['policy']['maxStateBytes']


def encode_for_test(value):
    from prosaic_harness.session_codec import encode
    return encode(value)


def test_hash_does_not_admit_malformed_record(state):
    hostile=seal(state|{'turns':[{'forged':True}]})
    with pytest.raises(StoreCorrupt):
        verify_session(hostile)


def test_canonical_utf8_and_alias_work_bounds(state):
    from prosaic_harness.session_codec import encode
    assert encode({'text':'ž'})==b'{"text":"\xc5\xbe"}'
    aliases=[{'text':'a'}]*1000
    with pytest.raises(ValueError):
        encode(aliases,nodes=100)
    cycle=[]
    cycle.append(cycle)
    with pytest.raises(ValueError):
        encode(cycle)


@pytest.mark.parametrize('field',['sessionId','invocationId','contextIdentity','bindingIdentity','encodingVersion'])
def test_matching_receipt_identity_is_required(state,field):
    running=mark_dispatch(reserve(state),AID)
    saved=receipt(running)
    saved[field]='d'*32 if field.endswith('Id') else 'different'
    with pytest.raises(StoreCorrupt):
        adopt_receipt(running,seal(saved))


def test_receipt_cannot_persist_a_turn_larger_than_reserved_turn_cap(state):
    from prosaic_harness.session_contracts import match_receipt
    running=mark_dispatch(reserve(state),AID)
    saved=receipt(running)
    saved['completedTurn']['messages'][-1]['content'][0]['text']='x'*200000
    with pytest.raises(StoreCorrupt): match_receipt(running,seal(saved))


def test_attempt_slots_are_counted_even_with_zero_dispatches(state):
    running=mark_dispatch(reserve(state),AID)
    saved=receipt(running,failure='cancelled')
    saved['evidence']['providerAttempts']=0
    saved['evidence']['knownUsage']={}
    adopted=adopt_receipt(running,seal(saved))
    assert len(adopted['attempts'])==1 and adopted['providerRequests']==0
    assert adopted['retainedReceiptBytes']>0


@pytest.mark.parametrize('change',['deleteAttempt','rewriteInput','rewindMarker','rewindReceipt'])
def test_transition_cannot_rewrite_admitted_effect_addresses(state,change):
    from prosaic_harness.session_contracts import validate_session_transition
    pending=reserve(state)
    running=mark_dispatch(pending,AID)
    done=adopt_receipt(running,receipt(running))
    if change=='deleteAttempt': old,new=running,state
    elif change=='rewriteInput':
        old,new=pending,seal(pending)
        new['turns'][0]['message']='changed'
        new=seal(new)
    elif change=='rewindMarker': old,new=running,pending
    else: old,new=done,running
    with pytest.raises(StoreCorrupt): validate_session_transition(old,new)


def test_transition_accepts_reservation_dispatch_and_once_adoption(state):
    from prosaic_harness.session_contracts import validate_session_transition
    pending=reserve(state)
    running=mark_dispatch(pending,AID)
    done=adopt_receipt(running,receipt(running))
    for old,new in ((state,pending),(pending,running),(running,done),(done,done)):
        assert validate_session_transition(old,new)==new


def test_accounting_cannot_change_session_owner(state):
    from prosaic_runtime import ExecutionContext
    accounting=ExecutionContext(application_id='other',tenant_id='tenant',
        actor_id='actor',billing_account_id='payer',run_id=SID).resolve().to_dict()
    with pytest.raises(StoreCorrupt): verify_session(seal(state|{'accounting':accounting}))
