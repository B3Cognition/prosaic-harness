"""Current-grant views of authoritative stored receipts. No source or URL fetches."""
from dataclasses import asdict, dataclass
import hashlib
import json

from prosaic_runtime import (InvocationScope, EvidenceAuthorizerV1, ToolDisplayAuthorizerV1,
    EvidenceUseV1, ToolDisplayUseV1)
from .session_codec import encode, decode, owned, digest, reference
from .conversation_bindings import ConversationScope

_SEAL=object()


def _owner(scope):
    if type(scope) is ConversationScope:
        return dict(kind='conversation',value=scope.to_dict())
    if type(scope) is InvocationScope:
        scope.__post_init__()
        return dict(kind='invocation',value=asdict(scope))
    raise ValueError('typed owner scope required')


@dataclass(frozen=True,init=False)
class VerifiedToolReceipt:
    _encoded: bytes
    _owner_encoded: bytes
    _delegates: object
    _delegate_proofs: bytes

    def __init__(self,packet,owner,*,delegates=None,delegate_proofs=(),_seal=None):
        if _seal is not _SEAL: raise ValueError('owned stored receipt required')
        object.__setattr__(self,'_encoded',encode(packet))
        object.__setattr__(self,'_owner_encoded',encode(owner))
        object.__setattr__(self,'_delegates',delegates)
        object.__setattr__(self,'_delegate_proofs',encode(list(delegate_proofs)))

    @classmethod
    def from_workflow_store(cls,store,run_id,invocation_id,*,workflow):
        from .factory import admit_workflow
        from .contracts import validate_state,validate_receipt
        state=store.load_run(run_id).state
        packet=store.load_receipt(run_id,invocation_id)
        admit_workflow(workflow);validate_state(state,workflow)
        if packet is None or state['fingerprint']!=workflow.current_fingerprint() or state.get('version') not in (4,5,6):
            raise ValueError('unavailable owned tool receipt')
        invocation=next((item for item in state['invocations'] if item['id']==invocation_id),None)
        if invocation is None or invocation['status']!='complete' or invocation['receipt_sha256']!=packet['sha256']:
            raise ValueError('receipt is not adopted')
        validate_receipt(packet,state,invocation,workflow)
        proofs=[]
        if state['version']==6:
            for item in state['invocations']:
                if item['status']=='complete':
                    prior=store.load_receipt(run_id,item['id'])
                    if prior is None or item['receipt_sha256']!=prior['sha256']:
                        raise ValueError('delegation receipt is unavailable')
                    if prior['subAgentsV1'] is not None: proofs.append(prior['subAgentsV1'])
                if item['id']==invocation_id: break
        return cls(packet,_owner(InvocationScope(**packet['toolContractV1']['scope'])),
            delegates=workflow._sub_agents,delegate_proofs=proofs,_seal=_SEAL)

    @classmethod
    def from_session_store(cls,store,session_id,invocation_id,*,bindings,scope):
        from .session_contracts import match_receipt
        state=store.load_session(session_id,scope=scope).state
        packet=store.load_receipt(session_id,invocation_id,scope=scope)
        bindings.readmit()
        if state['bindingIdentity']!=bindings.identity or state.get('version') not in (4,5,6) or packet is None:
            raise ValueError('unavailable owned tool receipt')
        attempt=state['attempts'].get(invocation_id)
        if attempt is None or not attempt['receiptAdopted'] or attempt['receiptIdentity']!=packet['sha256']:
            raise ValueError('receipt is not adopted')
        match_receipt(state,packet)
        if packet.get('toolContractV1') is None: raise ValueError('no tool contract for this phase')
        proofs=[]
        if state['version']==6:
            for aid, previous in state['attempts'].items():
                if previous['receiptAdopted'] and previous['turnSequence']<=attempt['turnSequence']:
                    prior=store.load_receipt(session_id,aid,scope=scope)
                    if prior is None or previous['receiptIdentity']!=prior['sha256']:
                        raise ValueError('delegation receipt is unavailable')
                    if prior['subAgentsV1'] is not None: proofs.append(prior['subAgentsV1'])
        return cls(packet,_owner(scope),delegates=bindings.sub_agents,delegate_proofs=proofs,_seal=_SEAL)

    def _delegation_granted(self,scope,purpose):
        proofs=decode(self._delegate_proofs)
        return not proofs or self._delegates is not None and all(
            self._delegates.may_reuse(proof,scope,purpose) for proof in proofs)

    def to_dict(self): return decode(self._encoded)

    @property
    def identity(self): return self.to_dict()['sha256']

    @property
    def owner(self): return decode(self._owner_encoded)


