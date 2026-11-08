"""Versioned workflow records; no controller checks or execution during adoption."""
from dataclasses import asdict
from .codec import ContextPackError,closed,decode,encode,digest
from .records import ContextPackInvocation,validate_completed_pack_evidence
from .types import ContextScope
from .capacity import PackReservation,reserve_pack_capacity,_nodes


def _owned(value): return decode(encode(value,maximum=8388608,nodes=65536,depth=64))


def upgrade_pack_workflow(document,workflow):
    from ..contracts import validate_state,seal
    state=_owned(document);validate_state(state,workflow)
    bindings=workflow._context_packs
    if bindings is None or state['calls'] or state['pending'] is not None: raise ContextPackError('contextBindingMismatch')
    state.update(version=3,recordType='workflow',contextPacks=dict(version=1,scope=bindings.scope.to_dict(),
        bindingIdentity=bindings.identity,attempts={},reservations={}))
    state=seal(state);validate_state(state,workflow)
    return state


def reserve_workflow_pack_attempt(document,workflow,step,arguments,frame,*,tool_result_bytes=()):
    from ..contracts import validate_state,seal
    from ..workflow import digest as arguments_digest
    state=_owned(document);validate_state(state,workflow)
    if state['version']!=3 or state['pending'] is not None or state['current']!=step: raise ContextPackError('contextBindingMismatch')
    if type(frame) is not ContextPackInvocation or frame.stage!='prepared' or frame.projection is None: raise ContextPackError()
    projection=frame.projection
    if projection['step']!=step or projection['originalArgumentsDigest']!=arguments_digest(arguments): raise ContextPackError('contextBindingMismatch')
    aid=frame.invocation_id
    if aid in state['contextPacks']['attempts']: raise ContextPackError('contextBindingMismatch')
    state['pending']=dict(id=aid,step=step,arguments_sha256=arguments_digest(arguments),arguments=_owned(arguments))
    state['invocations'].append(dict(id=aid,step=step,arguments_sha256=arguments_digest(arguments),
        status='pending',token_usage=None,receipt_sha256=None))
    state['calls']+=1;state['attempt']+=1
    state['contextPacks']['attempts'][aid]=frame.to_dict()
    state['contextPacks']['reservations'][aid]=None
    policy=workflow._admission.policy
    packet=dict(version=2,recordType='workflowReceipt',run_id=state['run_id'],id=aid,step=step,
        arguments_sha256=arguments_digest(arguments),arguments=arguments,contextPack=frame.to_dict(),contextPackResult=None,
        result=None,events=[])
    reservation=reserve_pack_capacity(state,packet,max_state_bytes=policy.max_state_bytes,
        max_receipt_bytes=policy.max_receipt_bytes,max_json_nodes=policy.max_json_nodes,
        output_bytes=min(policy.max_output_bytes,65536),metadata_bytes=policy.max_metadata_bytes,
        event_bytes=policy.max_event_bytes,tool_result_bytes=tool_result_bytes,
        provider_allowance=frame.frozen_input.to_dict()['bindings']['policy']['max_provider_requests'])
    state['contextPacks']['reservations'][aid]=reservation.to_dict()
    state=seal(state);validate_state(state,workflow)
    return state


