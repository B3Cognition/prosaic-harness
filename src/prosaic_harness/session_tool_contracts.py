"""Explicit conversation tool authority; legacy sessions never enter this codec."""
from dataclasses import asdict,dataclass,replace
from uuid import uuid4
import hashlib

from prosaic_runtime import (InvocationScope,FrozenTurnInput,TurnEvidence,CitationsV1,
    EvidenceDraftV1,HostEvidenceImportV1,EvidenceAuthorizerV1)
from .session_codec import encode,decode,digest,owned
from .conversation_errors import ConversationError


def has_packs(state):
    return state.get('version') in (3,4,5) and type(state.get('contextPacks')) is dict


def scope_for(state,aid,purpose='ordinary',namespace=None):
    return InvocationScope(aid,run_id=state['sessionId'],step_id='turn.'+str(
        state['attempts'][aid]['turnSequence'] if aid in state['attempts'] else len(state['turns'])+1)+'.'+purpose,
        operation_namespace=namespace)


def upgrade_session(state,bindings):
    from .session_context import binding_context
    result=state|dict(version=4,contextBindings=binding_context(bindings),contextPacks=None,
        toolContractV1=dict(version=1,bindings=bindings.readmit()['toolContractV1'],attempts={}))
    if bindings.run_policy.parallel_tools is not None:result.update(version=5,parallelToolsV1=bindings.readmit()['parallelToolsV1'])
    return result


def reserve_contract(state,attempt,frozen,frame,refs):
    if attempt['purpose']!='ordinary':
        if frozen is not None or refs: raise ValueError('interpretation cannot import evidence')
        value=None
    else:
        frozen=frame.frozen_input.to_dict() if frame else FrozenTurnInput.from_dict(frozen).to_dict()
        value=dict(version=1,frozenInput=None if frame else frozen,retainedReferences=list(refs))
        # The input is already retained once. Reserve bounded evidence growth,
        # including complete call outcomes, independently of public view limits.
        turn=state['turns'][-1]
        room=state['toolContractV1']['bindings']['reservations']['receiptBytes']
        turn['stateReservation']+=room
        # Evidence remains in the bounded receipt; session history nodes are
        # already covered by the turn reservation.
    state['toolContractV1']['attempts'][attempt['invocationId']]=value


def attempt_frozen(state,aid):
    side=state['toolContractV1']['attempts'][aid]
    if side is None:return None
    return side['frozenInput'] if side['frozenInput'] is not None else state['contextPacks']['attempts'][aid]['frozenInput']


def validate_refs(refs):
    if type(refs) is not list or len(refs)>16: raise ValueError('retained reference capacity')
    for ref in refs:
        if type(ref) is not dict or set(ref)!={'version','sessionId','invocationId','receiptSha256','evidenceId','scope'} or type(ref['version']) is not int or ref['version']!=1:
            raise ValueError('invalid retained reference')
        from .run_store import validate_id
        from .session_contracts import hash_value,scope_from
        validate_id(ref['sessionId']);validate_id(ref['invocationId']);hash_value(ref['receiptSha256']);scope_from(ref['scope'])
        import re
        if type(ref['evidenceId']) is not str or not re.fullmatch(r'(?:ev|ctx)_[0-9a-f]{64}',ref['evidenceId']):raise ValueError('invalid retained ID')
    if len({encode(ref) for ref in refs})!=len(refs):raise ValueError('duplicate retained reference')


def validate_state(state):
    side=state['toolContractV1']
    if type(side) is not dict or set(side)!={'version','bindings','attempts'} or side['version']!=1:
        raise ValueError('invalid session tool contract')
    if set(side['attempts'])!=set(state['attempts']):raise ValueError('tool attempt ledger mismatch')
    from .session_contracts import history_of
    for aid,attempt in state['attempts'].items():
        record=side['attempts'][aid]
        if attempt['purpose']!='ordinary':
            if record is not None:raise ValueError('interpretation authority')
            continue
        if type(record) is not dict or set(record)!={'version','frozenInput','retainedReferences'} or record['version']!=1:
            raise ValueError('invalid tool attempt')
        validate_refs(record['retainedReferences'])
        frozen=FrozenTurnInput.from_dict(attempt_frozen(state,aid)).to_dict()
        if state['version']==5 and frozen['bindings'].get('parallelToolsV1')!=state['parallelToolsV1']:raise ValueError('parallel frozen binding drift')
        binding=frozen['bindings']['toolContractV1'];scope=binding['scope']
        expected=asdict(scope_for(state,aid,namespace=scope['operation_namespace']))
        turn=state['turns'][attempt['turnSequence']-1]
        if (frozen['encodingVersion']!=('conversation-turn-v5' if state['version']==5 else 'conversation-turn-v4') or scope!=expected or
                any(frozen[key]!=attempt[key] for key in ('contextIdentity','encodingVersion','inputBytes')) or
                frozen['message']!=turn['message'] or frozen['sourceHistoryDigest']!=digest(
                    history_of(state,before_sequence=turn['sequence']))):
            raise ValueError('tool frozen input mismatch')
        # Wrapped pack/retention grants change only the authorizer identity.
        declared=side['bindings']['bindings']
        for key in ('identity','version','bindingVersion','displayAuthorizer','citations','limits'):
            if binding[key]!=declared[key]:raise ValueError('tool declaration mismatch')


