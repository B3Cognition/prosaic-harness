"""Versioned workflow records; no controller checks or execution during adoption."""
from dataclasses import asdict
from .codec import ContextPackError,closed,decode,encode,digest
from .records import ContextPackInvocation,validate_completed_pack_evidence
from .types import ContextScope
from .capacity import PackReservation,reserve_pack_capacity,_nodes,TOOL_ENVELOPE_BYTES,TOOL_ENVELOPE_NODES


def _owned(value): return decode(encode(value,maximum=8388608,nodes=65536,depth=64))


def storage_policy(workflow):
    from ..factory import WorkflowPolicy
    admission=getattr(workflow,'_admission',None)
    return admission.policy if admission is not None else WorkflowPolicy()


def output_pack_binding(frame):
    if frame is None: return dict(contextPackIdentity=None,contextSourceRevisions=None)
    if type(frame) is not ContextPackInvocation: frame=ContextPackInvocation.from_dict(frame)
    return dict(contextPackIdentity=frame.selected_pack_reference['packIdentity'],
        contextSourceRevisions=frame.candidates.snapshot.to_dict()['sources'])


def metadata_bounds(frame,tool_bytes):
    """Bound all receipt metadata occurrences, including duplicated proofs.

    Tool outcomes already have their own body/envelope reservations. Evidence
    can spend that budget on other bounded JSON, so its node ceiling is shared
    with those reservations rather than silently counted twice or omitted.
    """
    frozen=frame.frozen_input.to_dict();limits=frozen['bindings']['limits']
    rules=frozen['bindings'].get('rules',{})
    maximum_rules=maximum_proof=None
    if rules.get('bindings'):
        from ..workflow_rules import pack_proof
        ids=[binding['id'] for binding in rules['bindings']]
        maximum_rules=dict(version=1,fingerprint=rules['fingerprint'],
            **{key:ids for key in ('evaluated','violated','fixed','faulted')})
        maximum_proof=pack_proof(frame,maximum_rules)
    proof_bytes=len(encode(maximum_proof)) if maximum_proof is not None else 0
    rule_bytes=len(encode(maximum_rules)) if maximum_rules is not None else 0
    tool_room=sum(amount+TOOL_ENVELOPE_BYTES for amount in tool_bytes)
    tool_nodes=sum((amount+1)//2+1+TOOL_ENVELOPE_NODES for amount in tool_bytes)
    report=frozen['contextReport']
    base_evidence=max(0,limits['max_evidence_bytes']-tool_room)
    evidence_nodes=min(limits['max_json_nodes'],(limits['max_evidence_bytes']+1)//2+1)
    meta_nodes=min(limits['max_json_nodes'],(limits['max_metadata_bytes']+1)//2+1)
    # Work is a <=4KiB closed record; final report changes only bounded integer
    # counts. Include their framing and final evidence/rule hashes as well.
    byte_bound=(limits['max_metadata_bytes']+base_evidence+proof_bytes+rule_bytes+
        len(encode(report))+4096+1024+tool_room)
    node_bound=meta_nodes+max(0,evidence_nodes-tool_nodes)+_nodes(maximum_proof)+_nodes(maximum_rules)+_nodes(report)+128+64*len(tool_bytes)
    if frozen['encodingVersion']=='conversation-turn-v4':
        contract=frozen['bindings']['toolContractV1']['limits']
        byte_bound+=tool_room+contract['max_citation_bytes']+4096
        registry_nodes=contract['max_registry_items']*(32+4*frozen['bindings']['policy']['max_provider_requests'])
        node_bound=2048+_nodes(maximum_proof)+_nodes(maximum_rules)+_nodes(report)+registry_nodes+contract['max_citations']*8+_nodes(frozen['bindings']['toolContractV1'])+2*tool_nodes
    return byte_bound,node_bound,limits['max_metadata_bytes']+proof_bytes


def upgrade_pack_workflow(document,workflow,*,assembly_bindings=None):
    from ..contracts import validate_state,seal
    state=_owned(document);validate_state(state,workflow)
    bindings=workflow._context_packs
    if bindings is None or state['calls'] or state['pending'] is not None: raise ContextPackError('contextBindingMismatch')
    state.update(version=3,recordType='workflow',contextPacks=dict(version=1,scope=bindings.scope.to_dict(),
        bindingIdentity=bindings.identity,attempts={},reservations={},assemblyBindings=assembly_bindings))
    state=seal(state);validate_state(state,workflow)
    return state


def reserve_workflow_pack_attempt(document,workflow,step,arguments,frame,*,tool_result_bytes=()):
    from ..contracts import validate_state,seal
    from ..workflow import digest as arguments_digest
    state=_owned(document);validate_state(state,workflow)
    if state['version'] not in (3,4) or state['pending'] is not None or state['current']!=step: raise ContextPackError('contextBindingMismatch')
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
    if state['version']==4: state['toolContractV1']['attempts'][aid]=None
    state['contextPacks']['reservations'][aid]=None
    policy=storage_policy(workflow)
    metadata_bytes,metadata_nodes,result_metadata_bytes=metadata_bounds(frame,tool_result_bytes)
    if result_metadata_bytes>policy.max_metadata_bytes: raise ContextPackError('contextPackLimit')
    packet=dict(version=3 if state['version']==4 else 2,recordType='workflowReceipt',run_id=state['run_id'],id=aid,step=step,
        arguments_sha256=arguments_digest(arguments),arguments=arguments,contextPack=frame.to_dict(),contextPackResult=None,
        result=None,events=[])
    if state['version']==4: packet['toolContractV1']=None
    reservation=reserve_pack_capacity(state,packet,max_state_bytes=policy.max_state_bytes,
        max_receipt_bytes=policy.max_receipt_bytes,max_json_nodes=policy.max_json_nodes,
        output_bytes=min(policy.max_output_bytes,65536),metadata_bytes=metadata_bytes,metadata_nodes=metadata_nodes,
        event_bytes=policy.max_event_bytes,tool_result_bytes=tool_result_bytes,
        provider_allowance=frame.frozen_input.to_dict()['bindings']['policy']['max_provider_requests'])
    state['contextPacks']['reservations'][aid]=reservation.to_dict()
    state=seal(state);validate_state(state,workflow)
    return state


def validate_workflow_pack_state(state,workflow):
    if state['recordType']!='workflow': raise ContextPackError()
    side=state['contextPacks'];closed(side,{'version','scope','bindingIdentity','attempts','reservations'},optional={'diagnostics','assemblyBindings'})
    assembly=side.get('assemblyBindings')
    if assembly is not None:
        from prosaic_runtime import ContextPolicy,TokenCounterDescriptor
        closed(assembly,{'contextPolicy','counterDescriptor'})
        policy=ContextPolicy.from_dict(assembly['contextPolicy']);counter=TokenCounterDescriptor.from_dict(assembly['counterDescriptor'])
        if policy.counter_identity!=counter.identity or policy.context_window_tokens>counter.context_capacity_tokens: raise ContextPackError()
    if 'diagnostics' in side:
        from .feedback import private_diagnostics
        if type(side['diagnostics']) is not dict or len(side['diagnostics'])>128: raise ContextPackError()
        for value in side['diagnostics'].values():
            if encode(value)!=encode(private_diagnostics(value['issues'])): raise ContextPackError()
    bindings=workflow._context_packs
    from .feedback import readmit_feedback
    readmit_feedback(state['feedback'],workflow._feedback_catalog)
    if (type(side['version']) is not int or side['version']!=1 or bindings is None
            or side['bindingIdentity']!=bindings.identity or side['scope']!=bindings.scope.to_dict()):
        raise ContextPackError('contextBindingMismatch')
    ContextScope.from_dict(side['scope'])
    ids={entry['id'] for entry in state['invocations']}
    if type(side['attempts']) is not dict or type(side['reservations']) is not dict or set(side['attempts'])!=ids or set(side['reservations'])!=ids:
        raise ContextPackError()
    predecessors={}
    for entry in state['invocations']:
        aid=entry['id'];value=side['attempts'][aid];reservation=side['reservations'][aid]
        if reservation is not None: PackReservation.from_dict(reservation)
        if value is None:
            if reservation is not None or workflow.context_pack_for(entry['step']) is not None: raise ContextPackError('contextBindingMismatch')
            continue
        frame=ContextPackInvocation.from_dict(value)
        if frame.to_dict()['version']==2:
            prior=predecessors.get(entry['step'])
            if frame.execution_epoch!=1 or prior is not None and prior[0]=='abandoned':
                if (prior is None or prior[0]!='abandoned' or frame.execution_epoch!=prior[1].execution_epoch+1
                        or frame.selected_pack_reference!=prior[1].selected_pack_reference):
                    raise ContextPackError('contextBindingMismatch')
            predecessors[entry['step']]=(entry['status'],frame)
        if reservation is None: raise ContextPackError('contextBindingMismatch')
        bound=PackReservation.from_dict(reservation)
        caps=storage_policy(workflow)
        minimum_bytes,minimum_nodes,result_bytes=metadata_bounds(frame,bound.tool_result_bytes)
        limits=frame.frozen_input.to_dict()['bindings']['limits']
        policy=frame.frozen_input.to_dict()['bindings']['policy']
        result_bound=max([workflow.tool_descriptors[tool]['max_result_bytes'] if tool in workflow.tool_descriptors
            else caps.max_invocation_bytes for tool in policy['allowed_tools']] or [0])
        expected_tools=[result_bound]*policy['max_tool_calls'] if result_bound else []
        if (bound.family!='workflow' or bound.max_state_bytes!=caps.max_state_bytes
                or bound.max_receipt_bytes!=caps.max_receipt_bytes or bound.max_json_nodes!=caps.max_json_nodes
                or bound.metadata_bytes<minimum_bytes or bound.metadata_nodes<minimum_nodes
                or bound.event_bytes<caps.max_event_bytes or bound.output_bytes<min(caps.max_output_bytes,65536)
                or bound.tool_result_bytes!=expected_tools or bound.provider_allowance!=policy['max_provider_requests']
                or result_bytes>caps.max_metadata_bytes):
            raise ContextPackError('contextBindingMismatch')
        frozen_binding=frame.frozen_input.to_dict()['bindings']
        if (frozen_binding.get('contextPolicy')!=(assembly['contextPolicy'] if assembly else None)
                or frozen_binding.get('counterDescriptor')!=(assembly['counterDescriptor'] if assembly else None)):
            raise ContextPackError('contextBindingMismatch')
        projection=frame.projection
        if projection is not None:
            readmit_feedback(projection['originalArguments'].get('validation_feedback'),workflow._feedback_catalog)
            from .projection import FrozenCheckContext,validation_exposures
            from .authorization import ExposureBindings
            expected_private=validation_exposures(bindings,FrozenCheckContext.from_dict(
                projection['controllerValidationContext']).to_check_context()).union(ExposureBindings.from_snapshot(frame.candidates.snapshot))
            if encode(frame.validation_bindings)!=encode(expected_private.to_dict()):
                raise ContextPackError('contextBindingMismatch')
        alias=workflow.context_pack_for(entry['step'])
        if alias is None or encode(frame.candidates.spec.to_dict())!=encode(bindings.specs[alias].to_dict()):
            raise ContextPackError('contextBindingMismatch')
        if (frame.invocation_id!=aid or projection is None or projection['step']!=entry['step']
                or projection['originalArgumentsDigest']!=entry['arguments_sha256']
                or frame.candidates.snapshot.scope_binding.to_dict()!=side['scope']):
            raise ContextPackError('contextBindingMismatch')
        expected={'pending':{'prepared','dispatched'},'complete':{'adopted'},'abandoned':{'abandoned'}}[entry['status']]
        if frame.stage not in expected or frame.receipt_identity!=entry['receipt_sha256']: raise ContextPackError('contextBindingMismatch')
        if state['pending'] is not None and state['pending']['id']==aid:
            if encode(projection['originalArguments'])!=encode(state['pending']['arguments']): raise ContextPackError('contextBindingMismatch')
    for binding in state['bindings'].values():
        expected=output_pack_binding(side['attempts'][binding['id']])
        if any(encode(binding[k])!=encode(v) for k,v in expected.items()): raise ContextPackError('contextBindingMismatch')


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
    packet=seal(dict(version=3 if state['version']==4 else 2,recordType='workflowReceipt',run_id=state['run_id'],**pending,
        result=asdict(turn.result) if result is None else result,events=_owned(events),contextPack=frame.to_dict(),
        contextPackResult=dict(evidence=turn.evidence.to_dict(),rules=rule_receipt(turn),
            finalContextReport=turn.context_report.to_dict() if turn.context_report is not None else None,
            contextWork=turn.context_work.to_dict() if turn.context_work is not None else None)))
    if state['version']==4:
        from ..tool_contracts import freeze_tool_contract_receipt,invocation_scope
        from prosaic_runtime import Result
        payload=Result(**packet['result'])
        packet=seal({**packet,'toolContractV1':freeze_tool_contract_receipt(workflow,
            invocation_scope(state,aid,pending['step'],workflow),payload,turn=turn,frame=frame)})
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
    runtime_metadata=dict(packet['result']['metadata'])
    runtime_metadata.pop('workflow_rules_v2',None)
    limits=frozen['bindings']['limits']
    if (len(encode(runtime_metadata))>limits['max_metadata_bytes']
            or len(encode(evidence))>limits['max_evidence_bytes']
            or _nodes(runtime_metadata)>limits['max_json_nodes'] or _nodes(evidence)>limits['max_json_nodes']):
        raise ContextPackError('contextSnapshotLimit')
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
        metadata={'metadata':packet['result']['metadata'],**proof}
        tool_nodes=sum((amount+1)//2+1+TOOL_ENVELOPE_NODES for amount in bound.tool_result_bytes)
        if (len(packet['result']['stdout'].encode())+len(packet['result']['stderr'].encode())>bound.output_bytes
                or len(encode(metadata))>bound.metadata_bytes+bound.tool_result_reservation_bytes
                or _nodes(metadata)>bound.metadata_nodes+tool_nodes
                or len(encode(packet['events']))>bound.event_bytes
                or _nodes(packet['events'])>bound.event_nodes
                or len(encode(packet))>bound.receipt_bytes or _nodes(packet)>bound.receipt_nodes):
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
