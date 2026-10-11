"""Closed version-1 session reducer. No callbacks, I/O or model execution."""
from dataclasses import fields
import hashlib
import re

from prosaic_runtime import (ConversationMessage, CompletedTurn, TurnEvidence, TurnResult)
from .conversation_bindings import ConversationScope, ConversationPolicy, ConversationBindings
from .conversation_errors import ConversationError
from .run_store import StoreCorrupt, validate_id
from .session_codec import encode, decode, owned, digest, reference, node_count

_HASH = re.compile('[0-9a-f]{64}')
_FAILURES = frozenset({'providerFailure','invalidToolRequest','cancelled','timeout','contextLimit',
    'inputLimit','outputLimit','budgetExceeded','accountingFailure','observationFailure',
    'toolEffectUncertain','toolJournalFailure','toolFailure','incompleteGeneration',
    'bindingMismatch','interrupted','invalidInterpretation','confirmationRequired','interactionStale'})
_UNCERTAIN = frozenset({'toolEffectUncertain', 'toolJournalFailure', 'interrupted'})


def camel(name):
    first,*rest=name.split('_')
    return first+''.join(part.title() for part in rest)


_POLICY_FIELDS={camel(f.name): f.name for f in fields(ConversationPolicy)}


def policy_document(policy):
    return {camel(k):v for k,v in policy.to_dict().items()}


def policy_from(document):
    closed(document,_POLICY_FIELDS)
    return ConversationPolicy(**{name:document[key] for key,name in _POLICY_FIELDS.items()})


def closed(value, required, optional=()):
    if type(value) is not dict or set(value)-set(required)-set(optional) or not set(required)<=set(value):
        raise ValueError('record fields')


def integer(value, minimum=0, maximum=2**63-1):
    if type(value) is not int or not minimum<=value<=maximum:
        raise ValueError('integer bounds')


def hash_value(value):
    if type(value) is not str or not _HASH.fullmatch(value):
        raise ValueError('identity hash')


def scope_from(value):
    closed(value,{'namespace','environment','application','tenant','actor','billingAccount'})
    return ConversationScope(value['namespace'],value['environment'],value['application'],
        value['tenant'],value['actor'],value['billingAccount'])


def seal(value):
    data=owned({k:v for k,v in value.items() if k!='sha256'})
    return data|{'sha256':digest(data)}


def verify_seal(value):
    if type(value) is not dict:
        raise ValueError('record type')
    hash_value(value.get('sha256'))
    if digest({k:v for k,v in value.items() if k!='sha256'})!=value['sha256']:
        raise ValueError('record seal')


def history_of(state, *, before_sequence=None):
    return [item for turn in state['turns'] if before_sequence is None or turn['sequence']<before_sequence
            for item in turn['history']]


def _counters(state):
    attempts=list(state['attempts'].values())
    return {'providerRequests':sum(a['providerAttempts'] for a in attempts),
        'toolCalls':sum(a['toolAttempts'] for a in attempts),
        'reservedProviderRequests':sum(a['providerReservation'] for a in attempts),
        'reservedToolCalls':sum(a['toolReservation'] for a in attempts),
        'retainedReceiptBytes':sum(a['receiptBytes'] for a in attempts),
        'reservedReceiptBytes':sum(a['receiptReservation'] for a in attempts),
        'historyBytes':len(encode(history_of(state))),
        'reservedHistoryBytes':sum(t['historyReservation'] for t in state['turns']),
        'reservedStateBytes':sum(t['stateReservation'] for t in state['turns']),
        'reservedStateNodes':sum(t['stateNodeReservation'] for t in state['turns'])}


def _with_counters(state):
    return seal(state|_counters(state))


def public_node_limit(policy):
    return (policy['maxJsonNodes']-8192)//8


def _consume_headroom(state, before_bytes, before_nodes):
    current=_with_counters(state)
    turn=state['turns'][-1]
    if turn['stateReservation']:
        turn['stateReservation']=max(0,turn['stateReservation']-max(0,len(encode(current))-before_bytes))
        turn['stateNodeReservation']=max(0,turn['stateNodeReservation']-max(0,node_count(current)-before_nodes))
    return _with_counters(state)