@dataclass(frozen=True)
class ToolContractViewBindings:
    scope: object
    evidence_authorizer: object = None
    display_authorizer: object = None
    context_packs: object = None
    origins: tuple = ()
    max_bytes: int = 262144

    def __post_init__(self):
        _owner(self.scope)
        if self.evidence_authorizer is not None and type(self.evidence_authorizer) is not EvidenceAuthorizerV1:
            raise ValueError('invalid evidence viewing grant')
        if self.display_authorizer is not None and type(self.display_authorizer) is not ToolDisplayAuthorizerV1:
            raise ValueError('invalid event viewing grant')
        if type(self.origins) is not tuple or len(self.origins)>16 or any(type(item) is not VerifiedToolReceipt for item in self.origins):
            raise ValueError('verified origin receipts required')
        if sum(len(item._encoded) for item in self.origins)>8_388_608:
            raise ValueError('origin receipt capacity')
        if type(self.max_bytes) is not int or not 128<=self.max_bytes<=4_194_304:
            raise ValueError('invalid source view limit')


def _parts(verified):
    packet=verified.to_dict()
    if packet['recordType']=='workflowReceipt':
        from .tool_contracts import receipt_contract_material
        frozen,evidence=receipt_contract_material(packet)
        if evidence is None: return packet,None,None
    else:
        evidence=packet['evidence'];side=packet['toolContractV1']
        frozen=side['frozenInput'] if side['frozenInput'] is not None else packet['contextPack']['frozenInput']
    return packet,frozen,evidence


def _record(verified,evidence_id):
    packet,frozen,evidence=_parts(verified)
    if evidence is None or evidence.get('version') not in (3,4): raise ValueError('source was not exposed')
    registry=evidence['toolContractV1']['evidence']
    if evidence_id not in registry['deliveries']: raise ValueError('source was not delivered')
    record=next((record for record in registry['records'] if record['id']==evidence_id),None)
    if record is None: raise ValueError('missing captured source')
    return packet,frozen,evidence,record


def _content(frozen,evidence,record):
    from .context_packs.selection import project
    if record.get('originKind') in {'contextPack','retainedReceipt'}:
        descriptor=next(item for item in evidence['toolContractV1']['bindings']['retained'] if item['evidenceId']==record['id'])
        stack=[frozen['selectedInputData']];selected=None;found=False
        while stack:
            node=stack.pop()
            if type(node) is dict:
                if digest(node)==descriptor['modelViewSha256']:
                    selected=project(node,dict(kind='jsonPointer',pointer=descriptor['contentPointer']));found=True;break
                stack.extend(node.values())
            elif type(node) is list: stack.extend(node)
        if not found: raise ValueError('captured import is absent')
    else:
        call=next(item for item in evidence['toolContractV1']['evidence']['calls'] if item['callId']==record['callId'])
        selected=project(call['outcome']['result']['data'],dict(kind='jsonPointer',pointer=record['selector']))
    raw=selected.encode('utf-8') if record['contentKind']=='text' and type(selected) is str else encode(selected)
    if hashlib.sha256(raw).hexdigest()!=record['contentSha256'] or len(raw)!=record['contentBytes']:
        raise ValueError('captured representation mismatch')
    return selected


