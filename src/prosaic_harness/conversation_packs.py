"""Host-owned pack admission on the existing conversation transaction boundary."""
import time
from .context_packs import (ContextPackCandidates,ContextPacker,ExposureBindings,ContextUse,
    ContextPackReader,ContextScope)
from .context_packs.authorization import authorize_context_use
from .context_packs.codec import ContextPackError,encode,digest
from .context_packs.records import ContextPackInvocation
from .context_packs.sources import source_identity
from .conversation_errors import ConversationError


def admit_candidates(chat,value):
    bindings=chat.bindings.context_packs
    if bindings is None or type(value) is not ContextPackCandidates: raise ContextPackError('invalidContextPack')
    candidates=ContextPackCandidates.from_dict(value.to_dict())
    if candidates.snapshot.scope_binding.to_dict()!=chat.scope.to_dict(): raise ContextPackError('contextScopeMismatch')
    if not any(spec.to_dict()==candidates.spec.to_dict() for spec in bindings.specs.values()):
        raise ContextPackError('contextBindingMismatch')
    for source in candidates.snapshot.sources:
        if source.alias not in bindings.sources or source.source_identity!=source_identity(bindings.sources[source.alias]):
            raise ContextPackError('contextBindingMismatch')
    return candidates


def history_exposures(chat,state,*,before_sequence=None):
    bindings=chat.bindings.context_packs
    if bindings is None: return None
    result=ExposureBindings(bindings.scope)
    for sequence,value in state['contextPacks']['turnExposures'].items():
        if before_sequence is not None and int(sequence)>=before_sequence: continue
        if value is not None: result=result.union(ExposureBindings.from_dict(value))
    return result


def authorize_history(chat,state,operation_id,*,purpose='historyReuse',deadline=None,before_sequence=None):
    if purpose=='historyReuse' and before_sequence is None and state['pending'] is not None:
        before_sequence=state['pending']['turnSequence']
    exposures=history_exposures(chat,state,before_sequence=before_sequence)
    if exposures is not None:
        authorize_context_use(chat.bindings.context_packs,ContextUse(purpose,scope=exposures.scope,
            session_id=state['sessionId'],operation_id=operation_id,exposures=exposures,
            deadline=None if purpose=='retainedRead' else deadline or time.monotonic()+chat.bindings.run_policy.timeout_s))
    return exposures


def authorize_private_view(chat,state):
    bindings=chat.bindings.context_packs
    if bindings is None: return
    for aid,value in state['contextPacks']['attempts'].items():
        if value is None: continue
        frame=ContextPackInvocation.from_dict(value)
        # A private checkpoint includes full snapshots even for guard-free turns.
        exposures=ExposureBindings.from_snapshot(frame.candidates.snapshot)
        authorize_context_use(bindings,ContextUse('retainedRead',scope=bindings.scope,session_id=state['sessionId'],
            operation_id=aid,exposures=exposures,
            validation_input={'profile':'conversation-retained-state-v1','digest':digest(state)}))


def authorize_pack(chat,state,frame,*,deadline):
    bindings=chat.bindings.context_packs;pack=frame.prepared_pack
    authorize_context_use(bindings,ContextUse.for_pack('invocation',pack,operation_id=frame.invocation_id,
        session_id=state['sessionId'],deadline=deadline))
    frozen=frame.frozen_input.to_dict()
    if frame.validation_bindings is not None:
        authorize_context_use(bindings,ContextUse('validation',scope=bindings.scope,operation_id=frame.invocation_id,
            session_id=state['sessionId'],deadline=deadline,exposures=ExposureBindings.from_dict(frame.validation_bindings),
            validation_input={'profile':frozen['authoritativeInputProfile'],'digest':frozen['inputViews']['authoritative']['digest']}))