def validate_transition(old,new):
    before,after=old['toolContractV1'],new['toolContractV1']
    if before['bindings']!=after['bindings'] or any(after['attempts'].get(aid)!=value for aid,value in before['attempts'].items()):
        raise ValueError('tool input rewritten')


def complete_receipt(state,packet,result,events,events_truncated):
    aid=packet['invocationId'];side=state['toolContractV1']['attempts'][aid]
    return packet|dict(contextPack=packet.get('contextPack'),exposureBindings=packet.get('exposureBindings'),
        toolContractV1=None if side is None else dict(version=1,bindings=state['toolContractV1']['bindings'],
            frozenInput=side['frozenInput'],retainedReferences=side['retainedReferences'],
            citations=result.result.metadata.get('citations_v1'),events=list(events),eventsTruncated=events_truncated))


def validate_receipt(packet):
    side=packet['toolContractV1']
    if side is None:
        if packet['encodingVersion']in ('conversation-turn-v4','conversation-turn-v5'):raise ValueError('missing ordinary authority')
        return
    if type(side) is not dict or set(side)!={'version','bindings','frozenInput','retainedReferences','citations','events','eventsTruncated'} or side['version']!=1:
        raise ValueError('invalid session receipt tool contract')
    validate_refs(side['retainedReferences'])
    frozen=FrozenTurnInput.from_dict(side['frozenInput'] if side['frozenInput'] is not None else packet['contextPack']['frozenInput']).to_dict()
    if type(side['events']) is not list or len(side['events'])>2048 or type(side['eventsTruncated']) is not bool:raise ValueError('invalid retained events')
    if len(encode(side['events']))>frozen['bindings']['limits']['max_event_bytes']:raise ValueError('retained events capacity')
    for event in side['events']:
        if event.get('event') not in {'tool_started','tool_completed'} or 'toolEventV1' not in event:raise ValueError('invalid retained event')
    evidence=TurnEvidence.from_dict(packet['evidence']).to_dict()
    if evidence['version']!=(4 if frozen['encodingVersion']=='conversation-turn-v5' else 3) or frozen['bindings']['toolContractV1']!=evidence['toolContractV1']['bindings'] or side['citations']!=evidence['toolContractV1']['citations']:
        raise ValueError('tool evidence binding mismatch')
    if side['citations'] is not None and not CitationsV1.from_dict(side['citations']).verify_answer(packet['result']['answer']):
        raise ValueError('accepted answer differs from citations')
    if packet['completedTurn'] is not None:
        last=packet['completedTurn']['messages'][-1]
        if last!={'role':'assistant','content':[{'type':'text','text':packet['result']['answer']}]}:raise ValueError('answer history mismatch')


def match_contract(state,packet):
    side=state['toolContractV1']['attempts'][packet['invocationId']];proof=packet['toolContractV1']
    if (side is None)!=(proof is None):raise ValueError('phase authority mismatch')
    if proof is not None and (proof['bindings']!=state['toolContractV1']['bindings'] or any(side[k]!=proof[k] for k in side)):
        raise ValueError('tool receipt input changed')


_SEAL=object()
@dataclass(frozen=True,init=False)
class RetainedCitationReference:
    _encoded: bytes
    def __init__(self,document,*,_seal=None):
        if _seal is not _SEAL:raise ValueError('owned stored receipt required')
        validate_refs([document]);object.__setattr__(self,'_encoded',encode(document))
    def to_dict(self):return decode(self._encoded)


def verified(chat,sid,aid):
    from .tool_contract_views import VerifiedToolReceipt
    chat._load(sid)
    return VerifiedToolReceipt.from_session_store(chat.store,sid,aid,bindings=chat.bindings,scope=chat.scope)


def retain(chat,sid,aid,eid):
    from .tool_contract_views import _record
    receipt=verified(chat,sid,aid);_record(receipt,eid)
    return RetainedCitationReference(dict(version=1,sessionId=sid,invocationId=aid,receiptSha256=receipt.identity,
        evidenceId=eid,scope=chat.scope.to_dict()),_seal=_SEAL)