def _bounds(state, *, admission=False):
    p=state['policy']
    checks={'maxTurns':len(state['turns']), 'maxAttempts':len(state['attempts']),
        'maxHistoryBytes':state['historyBytes']+state['reservedHistoryBytes'],
        'maxStateBytes':len(encode(state))+state['reservedStateBytes'],
        'maxTotalReceiptBytes':state['retainedReceiptBytes']+state['reservedReceiptBytes'],
        'maxProviderRequests':state['providerRequests']+state['reservedProviderRequests'],
        'maxToolCalls':state['toolCalls']+state['reservedToolCalls'],
        'maxJsonNodes':node_count(state)+state['reservedStateNodes']}
    for key,size in checks.items():
        if size>p[key]:
            if admission:
                raise ConversationError('sessionLimit',key)
            raise ValueError('session capacity')
    if any(len(t['attempts'])>p['maxAttemptsPerTurn'] for t in state['turns']):
        if admission: raise ConversationError('sessionLimit','maxAttemptsPerTurn')
        raise ValueError('attempt capacity')


def verify_session(document):
    try:
        state=owned(document)
        closed(state,{'version','recordType','sessionId','scope','bindingIdentity','bindingVersion','policy',
            'accounting','accountingScope','turns','attempts','pending','workflow','sha256',*_counters_empty()})
        verify_seal(state)
        if type(state['version']) is not int or state['version']!=1 or state['recordType']!='session':
            raise ValueError('record version')
        validate_id(state['sessionId'])
        scope_from(state['scope'])
        hash_value(state['bindingIdentity'])
        reference(state['bindingVersion'])
        policy_from(state['policy'])
        encode(state, maximum=state['policy']['maxStateBytes'],
               depth=state['policy']['maxJsonDepth'], nodes=state['policy']['maxJsonNodes'])
        if state['accounting'] is not None:
            from prosaic_runtime import ResolvedContext
            attribution=ResolvedContext.from_dict(state['accounting'])
            owner=state['scope']
            if (attribution.application_id,attribution.tenant_id,attribution.actor_id,
                    attribution.billing_account_id,attribution.run_id)!=(
                    owner['application'],owner['tenant'],owner['actor'],owner['billingAccount'],state['sessionId']):
                raise ValueError('accounting owner')
        if state['accountingScope'] is not None:
            closed(state['accountingScope'],{'namespace','environment'})
            for value in state['accountingScope'].values(): reference(value)
            if state['accounting'] is None: raise ValueError('accounting scope absent')
        if type(state['turns']) is not list or type(state['attempts']) is not dict:
            raise ValueError('turn ledger')
        ids=set()
        allocated=[]
        for sequence,turn in enumerate(state['turns'],1):
            closed(turn,{'sequence','messageId','message','requestIdentity','interactionRef','status','answer',
                'failureCode','history','attempts','inputData','historyIdentity','historyReservation',
                'stateReservation','stateNodeReservation','pendingInteraction','recoveryStatus'})
            integer(turn['sequence'],1)
            if turn['sequence']!=sequence or turn['messageId'] in ids:
                raise ValueError('turn sequence')
            reference(turn['messageId'])
            ids.add(turn['messageId'])
            if type(turn['message']) is not str or not turn['message'] or len(turn['message'].encode())>state['policy']['maxUserBytes']:
                raise ValueError('turn input')
            if turn['interactionRef'] is not None: reference(turn['interactionRef'])
            hash_value(turn['requestIdentity'])
            hash_value(turn['historyIdentity'])
            if turn['status'] not in {'pending','running','completed','failed','needsResolution'}:
                raise ValueError('turn status')
            if turn['failureCode'] is not None and turn['failureCode'] not in _FAILURES:
                raise ValueError('failure code')
            if turn['answer'] is not None and (type(turn['answer']) is not str or
                    len(turn['answer'].encode())>state['policy']['maxAssistantBytes']):
                raise ValueError('answer bounds')
            if type(turn['history']) is not list or type(turn['attempts']) is not list:
                raise ValueError('turn history')
            if turn['history']:
                encode(turn['history'], maximum=state['policy']['maxTurnBytes'])
                if turn['status']=='completed':
                    CompletedTurn.from_dict({'version':1,'messages':turn['history']})
                else:
                    if len(turn['history'])!=1 or turn['history'][0].get('turnStatus')!='failed':
                        raise ValueError('failed history')
                    ConversationMessage.from_dict(turn['history'][0])
                if turn['history'][0]['content']!=[{'type':'text','text':turn['message']}]:
                    raise ValueError('history source')
            elif turn['status'] in {'completed','failed'}:
                raise ValueError('terminal history absent')
            for name in ('historyReservation','stateReservation','stateNodeReservation'): integer(turn[name])
            if turn['status'] in {'completed','failed'} and (turn['historyReservation'] or turn['stateReservation'] or turn['stateNodeReservation']):
                raise ValueError('terminal reservation')
            if turn['recoveryStatus'] not in {None,'needsResolution','pending','workflowCommand'}:
                raise ValueError('recovery status')
            if turn['pendingInteraction'] is not None and type(turn['pendingInteraction']) is not dict:
                raise ValueError('interaction shape')
            allocated.extend(turn['attempts'])
        if len(allocated)!=len(set(allocated)) or set(allocated)!=set(state['attempts']):
            raise ValueError('attempt addresses')
        for aid,attempt in state['attempts'].items():
            validate_id(aid)
            closed(attempt,{'invocationId','turnSequence','purpose','contextIdentity','encodingVersion','inputBytes',
                'context','dispatchMarker','receiptAdopted','effectUncertain','receiptIdentity','receiptBytes','receiptReservation',
                'providerAllowance','toolAllowance','providerAttempts','toolAttempts',
                'providerReservation','toolReservation'})
            if attempt['invocationId']!=aid or attempt['purpose'] not in {'ordinary','interpretation'}:
                raise ValueError('attempt identity')
            integer(attempt['turnSequence'],1,len(state['turns']))
            if aid not in state['turns'][attempt['turnSequence']-1]['attempts']:
                raise ValueError('attempt source')
            hash_value(attempt['contextIdentity'])
            if attempt['encodingVersion']!='conversation-turn-v1': raise ValueError('encoding contract')
            integer(attempt['inputBytes'],1,state['policy']['maxInputBytes'])
            if any(type(attempt[k]) is not bool for k in ('dispatchMarker','receiptAdopted','effectUncertain')):
                raise ValueError('attempt marker')
            if attempt['context'] is not None:
                from prosaic_runtime import ResolvedContext
                context=ResolvedContext.from_dict(attempt['context'])
                base=state['accounting']
                if base is None or context.to_dict()!=ResolvedContext.from_dict(base).child(
                        invocation_id=aid,run_id=state['sessionId'],
                        step_id='turn.'+str(attempt['turnSequence'])+'.'+attempt['purpose']).to_dict():
                    raise ValueError('accounting attempt')
            elif state['accounting'] is not None: raise ValueError('accounting absent')
            for key in ('receiptBytes','receiptReservation','providerAllowance','toolAllowance',
                        'providerAttempts','toolAttempts','providerReservation','toolReservation'):
                integer(attempt[key])
            if attempt['providerAttempts']+attempt['providerReservation']>attempt['providerAllowance'] or (
                    attempt['toolAttempts']+attempt['toolReservation']>attempt['toolAllowance']):
                raise ValueError('allowance ledger')
            if attempt['receiptAdopted']:
                hash_value(attempt['receiptIdentity'])
                if not attempt['dispatchMarker'] or attempt['receiptBytes']==0 or attempt['receiptReservation']:
                    raise ValueError('receipt adoption')
            elif (attempt['receiptIdentity'] is not None or attempt['receiptBytes'] or
                  attempt['receiptReservation']!=state['policy']['maxReceiptBytes'] or
                  attempt['providerAttempts'] or attempt['toolAttempts']):
                raise ValueError('pending receipt reservation')
        pending=state['pending']
        if pending is not None:
            closed(pending,{'phase','turnSequence','invocationId','command'})
            if pending['phase'] not in {'modelInvocation','workflowCommand'}:
                raise ValueError('pending phase')
            integer(pending['turnSequence'],1,len(state['turns']))
            if pending['turnSequence']!=len(state['turns']): raise ValueError('pending order')
            if pending['phase']=='modelInvocation':
                if pending['invocationId'] not in state['attempts'] or pending['command'] is not None:
                    raise ValueError('pending attempt')
            elif type(pending['command']) is not dict: raise ValueError('workflow command')
        elif any(t['status'] in {'pending','running','needsResolution'} for t in state['turns']):
            raise ValueError('unresolved turn')
        if state['workflow'] is not None:
            closed(state['workflow'],{'registration','runId'})
            reference(state['workflow']['registration'])
            validate_id(state['workflow']['runId'])
        for key,value in _counters(state).items():
            integer(state[key])
            if state[key]!=value: raise ValueError('counter mismatch')
        _bounds(state)
        return state
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,RecursionError):
        raise StoreCorrupt('invalid conversation snapshot') from None