def authorize_source(verified,evidence_id,bindings,purpose,*,scope=None,call_id=None,_seen=()):
    """Host-only permission seam shared by views and explicitly retained imports."""
    if type(verified) is not VerifiedToolReceipt or type(bindings) is not ToolContractViewBindings:
        raise ValueError('typed verified source bindings required')
    bindings.__post_init__()
    if len(_seen)>=8 or (verified.identity,evidence_id) in _seen: raise ValueError('cyclic retained source')
    packet,frozen,evidence,record=_record(verified,evidence_id)
    if not verified._delegation_granted(bindings.scope,purpose):
        raise ValueError('delegate result use denied')
    grant=bindings.evidence_authorizer
    scope=InvocationScope(**evidence['toolContractV1']['bindings']['scope']) if scope is None else scope
    use=EvidenceUseV1(scope,purpose,record['sourceKey'],record['sourceRevision'],record['locator'],record['selector'],
        record['contentSha256'],call_id or record['callId'])
    if grant is None or grant.authorize(use) is not True: raise ValueError('source use denied')
    if record.get('originKind')=='retainedReceipt':
        origin=next((item for item in bindings.origins if item.identity==record['originReceiptSha256']),None)
        if origin is None: raise ValueError('retained origin is unavailable')
        if origin.owner!=verified.owner: raise ValueError('foreign retained source')
        prior=authorize_source(origin,record['lineage'],bindings,purpose,scope=scope,call_id=call_id,
            _seen=(*_seen,(verified.identity,evidence_id)))
        if encode(prior)!=encode(_content(frozen,evidence,record)): raise ValueError('retained content changed')
    elif record.get('originKind')=='contextPack' or record['sourceKey'].startswith('ctx_'):
        from .context_packs.records import ContextPackInvocation
        from .context_packs.tool_contracts import pack_evidence_bindings
        from .tool_contracts import ToolContracts
        if bindings.context_packs is None or packet.get('contextPack') is None:
            raise ValueError('pack viewing grant absent')
        adapter=pack_evidence_bindings(ContextPackInvocation.from_dict(packet['contextPack']),evidence,bindings.context_packs,
            tool_contracts=ToolContracts('view','1',evidence_authorizer=grant),scope=scope,
            session_id=packet.get('sessionId'))
        if not adapter.authorize(use): raise ValueError('pack source use denied')
    return _content(frozen,evidence,record)


def resolve_citation_view(receipt,evidence_id,view_bindings):
    if type(receipt) is not VerifiedToolReceipt or type(view_bindings) is not ToolContractViewBindings:
        raise ValueError('typed verified receipt required')
    reference(evidence_id)
    unavailable=dict(version=1,available=False,evidenceId=evidence_id)
    try:
        if receipt.owner!=_owner(view_bindings.scope): return unavailable
        content=authorize_source(receipt,evidence_id,view_bindings,'retainedRead')
        record=_record(receipt,evidence_id)[3]
        return decode(encode(dict(version=1,available=True,evidenceId=evidence_id,label=record['label'],
            contentKind=record['contentKind'],content=content),maximum=view_bindings.max_bytes))
    except Exception:
        return unavailable


def project_retained_tool_event(receipt,event_index,view_bindings,tools):
    if type(receipt) is not VerifiedToolReceipt or type(view_bindings) is not ToolContractViewBindings:
        raise ValueError('typed verified receipt required')
    unavailable=dict(version=1,available=False)
    try:
        if receipt.owner!=_owner(view_bindings.scope) or type(event_index) is not int or event_index<0: return unavailable
        if not receipt._delegation_granted(view_bindings.scope,'retainedRead'): return unavailable
        packet,frozen,evidence=_parts(receipt)
        if frozen is None:return unavailable
        events=packet['events'] if packet['recordType']=='workflowReceipt' else packet['toolContractV1']['events']
        event=owned(events[event_index])
        if event.get('event') not in {'tool_started','tool_completed'} or 'toolEventV1' not in event: return unavailable
        tool=tools[event['name']]
        if tool.descriptor!=frozen['bindings']['tools'][tool.name]: return unavailable
        fields=tuple(event['toolEventV1'].get('display',{}))
        use=ToolDisplayUseV1(InvocationScope(**evidence['toolContractV1']['bindings']['scope']),tool.name,tool.version,
            event['call_id'],event['toolEventV1']['phase'],fields)
        grant=view_bindings.display_authorizer
        try: allowed=grant is not None and grant.authorize(use) is True
        except Exception: allowed=False
        if not allowed: event['toolEventV1'].pop('display',None)
        return decode(encode(dict(version=1,available=True,event=event),maximum=view_bindings.max_bytes))
    except Exception:
        return unavailable