def validate_workflow_pack_state(state,workflow):
    if state['recordType']!='workflow': raise ContextPackError()
    side=state['contextPacks'];closed(side,{'version','scope','bindingIdentity','attempts','reservations'})
    bindings=workflow._context_packs
    if (type(side['version']) is not int or side['version']!=1 or bindings is None
            or side['bindingIdentity']!=bindings.identity or side['scope']!=bindings.scope.to_dict()):
        raise ContextPackError('contextBindingMismatch')
    ContextScope.from_dict(side['scope'])
    ids={entry['id'] for entry in state['invocations']}
    if type(side['attempts']) is not dict or type(side['reservations']) is not dict or set(side['attempts'])!=ids or set(side['reservations'])!=ids:
        raise ContextPackError()
    for entry in state['invocations']:
        aid=entry['id'];value=side['attempts'][aid];reservation=side['reservations'][aid]
        if reservation is not None: PackReservation.from_dict(reservation)
        if value is None:
            if reservation is not None or workflow.context_pack_for(entry['step']) is not None: raise ContextPackError('contextBindingMismatch')
            continue
        frame=ContextPackInvocation.from_dict(value)
        projection=frame.projection
        if (frame.invocation_id!=aid or projection is None or projection['step']!=entry['step']
                or projection['originalArgumentsDigest']!=entry['arguments_sha256']
                or frame.candidates.snapshot.scope_binding.to_dict()!=side['scope']):
            raise ContextPackError('contextBindingMismatch')
        expected={'pending':{'prepared','dispatched'},'complete':{'adopted'},'abandoned':{'abandoned'}}[entry['status']]
        if frame.stage not in expected or frame.receipt_identity!=entry['receipt_sha256']: raise ContextPackError('contextBindingMismatch')
        if state['pending'] is not None and state['pending']['id']==aid:
            if encode(projection['originalArguments'])!=encode(state['pending']['arguments']): raise ContextPackError('contextBindingMismatch')


def mark_workflow_pack_dispatch(document,workflow,invocation_id):
    from ..contracts import seal,validate_state
    state=_owned(document);validate_state(state,workflow)
    if state['pending'] is None or state['pending']['id']!=invocation_id: raise ContextPackError('contextBindingMismatch')
    side=state['contextPacks']['attempts']
    side[invocation_id]=ContextPackInvocation.from_dict(side[invocation_id]).mark_dispatched().to_dict()
    state=seal(state);validate_state(state,workflow)
    return state


def checkpoint_workflow_pack_work(document,workflow,invocation_id,work):
    from ..contracts import seal,validate_state
    state=_owned(document);validate_state(state,workflow)
    if state['pending'] is None or state['pending']['id']!=invocation_id: raise ContextPackError('contextBindingMismatch')
    side=state['contextPacks']['attempts']
    side[invocation_id]=ContextPackInvocation.from_dict(side[invocation_id]).checkpoint(work).to_dict()
    state=seal(state);validate_state(state,workflow)
    return state


def make_workflow_pack_receipt(document,workflow,turn,*,events,result=None):
    from ..contracts import seal,validate_state,validate_receipt
    from ..conversation_rules import rule_receipt
    state=_owned(document);validate_state(state,workflow)
    pending=state['pending'];aid=pending['id']
    frame=ContextPackInvocation.from_dict(state['contextPacks']['attempts'][aid]).complete(turn)
    packet=seal(dict(version=2,recordType='workflowReceipt',run_id=state['run_id'],**pending,
        result=asdict(turn.result) if result is None else result,events=_owned(events),contextPack=frame.to_dict(),
        contextPackResult=dict(evidence=turn.evidence.to_dict(),rules=rule_receipt(turn),
            finalContextReport=turn.context_report.to_dict() if turn.context_report is not None else None,
            contextWork=turn.context_work.to_dict() if turn.context_work is not None else None)))
    validate_receipt(packet,state,pending,workflow)
    return packet