def _counters_empty():
    return ('providerRequests','toolCalls','reservedProviderRequests','reservedToolCalls',
        'retainedReceiptBytes','reservedReceiptBytes','historyBytes','reservedHistoryBytes','reservedStateBytes','reservedStateNodes')


def encode_session(state):
    return encode(verify_session(state))


def decode_session(content):
    try: return verify_session(decode(content))
    except (ValueError,TypeError,UnicodeError): raise StoreCorrupt('invalid conversation snapshot') from None


def validate_session_transition(previous, proposed):
    """Validate monotonic storage advancement, independently of a record hash."""
    old,new=verify_session(previous),verify_session(proposed)
    immutable=('version','recordType','sessionId','scope','bindingIdentity','bindingVersion','policy','accounting','accountingScope')
    turn_input=('sequence','messageId','message','requestIdentity','interactionRef','inputData','historyIdentity')
    attempt_input=('invocationId','turnSequence','purpose','contextIdentity','encodingVersion','inputBytes',
                   'context','providerAllowance','toolAllowance')
    try:
        if any(old[k]!=new[k] for k in immutable): raise ValueError('session identity changed')
        if len(new['turns'])<len(old['turns']) or not set(old['attempts'])<=set(new['attempts']):
            raise ValueError('ledger removed')
        for before,after in zip(old['turns'],new['turns']):
            if any(before[k]!=after[k] for k in turn_input) or (
                    after['attempts'][:len(before['attempts'])]!=before['attempts']):
                raise ValueError('turn input changed')
            if before['status'] in {'completed','failed'} and before!=after:
                raise ValueError('terminal turn changed')
        for aid,before in old['attempts'].items():
            after=new['attempts'][aid]
            if any(before[k]!=after[k] for k in attempt_input): raise ValueError('attempt input changed')
            if before['dispatchMarker'] and not after['dispatchMarker']: raise ValueError('marker rewound')
            if before['receiptAdopted'] and (not after['receiptAdopted'] or any(before[k]!=after[k]
                    for k in ('receiptIdentity','receiptBytes','providerAttempts','toolAttempts','effectUncertain'))):
                raise ValueError('receipt rewound')
        return new
    except (ValueError,KeyError,TypeError):
        raise StoreCorrupt('invalid conversation advancement') from None