def origin_receipts(chat,sid,refs):
    result={};pending=list(refs)
    while pending:
        ref=pending.pop()
        if ref['sessionId']!=sid or ref['scope']!=chat.scope.to_dict():raise ConversationError('identityMismatch')
        receipt=verified(chat,sid,ref['invocationId'])
        if receipt.identity!=ref['receiptSha256']:raise ConversationError('bindingMismatch')
        if receipt.identity in result:continue
        if len(result)>=16:raise ConversationError('contextLimit')
        result[receipt.identity]=receipt
        pending.extend(receipt.to_dict()['toolContractV1']['retainedReferences'])
    return tuple(result.values())


def invocation_bindings(chat,state,aid,*,references=(),pack_adapter=None):
    from .tool_contract_views import ToolContractViewBindings,authorize_source,_record,_content
    scope=scope_for(state,aid,namespace=chat.bindings.readmit()['operationNamespace'])
    base=pack_adapter.runtime_bindings if pack_adapter is not None else chat.bindings.tool_contracts.bind(scope)
    if not references:return base,[]
    origins=origin_receipts(chat,state['sessionId'],references)
    views=ToolContractViewBindings(chat.scope,evidence_authorizer=chat.bindings.tool_contracts.evidence_authorizer,
        context_packs=chat.bindings.context_packs,origins=origins)
    imports=[];source_map={}
    for ref in references:
        origin=next(r for r in origins if r.identity==ref['receiptSha256'])
        packet,frozen,evidence,record=_record(origin,ref['evidenceId'])
        if packet['turnSequence']>= (state['attempts'][aid]['turnSequence'] if aid in state['attempts'] else len(state['turns'])+1):
            raise ConversationError('bindingMismatch')
        content=_content(frozen,evidence,record)
        eid='ev_'+digest(dict(scope=asdict(scope),receipt=origin.identity,source=ref['evidenceId']))
        model=dict(evidence=dict(id=eid,label=record['label'],observation='retainedContext'),data=content)
        source=EvidenceDraftV1(record['sourceKey'],record['sourceRevision'],record['locator'],'',record['label'])
        item=HostEvidenceImportV1(scope,source,evidence_id=eid,origin_kind='retainedReceipt',
            origin_receipt_sha256=origin.identity,model_view=model,content_pointer='/data',reference_pointer='/evidence/id',lineage=ref['evidenceId'])
        imports.append(item)
        source_map['import_'+digest(item.to_dict())]=(origin,ref['evidenceId'])
    def authorize(use):
        if use.call_id in source_map:
            origin,eid=source_map[use.call_id]
            try:
                # The import's representation is newly hashed; the original
                # captured representation still requires a current grant.
                if chat.bindings.tool_contracts.evidence_authorizer is None or chat.bindings.tool_contracts.evidence_authorizer.authorize(use) is not True:return False
                authorize_source(origin,eid,views,use.purpose,scope=scope,call_id=use.call_id)
                return True
            except Exception:return False
        try:return base.evidence_authorizer is not None and base.evidence_authorizer.authorize(use) is True
        except Exception:return False
    wrapped=EvidenceAuthorizerV1('retained_'+digest(dict(base=base.evidence_authorizer.to_dict(),refs=list(references))),'1',authorize)
    return replace(base,evidence_authorizer=wrapped,retained=(*base.retained,*imports)),[item.model_view for item in imports]