def prepare_pack(chat,state,turn,candidates):
    bindings=chat.bindings.context_packs;aid=turn['_packInvocationId']
    deadline=time.monotonic()+chat.bindings.run_policy.timeout_s
    richest=ContextPacker().select(candidates,0,digest(candidates.variants[0]))
    authorize_context_use(bindings,ContextUse.for_pack('invocation',richest,operation_id=aid,
        session_id=state['sessionId'],deadline=deadline))
    options={}
    if chat.bindings._guards:
        snapshot=candidates.snapshot.to_dict()
        options.update(authoritative_input_data=snapshot,authoritative_input_profile='context-pack-snapshot-v1')
        authorize_context_use(bindings,ContextUse('validation',scope=bindings.scope,operation_id=aid,
            session_id=state['sessionId'],deadline=deadline,exposures=ExposureBindings.from_snapshot(candidates.snapshot),
            validation_input={'profile':'context-pack-snapshot-v1','digest':digest(snapshot)}))
    from prosaic_runtime import ConversationMessage
    from .session_contracts import history_of
    rt=chat.bindings.runtime(lifecycle=chat.lifecycle)
    options.update(message=turn['message'],history=tuple(ConversationMessage.from_dict(m) for m in
        history_of(state,before_sequence=turn['sequence'])),policy=chat.bindings.run_policy,
        limits=chat.bindings.turn_limits,workspace=chat.bindings._workspace,input_profile='context-pack-input-v1')
    roots=[{'contextPack':envelope} for envelope in candidates.variants]
    if chat.bindings.tool_contracts is not None:
        from .context_packs.tool_contracts import prepare_pack_contract,CONVERSATION_PROFILE
        from .session_tool_contracts import scope_for
        factory=None
        if turn.get('_retainedReferences'):
            from .session_tool_contracts import invocation_bindings
            _,models=invocation_bindings(chat,state,aid,references=turn['_retainedReferences'])
            roots=[{**root,'retainedEvidence':models} for root in roots]
            factory=lambda adapter:invocation_bindings(chat,state,aid,references=turn['_retainedReferences'],pack_adapter=adapter)[0]
        options['input_profile']=CONVERSATION_PROFILE
        prepared,pack,mapping,adapter=prepare_pack_contract(rt,chat.bindings.agent,candidates,roots,
            bindings=bindings,contracts=chat.bindings.tool_contracts,scope=scope_for(state,aid,namespace=chat.bindings.readmit()['operationNamespace']),
            options=options,context_policy=chat.bindings.context_policy,token_counters=chat.bindings.token_counters,
            deadline=deadline,session_id=state['sessionId'],binding_factory=factory)
        turn['_contractPackMapping']=mapping
    elif chat.bindings.context_policy is not None:
        prepared=rt.prepare_turn_variants(chat.bindings.agent,input_data_variants=roots,
            context_policy=chat.bindings.context_policy,token_counters=chat.bindings.token_counters,**options)
    else:
        prepared=rt.prepare_turn(chat.bindings.agent,input_data=roots[-1],**options)
    return rt,prepared


def frame_for(chat,state,turn,prepared,aid,*,previous=None):
    if previous is None:
        candidates=turn['_contextPack']
        index=prepared.input_variant_selection.to_dict()['selectedIndex'] if chat.bindings.context_policy else len(candidates.variants)-1
        mapping=turn.get('_contractPackMapping',list(range(len(candidates.variants))) if chat.bindings.context_policy else [index])
        if chat.bindings.tool_contracts is not None:index=mapping[0]
        pack=ContextPacker().select(candidates,index,digest(candidates.variants[index]))
        inherited=history_exposures(chat,state,before_sequence=turn['sequence'])
        private=ExposureBindings.from_snapshot(candidates.snapshot) if chat.bindings._guards else None
    else:
        candidates=previous.candidates;pack=previous.prepared_pack;mapping=previous.runtime_input_mapping
        inherited=ExposureBindings.from_dict(previous.to_dict()['initialExposureBindings'])
        private=ExposureBindings.from_dict(previous.validation_bindings) if previous.validation_bindings else None
    return ContextPackInvocation.from_prepared(aid,candidates,pack,prepared,runtime_input_mapping=mapping,
        history_exposures=inherited,validation_bindings=private,
        **({'execution_epoch':previous.execution_epoch+1} if previous is not None and chat.bindings.tool_contracts is not None else {}))


def tool_reservations(chat):
    material=chat.bindings.readmit();policy=chat.bindings.run_policy
    largest=max([material['tools'][name]['max_result_bytes'] if name in material['tools'] else chat.bindings.policy.max_input_bytes
        for name in policy.allowed_tools] or [0])
    return [largest]*policy.max_tool_calls if largest else []


def reader_for(chat,pack):
    if not pack.envelope['index']: return None
    from .context_packs.reader import NAME
    tool=chat.bindings._tools.get(NAME);reader=getattr(getattr(tool,'handler',None),'__self__',None)
    if type(reader) is not ContextPackReader or NAME not in chat.bindings.run_policy.allowed_tools:
        raise ContextPackError('contextCapabilityMissing')
    return reader


def pack_errors(method):
    from functools import wraps
    @wraps(method)
    def converted(*args,**kwargs):
        try: return method(*args,**kwargs)
        except ContextPackError as exc: raise ConversationError(exc.code) from None
    return converted