def new_session(session_id, scope, bindings, *, accounting=None, accounting_scope=None):
    validate_id(session_id)
    if type(scope) is not ConversationScope or type(bindings) is not ConversationBindings:
        raise ConversationError('bindingMismatch')
    bindings.readmit()
    state=seal({'version':1,'recordType':'session','sessionId':session_id,'scope':scope.to_dict(),
        'bindingIdentity':bindings.identity,'bindingVersion':bindings.version,
        'policy':policy_document(bindings.policy),'accounting':accounting,'accountingScope':accounting_scope,
        'turns':[],'attempts':{},'pending':None,'workflow':None,
        **dict.fromkeys(_counters_empty(),0)})
    state=_with_counters(state)
    _bounds(state,admission=True)
    return verify_session(state)


def reserve_attempt(document, *, message_id, message, invocation_id, context_identity,
                    encoding_version, input_bytes, provider_allowance, tool_allowance,
                    input_data=None, interaction_ref=None, purpose='ordinary', context=None,
                    retry=False):
    state=verify_session(document)
    p=state['policy']
    validate_id(invocation_id)
    reference(message_id)
    hash_value(context_identity)
    if invocation_id in state['attempts']: raise ConversationError('messageConflict')
    if type(message) is not str or not message or len(message.encode())>p['maxUserBytes']:
        raise ConversationError('invalidMessage')
    for count in (provider_allowance,tool_allowance): integer(count)
    if interaction_ref is not None: reference(interaction_ref)
    if retry:
        if state['pending'] is None or not state['turns']: raise ConversationError('messageConflict')
        turn=state['turns'][-1]
        if turn['messageId']!=message_id or turn['message']!=message:
            raise ConversationError('messageConflict')
        turn['status']='pending'
        turn['history']=[]
        turn['answer']=None
        turn['failureCode']=None
        turn['recoveryStatus']=None
        turn['historyReservation']=p['maxTurnBytes']
        turn['stateReservation']=p['maxTurnBytes']+p['maxPublicBytes']+8192
        turn['stateNodeReservation']=(p['maxJsonNodes']-8192)//2+2*public_node_limit(p)+8192
    else:
        if state['pending'] is not None: raise ConversationError('messageConflict')
        if any(t['messageId']==message_id for t in state['turns']): raise ConversationError('messageConflict')
        turn={'sequence':len(state['turns'])+1,'messageId':message_id,'message':message,
            'requestIdentity':digest({'message':message,'interactionRef':interaction_ref,'workflow':state['workflow']}),
            'interactionRef':interaction_ref,'status':'pending','answer':None,'failureCode':None,
            'history':[],'attempts':[],'inputData':owned(input_data),
            'historyIdentity':digest(history_of(state)),'historyReservation':p['maxTurnBytes'],
            'stateReservation':p['maxTurnBytes']+p['maxPublicBytes']+8192,
            'stateNodeReservation':(p['maxJsonNodes']-8192)//2+2*public_node_limit(p)+8192,
            'pendingInteraction':None,'recoveryStatus':None}
        state['turns'].append(turn)
    attempt={'invocationId':invocation_id,'turnSequence':turn['sequence'],'purpose':purpose,
        'contextIdentity':context_identity,'encodingVersion':encoding_version,'inputBytes':input_bytes,
        'context':owned(context),'dispatchMarker':False,'receiptAdopted':False,'effectUncertain':False,'receiptIdentity':None,
        'receiptBytes':0,'receiptReservation':p['maxReceiptBytes'],
        'providerAllowance':provider_allowance,'toolAllowance':tool_allowance,
        'providerAttempts':0,'toolAttempts':0,'providerReservation':provider_allowance,'toolReservation':tool_allowance}
    turn['attempts'].append(invocation_id)
    state['attempts'][invocation_id]=attempt
    state['pending']={'phase':'modelInvocation','turnSequence':turn['sequence'],'invocationId':invocation_id,'command':None}
    state=_with_counters(state)
    _bounds(state,admission=True)
    return verify_session(state)