def restore_attempt(chat,state,attempt,turn,*,fresh_attempt=False):
    from prosaic_runtime import ConversationMessage,ContextPolicy,ContextSelection,ContextAssemblyReport,ContextWorkState,AuthoritativeInputLimits
    from .session_contracts import history_of
    from .context_packs.records import ContextPackInvocation
    from .context_packs.tool_contracts import pack_evidence_bindings
    aid=uuid4().hex if fresh_attempt else attempt['invocationId']
    if fresh_attempt:
        state={**state,'attempts':{**state['attempts'],aid:{**attempt,'invocationId':aid}}}
    frozen=attempt_frozen(state,attempt['invocationId']);rt=chat.bindings.runtime(lifecycle=chat.lifecycle)
    adapter=None;frame=None
    if has_packs(state) and state['contextPacks']['attempts'][attempt['invocationId']] is not None:
        frame=ContextPackInvocation.from_dict(state['contextPacks']['attempts'][attempt['invocationId']])
        from .conversation_packs import authorize_pack
        import time
        authorize_pack(chat,state,frame,deadline=time.monotonic()+chat.bindings.run_policy.timeout_s)
        adapter=pack_evidence_bindings(frame,None,chat.bindings.context_packs,tool_contracts=chat.bindings.tool_contracts,
            scope=scope_for(state,aid,namespace=chat.bindings.readmit()['operationNamespace']),session_id=state['sessionId'])
    refs=state['toolContractV1']['attempts'][attempt['invocationId']]['retainedReferences']
    binding,models=invocation_bindings(chat,state,aid,references=refs,pack_adapter=adapter)
    options=dict(policy=chat.bindings.run_policy,limits=chat.bindings.turn_limits,workspace=chat.bindings._workspace,
        history=tuple(ConversationMessage.from_dict(m) for m in history_of(state,before_sequence=turn['sequence'])),
        tool_contract_bindings=binding)
    if not fresh_attempt:
        return rt,rt.restore_turn(chat.bindings.agent,frozen_input=frozen,context_policy=chat.bindings.context_policy,
            token_counters=chat.bindings.token_counters,context_work=ContextWorkState.from_dict(attempt['contextWork']) if attempt['contextWork'] is not None else None,**options)
    data=owned(frozen['selectedInputData'])
    if models:data={**(data or {}),'retainedEvidence':models}
    options.update(message=turn['message'],input_data=data,input_profile=frozen['inputProfile'])
    if frozen.get('authoritativeInputData') is not None:
        options.update(authoritative_input_data=frozen['authoritativeInputData'],authoritative_input_profile=frozen['authoritativeInputProfile'])
        if frozen['authoritativeInputLimits'] is not None:options['authoritative_input_limits']=AuthoritativeInputLimits(**frozen['authoritativeInputLimits'])
    if frozen['contextSelection'] is not None:
        options.update(context_policy=chat.bindings.context_policy,token_counters=chat.bindings.token_counters,
            context_selection=ContextSelection.from_dict(frozen['contextSelection']),
            context_report=ContextAssemblyReport.from_dict(frozen['contextReport']),context_work=ContextWorkState.from_dict(frozen['initialContextWork']))
    return rt,rt.prepare_turn(chat.bindings.agent,**options)


def same_retry_input(old,new,prior_aid,next_aid):
    """An explicit new scope may change IDs, never selected data or allowances."""
    left,right=attempt_frozen(old,prior_aid),attempt_frozen(new,next_aid)
    a,b=old['toolContractV1']['attempts'][prior_aid],new['toolContractV1']['attempts'][next_aid]
    if a['retainedReferences']!=b['retainedReferences']:return False
    keys=('message','inputProfile','authoritativeInputData','authoritativeInputProfile','authoritativeInputLimits',
        'sourceHistoryDigest','selectedHistoryDigest','contextSelection','contextReport')
    if any(left[k]!=right[k] for k in keys):return False
    lb,rb=left['bindings'],right['bindings']
    if {k:v for k,v in lb.items() if k!='toolContractV1'}!={k:v for k,v in rb.items() if k!='toolContractV1'}:return False
    li,ri=lb['toolContractV1']['retained'],rb['toolContractV1']['retained']
    if len(li)!=len(ri):return False
    replacements={}
    for l,r in zip(li,ri):
        if {k:v for k,v in l.items() if k not in {'scope','evidenceId','modelViewSha256'}}!={k:v for k,v in r.items() if k not in {'scope','evidenceId','modelViewSha256'}}:return False
        replacements[l['evidenceId']]=r['evidenceId']
    def rename(value):
        if type(value) is str:return replacements.get(value,value)
        if type(value) is list:return [rename(v) for v in value]
        if type(value) is dict:return {k:rename(v) for k,v in value.items()}
        return value
    return rename(left['selectedInputData'])==right['selectedInputData']


class HistoricalEvidenceDenied(RuntimeError):
    def __init__(self):super().__init__('evidenceUseDenied')


def authorize_tool_history(chat,state,purpose,*,scope=None,before_sequence=None,report=None):
    """Check only history actually retained for this read/model submission.

    Textual IDs confer no new registry authority. These checks protect the
    captured source bodies already present in portable historical messages.
    """
    if state.get('version') not in (4,5):return
    from .tool_contract_views import ToolContractViewBindings,authorize_source
    turns=[turn for turn in state['turns'] if turn['history'] and (before_sequence is None or turn['sequence']<before_sequence)]
    if report is not None:turns=turns[report.omitted_turn_count:]
    for turn in turns:
        if turn['status']!='completed' or not turn['attempts']:continue
        aid=turn['attempts'][-1]
        if state['toolContractV1']['attempts'][aid] is None:continue
        try:
            receipt=verified(chat,state['sessionId'],aid);packet=receipt.to_dict()
            origins=origin_receipts(chat,state['sessionId'],packet['toolContractV1']['retainedReferences'])
            views=ToolContractViewBindings(chat.scope,evidence_authorizer=chat.bindings.tool_contracts.evidence_authorizer,
                context_packs=chat.bindings.context_packs,origins=origins)
            for eid in packet['evidence']['toolContractV1']['evidence']['deliveries']:
                authorize_source(receipt,eid,views,purpose,scope=scope)
        except Exception:
            raise HistoricalEvidenceDenied() from None