def validate_workflow_pack_receipt(packet,state,pending,workflow):
    from ..conversation_rules import validate_rule_receipt
    from prosaic_runtime import TurnEvidence
    if packet['recordType']!='workflowReceipt': raise ContextPackError()
    aid=packet['id'];before=state['contextPacks']['attempts'][aid]
    after=packet['contextPack'];proof=packet['contextPackResult']
    if (before is None)!=(after is None): raise ContextPackError('contextBindingMismatch')
    if after is None:
        if proof is not None: raise ContextPackError('contextBindingMismatch')
        return
    frame=ContextPackInvocation.from_dict(before);completed=ContextPackInvocation.from_dict(after)
    if (completed.stage!='completed' or frame.frozen_identity!=completed.frozen_identity
            or completed.invocation_id!=aid): raise ContextPackError('contextBindingMismatch')
    closed(proof,{'evidence','rules','finalContextReport','contextWork'})
    evidence=TurnEvidence.from_dict(proof['evidence']).to_dict()
    if proof['rules'] is not None: validate_rule_receipt(proof['rules'])
    frozen=frame.frozen_input.to_dict()
    validate_completed_pack_evidence(completed,evidence,proof['rules'],packet['result']['exit_code']==0,proof['finalContextReport'])
    if (evidence.get('inputViews')!=frozen['inputViews'] or completed.result_evidence_digest!=digest(evidence)
            or completed.rule_receipt_digest!=(digest(proof['rules']) if proof['rules'] is not None else None)
            or completed.final_context_report_digest!=(digest(proof['finalContextReport']) if proof['finalContextReport'] is not None else None)
            or completed.to_dict()['contextWork']!=proof['contextWork']): raise ContextPackError('contextBindingMismatch')
    if frame.stage=='adopted':
        if frame.receipt_identity!=packet['sha256']: raise ContextPackError('contextBindingMismatch')
    elif frame.stage not in {'prepared','dispatched'}: raise ContextPackError('contextBindingMismatch')
    if frame.stage=='prepared' and (evidence['providerAttempts'] or evidence['toolAttempts'] or evidence['failureCode'] is None):
        raise ContextPackError('contextBindingMismatch')
    policy=frozen['bindings']['policy']
    if evidence['providerAttempts']>policy['max_provider_requests'] or evidence['toolAttempts']>policy['max_tool_calls']:
        raise ContextPackError('contextBindingMismatch')
    if frame.to_dict()['contextWork']!=proof['contextWork']:
        from ..session_context import validate_work_transition
        validate_work_transition(frame.context_work,completed.context_work)
    reservation=state['contextPacks']['reservations'][aid]
    if reservation is not None:
        bound=PackReservation.from_dict(reservation)
        if (len(packet['result']['stdout'].encode())+len(packet['result']['stderr'].encode())>bound.output_bytes
                or len(encode(packet['result']['metadata']))>bound.metadata_bytes
                or _nodes(packet['result']['metadata'])>bound.metadata_nodes
                or len(encode(packet['events']))>bound.event_bytes
                or _nodes(packet['events'])>bound.event_nodes
                or len(encode(packet))>bound.max_receipt_bytes):
            raise ContextPackError('contextSnapshotLimit')
    from ..workflow_rules import compiled
    if workflow is not None and pending['step'] in compiled(workflow):
        # V1 proofs cannot authenticate the model/private split. The v2 proof
        # validator is installed with controller integration; fail closed here.
        from ..workflow_rules import validate_pack_proof
        validate_pack_proof(packet['result']['metadata'].get('workflow_rules_v2'),workflow,pending['step'],completed,proof,
            success=packet['result']['exit_code']==0)


def adopt_workflow_pack_receipt(document,packet,workflow):
    from ..contracts import validate_state,validate_receipt,seal
    state=_owned(document);validate_state(state,workflow)
    entry=next((item for item in state['invocations'] if item['id']==packet['id']),None)
    if entry is None: raise ContextPackError('contextBindingMismatch')
    pending=state['pending'] if state['pending'] is not None else entry
    validate_receipt(packet,state,pending,workflow)
    if entry['status']=='complete':
        if entry['receipt_sha256']!=packet['sha256']: raise ContextPackError('contextBindingMismatch')
        return state
    if state['pending'] is None or state['pending']['id']!=entry['id']: raise ContextPackError('contextBindingMismatch')
    entry.update(status='complete',token_usage=packet['result']['token_usage'],receipt_sha256=packet['sha256'])
    if packet['contextPack'] is not None:
        state['contextPacks']['attempts'][entry['id']]=ContextPackInvocation.from_dict(packet['contextPack']).adopt(packet['sha256']).to_dict()
    state['pending']=None
    state=seal(state);validate_state(state,workflow)
    return state