def mark_dispatch(document, invocation_id):
    state=verify_session(document)
    if state['pending'] is None or state['pending']['invocationId']!=invocation_id:
        raise ConversationError('messageConflict')
    state['attempts'][invocation_id]['dispatchMarker']=True
    state['turns'][-1]['status']='running'
    return verify_session(_with_counters(state))


def mark_interrupted(document):
    state=verify_session(document)
    if state['pending'] is None: return state
    before_bytes,before_nodes=len(encode(state)),node_count(state)
    turn=state['turns'][-1]
    turn['status']='needsResolution'
    turn['failureCode']='interrupted'
    turn['answer']=None
    turn['history']=[{'role':'user','content':[{'type':'text','text':turn['message']}],
                     'turnStatus':'failed','failureCode':'interrupted'}]
    turn['historyReservation']=max(0,state['policy']['maxTurnBytes']-len(encode(turn['history'])))
    turn['recoveryStatus']='needsResolution'
    return verify_session(_consume_headroom(state,before_bytes,before_nodes))


def verify_receipt(document):
    try:
        value=owned(document)
        closed(value,{'version','recordType','sessionId','scope','bindingIdentity','invocationId','turnSequence',
            'contextIdentity','encodingVersion','context','result','completedTurn','evidence','sha256'})
        verify_seal(value)
        if type(value['version']) is not int or value['version']!=1 or value['recordType']!='receipt':
            raise ValueError('receipt version')
        for name in ('sessionId','invocationId'): validate_id(value[name])
        for name in ('bindingIdentity','contextIdentity'): hash_value(value[name])
        scope_from(value['scope'])
        integer(value['turnSequence'],1)
        if value['encodingVersion']!='conversation-turn-v1': raise ValueError('encoding version')
        result=value['result']
        closed(result,{'exitCode','answer','failureCode','timedOut'})
        integer(result['exitCode'],0,2**31-1)
        if type(result['timedOut']) is not bool or type(result['answer']) is not str:
            raise ValueError('result types')
        if result['failureCode'] is not None and result['failureCode'] not in _FAILURES:
            raise ValueError('failure code')
        if result['exitCode']==0:
            CompletedTurn.from_dict(value['completedTurn'])
            if result['failureCode'] is not None: raise ValueError('successful failure')
        elif value['completedTurn'] is not None or result['answer'] or result['failureCode'] is None:
            raise ValueError('failed partial result')
        TurnEvidence.from_dict(value['evidence'])
        if value['evidence']['failureCode']!=result['failureCode']:
            raise ValueError('evidence result mismatch')
        return value
    except (ValueError,TypeError,KeyError,UnicodeError,AttributeError,RecursionError):
        raise StoreCorrupt('invalid conversation receipt') from None


def match_receipt(state, receipt):
    value=verify_receipt(receipt)
    try:
        attempt=state['attempts'][value['invocationId']]
        for key in ('sessionId','scope','bindingIdentity'):
            if state[key]!=value[key]: raise ValueError('receipt scope')
        for key in ('turnSequence','contextIdentity','encodingVersion','context'):
            if attempt[key]!=value[key]: raise ValueError('receipt correlation')
        if not attempt['dispatchMarker']: raise ValueError('missing dispatch marker')
        evidence=value['evidence']
        if evidence['providerAttempts']>attempt['providerAllowance'] or evidence['toolAttempts']>attempt['toolAllowance']:
            raise ValueError('unallocated dispatch')
        if value['context'] is not None and (type(evidence['accounting']) is not dict or
                evidence['accounting'].get('context')!=value['context']):
            raise ValueError('accounting correlation')
        if state['accountingScope'] is not None and any(evidence['accounting'].get(k)!=v
                for k,v in state['accountingScope'].items()): raise ValueError('accounting destination')
        if value['completedTurn'] is not None:
            turn=state['turns'][value['turnSequence']-1]
            encode(value['completedTurn'], maximum=state['policy']['maxTurnBytes'])
            if value['completedTurn']['messages'][0]['content']!=[{'type':'text','text':turn['message']}]:
                raise ValueError('receipt source')
        if len(value['result']['answer'].encode())>state['policy']['maxAssistantBytes']:
            raise ValueError('answer capacity')
        if len(encode(value,depth=state['policy']['maxJsonDepth'],
                      nodes=state['policy']['maxJsonNodes']))>state['policy']['maxReceiptBytes']:
            raise ValueError('receipt capacity')
        return value
    except (ValueError,TypeError,KeyError):
        raise StoreCorrupt('conversation receipt does not match allocated attempt') from None


def make_receipt(document, invocation_id, result):
    state=verify_session(document)
    if type(result) is not TurnResult: raise StoreCorrupt('invalid Runtime turn result')
    attempt=state['attempts'][invocation_id]
    evidence=result.evidence.to_dict()
    packet=seal({'version':1,'recordType':'receipt','sessionId':state['sessionId'],'scope':state['scope'],
        'bindingIdentity':state['bindingIdentity'],'invocationId':invocation_id,'turnSequence':attempt['turnSequence'],
        'contextIdentity':attempt['contextIdentity'],'encodingVersion':attempt['encodingVersion'],'context':attempt['context'],
        'result':{'exitCode':result.result.exit_code,'answer':result.result.stdout if result.result.exit_code==0 else '',
                  'failureCode':evidence['failureCode'],'timedOut':result.result.timed_out},
        'completedTurn':result.completed_turn.to_dict() if result.completed_turn is not None else None,
        'evidence':evidence})
    return match_receipt(state,packet)


def adopt_receipt(document, receipt, *, finalize=True):
    state=verify_session(document)
    before_bytes,before_nodes=len(encode(state)),node_count(state)
    value=match_receipt(state,receipt)
    attempt=state['attempts'][value['invocationId']]
    if attempt['receiptAdopted']:
        if attempt['receiptIdentity']!=value['sha256']: raise StoreCorrupt('conflicting adopted receipt')
        return state
    if state['pending'] is None or state['pending']['invocationId']!=value['invocationId']:
        raise StoreCorrupt('receipt is not current')
    attempt['receiptAdopted']=True
    attempt['receiptIdentity']=value['sha256']
    attempt['receiptBytes']=len(encode(value))
    attempt['receiptReservation']=0
    evidence=value['evidence']
    attempt['providerAttempts']=evidence['providerAttempts']
    attempt['toolAttempts']=evidence['toolAttempts']
    effect_uncertain=(value['result']['failureCode'] in {'toolEffectUncertain','toolJournalFailure'} or
                      any(o['status']=='uncertain' for o in evidence['toolOutcomes']))
    attempt['effectUncertain']=effect_uncertain
    uncertain=(value['result']['failureCode'] in _UNCERTAIN or effect_uncertain or any(
        a['effectUncertain'] or (a['dispatchMarker'] and not a['receiptAdopted'] and a['toolAllowance']>0)
        for a in state['attempts'].values() if a['turnSequence']==attempt['turnSequence']))
    attempt['providerReservation']=attempt['providerAllowance']-attempt['providerAttempts'] if uncertain else 0
    attempt['toolReservation']=attempt['toolAllowance']-attempt['toolAttempts'] if uncertain else 0
    turn=state['turns'][value['turnSequence']-1]
    if finalize:
        code=value['result']['failureCode'] or ('interrupted' if uncertain else None)
        turn['failureCode']=code
        turn['answer']=value['result']['answer'] if code is None else None
        turn['status']='needsResolution' if uncertain else 'completed' if code is None else 'failed'
        turn['history']=(value['completedTurn']['messages'] if code is None else [
            {'role':'user','content':[{'type':'text','text':turn['message']}],
             'turnStatus':'failed','failureCode':code}])
        if not uncertain:
            turn['historyReservation']=turn['stateReservation']=turn['stateNodeReservation']=0
            state['pending']=None
        else:
            # History has been materialized, so retain only unused headroom.
            turn['historyReservation']=max(0,state['policy']['maxTurnBytes']-len(encode(turn['history'])))
            turn['recoveryStatus']='needsResolution'
    return verify_session(_consume_headroom(state,before_bytes,before_nodes))


def freeze_workflow_command(document, command):
    state=verify_session(document)
    before_bytes,before_nodes=len(encode(state)),node_count(state)
    if state['pending'] is None or state['pending']['phase']!='modelInvocation':
        raise ConversationError('messageConflict')
    attempt=state['attempts'][state['pending']['invocationId']]
    if attempt['purpose']!='interpretation' or not attempt['receiptAdopted']:
        raise ConversationError('invalidInterpretation')
    bounded=owned(command,maximum=state['policy']['maxPublicBytes'],
                  depth=state['policy']['maxJsonDepth']-8,nodes=public_node_limit(state['policy']))
    if type(bounded) is not dict: raise ConversationError('invalidInterpretation')
    state['pending']={'phase':'workflowCommand','turnSequence':attempt['turnSequence'],
                      'invocationId':attempt['invocationId'],'command':bounded}
    state['turns'][-1]['recoveryStatus']='workflowCommand'
    return verify_session(_consume_headroom(state,before_bytes,before_nodes))
