"""Pack execution on the existing Harness lease, checkpoint and receipt boundary."""
from contextlib import nullcontext
import time
import uuid
from .codec import ContextPackError,digest,encode,decode
from .selection import ContextPacker
from .sources import capture_sources
from .projection import project_step,validation_exposures
from .authorization import ContextUse,ExposureBindings,authorize_context_use
from .records import ContextPackInvocation
from .workflow_records import (reserve_workflow_pack_attempt,mark_workflow_pack_dispatch,
    checkpoint_workflow_pack_work,make_workflow_pack_receipt,storage_policy)


def retained_workflow_view(method):
    """Authorize returned views after internal effects have settled."""
    from functools import wraps
    @wraps(method)
    def viewed(controller,*args,**kwargs):
        from ..errors import HumanResponseError
        try: result=method(controller,*args,**kwargs)
        except HumanResponseError as exc:
            if controller._pack_nodes:
                from .feedback import safe_feedback
                exc.feedback=safe_feedback('humanResponseInvalid',None,1,{}).to_dict()
            raise
        state=result if type(result) is dict else result.state
        if state.get('version')==3:
            from ..validation import CheckContext
            bindings=controller.workflow._context_packs
            private=validation_exposures(bindings,CheckContext(state['current'],state['inputs'],state['outputs'],
                state['evidence'],state['bindings'],controller._human_responses(state)))
            model=ExposureBindings(bindings.scope)
            for value in state['contextPacks']['attempts'].values():
                if value is not None:
                    private=private.union(ExposureBindings.from_dict(value['validationBindings']))
                    model=model.union(ExposureBindings.from_dict(value['exposureBindings']))
            for exposures,profile in ((private,'workflow-retained-view-v1'),(model,None)):
                authorize_context_use(bindings,ContextUse('retainedRead',scope=bindings.scope,operation_id=state['run_id'],
                    run_id=state['run_id'],exposures=exposures,
                    validation_input={'profile':profile,'digest':digest(state)} if profile else None))
        return result
    return viewed


def assembly_material(controller):
    from prosaic_runtime import ContextPolicy,TokenCounterRegistry
    policy=controller.context_policy;counters=controller.token_counters
    if policy is None and counters is None: return None
    if type(policy) is not ContextPolicy or type(counters) is not TokenCounterRegistry: raise ContextPackError()
    return dict(contextPolicy=policy.to_dict(),counterDescriptor=counters.resolve(policy.counter_identity).descriptor.to_dict())


def tool_reservations(controller,policy):
    caps=storage_policy(controller.workflow)
    result_bound=max([controller.workflow.tool_descriptors[tool]['max_result_bytes'] if tool in controller.workflow.tool_descriptors
        else caps.max_invocation_bytes for tool in policy.allowed_tools] or [0])
    return [result_bound]*policy.max_tool_calls if result_bound else []


def turn_limits(controller,tool_bytes):
    from prosaic_runtime import TurnLimits
    from .capacity import TOOL_ENVELOPE_BYTES
    caps=storage_policy(controller.workflow)
    base=min(16384,caps.max_metadata_bytes//4)
    if base<128: raise ContextPackError('contextPackLimit')
    return TurnLimits(max_input_bytes=caps.max_invocation_bytes,max_user_bytes=caps.max_invocation_bytes,
        max_assistant_bytes=min(caps.max_output_bytes,65536),max_turn_bytes=caps.max_receipt_bytes,
        max_metadata_bytes=base,max_event_bytes=caps.max_event_bytes,
        max_evidence_bytes=base+sum(amount+TOOL_ENVELOPE_BYTES for amount in tool_bytes),
        max_json_depth=caps.max_json_depth,max_json_nodes=caps.max_json_nodes)


def pack_workspace(controller):
    # Native pack nodes prohibit acquisition and filesystem read roots. Their
    # ephemeral execution directory is not a durable part of the selected input.
    return None if controller._admission is not None else controller._cwd


def execute_step(controller,state,name,step,arguments):
    from prosaic_runtime import TurnLimits,InvocationScope
    from ..validation import CheckContext
    from ..workflow_rules import compiled,result_with_pack_proof
    controller._admit()
    workflow=controller.workflow;bindings=workflow._context_packs;alias=workflow.context_pack_for(name)
    caps=storage_policy(workflow)
    if state['contextPacks'].get('assemblyBindings')!=assembly_material(controller): raise ContextPackError('contextBindingMismatch')
    for dependency in step.get('optional_inputs',[]):
        if dependency in state['outputs'] and not controller._fresh(state,dependency):
            return controller._block(state,'stale_artifact')
    candidates=ContextPacker().compose(bindings.specs[alias],capture_sources(bindings.specs[alias],arguments,state['evidence'],bindings))
    context=CheckContext(name,state['inputs'],state['outputs'],state['evidence'],state['bindings'],controller._human_responses(state))
    projection=project_step(name,arguments,candidates,controller_validation_context=context,required_dependencies=step.get('inputs',[]))
    private_refs=validation_exposures(bindings,context).union(ExposureBindings.from_snapshot(candidates.snapshot))
    # Authorize each candidate before it reaches Runtime fitting/counter code.
    aid=uuid.uuid4().hex;policy=controller._invocation_policy(state,name,step)
    deadline=time.monotonic()+policy.timeout_s
    reader=None
    if any(envelope['index'] for envelope in candidates.variants):
        from .reader import ContextPackReader,NAME
        from prosaic_runtime.policy import requested_tools
        tool=workflow.custom_tools.get(NAME)
        reader=getattr(getattr(tool,'handler',None),'__self__',None)
        if (type(reader) is not ContextPackReader or NAME not in policy.allowed_tools
                or NAME not in workflow.config.allowed_tools
                or NAME not in requested_tools(workflow.artifacts[name].frontmatter.get('tools'))):
            raise ContextPackError('contextCapabilityMissing')
    richest=ContextPacker().select(candidates,0,digest(candidates.variants[0]))
    authorize_context_use(bindings,ContextUse.for_pack('invocation',richest,operation_id=aid,run_id=state['run_id'],deadline=deadline))
    # Without a counter the mandatory candidate is the only admitted input.
    index=len(candidates.variants)-1
    pack=ContextPacker().select(candidates,index,digest(candidates.variants[index]))
    authorize_context_use(bindings,ContextUse('validation',scope=bindings.scope,exposures=private_refs,
        operation_id=aid,run_id=state['run_id'],deadline=deadline,
        validation_input={'profile':projection.authoritative_input_profile,'digest':digest(projection.authoritative_input_data)}))
    tool_bytes=tool_reservations(controller,policy)
    limits=turn_limits(controller,tool_bytes)
    options=dict(message='Execute the current workflow step using inputData.workflow and inputData.contextPack.',input_profile=projection.profile,
        authoritative_input_data=projection.authoritative_input_data,authoritative_input_profile=projection.authoritative_input_profile,
        policy=policy,limits=limits,workspace=pack_workspace(controller))
    mapping=[index]
    if controller.context_policy is not None:
        prepared=controller.runtime.prepare_turn_variants(workflow.artifacts[name],input_data_variants=projection.variants,
            context_policy=controller.context_policy,token_counters=controller.token_counters,**options)
        index=prepared.input_variant_selection.to_dict()['selectedIndex']
        pack=ContextPacker().select(candidates,index,digest(candidates.variants[index]))
        mapping=list(range(len(candidates.variants)))
    else:
        prepared=controller.runtime.prepare_turn(workflow.artifacts[name],input_data=projection.variants[index],**options)
    frame=ContextPackInvocation.from_prepared(aid,candidates,pack,prepared,projection=projection,runtime_input_mapping=mapping,
        validation_bindings=private_refs)
    # Each allowed call could choose the largest granted custom result. Builtin
    # results are bounded conservatively by the complete admitted input ceiling.
    updated=reserve_workflow_pack_attempt(state,workflow,name,arguments,frame,tool_result_bytes=tool_bytes)
    state.clear();state.update(updated)
    controller._event(state,'invocation',attempt_id=aid,call=state['calls'])
    controller._save(state)
    if state['status']=='blocked': return state
    return execute_prepared(controller,state,prepared,frame,pack,reader,deadline)


def resume_prepared(controller,state,*,fresh_attempt=False):
    """Restore the selected bytes, with current host authority and saved work."""
    from dataclasses import replace
    from prosaic_runtime import TurnLimits
    controller._admit()
    workflow=controller.workflow;pending=state['pending'];name=pending['step'];step=workflow.definition['steps'][name]
    frame=ContextPackInvocation.from_dict(state['contextPacks']['attempts'][pending['id']])
    if frame.stage not in ({'prepared','dispatched'} if fresh_attempt else {'prepared'}): raise ContextPackError('contextBindingMismatch')
    if frame.context_work is not None and frame.context_work.reserved_active_micros and not fresh_attempt:
        return controller._block(state,'interrupted_call')
    if state['contextPacks'].get('assemblyBindings')!=assembly_material(controller): raise ContextPackError('contextBindingMismatch')
    frozen=frame.frozen_input.to_dict();policy=controller._invocation_policy(state,name,step)
    saved_timeout=frozen['bindings']['policy']['timeout_s']
    if saved_timeout>workflow.definition['limits']['timeout_s']: raise ContextPackError('contextBindingMismatch')
    policy=replace(policy,timeout_s=saved_timeout)
    caps=storage_policy(workflow)
    limits=turn_limits(controller,tool_reservations(controller,policy))
    prepared=controller.runtime.restore_turn(workflow.artifacts[name],frozen_input=frame.frozen_input,policy=policy,limits=limits,
        context_policy=controller.context_policy,token_counters=controller.token_counters,workspace=pack_workspace(controller),
        context_work=None if fresh_attempt else frame.context_work,fresh_attempt=fresh_attempt)
    pack=frame.prepared_pack;reader=None
    if pack.envelope['index']:
        from .reader import ContextPackReader,NAME
        tool=workflow.custom_tools.get(NAME);reader=getattr(getattr(tool,'handler',None),'__self__',None)
        if type(reader) is not ContextPackReader or NAME not in policy.allowed_tools: raise ContextPackError('contextCapabilityMissing')
    if fresh_attempt:
        from .projection import StepPackProjection
        old=frame.to_dict();old['stage']='abandoned'
        state['contextPacks']['attempts'][frame.invocation_id]=ContextPackInvocation.from_dict(old).to_dict()
        state['invocations'][-1]['status']='abandoned'
        if frame.stage=='prepared': state['invocations'][-1]['token_usage']=0
        state['pending']=None;state['attempt']-=1
        state.update(status='running',reason=None)
        controller._event(state,'interrupted_retry',abandoned=frame.invocation_id)
        controller._save(state)
        reason=controller._resource_reason(state,before_call=True)
        if reason: return controller._block(state,reason)
        if state['calls']>=workflow.definition['limits']['max_calls']: return controller._block(state,'call_limit')
        tool_bytes=state['contextPacks']['reservations'][frame.invocation_id]['toolResultBytes']
        frame=ContextPackInvocation.from_prepared(uuid.uuid4().hex,frame.candidates,pack,prepared,
            projection=StepPackProjection.from_dict(frame.projection),runtime_input_mapping=frame.runtime_input_mapping,
            validation_bindings=ExposureBindings.from_dict(frame.validation_bindings))
        updated=reserve_workflow_pack_attempt(state,workflow,name,pending['arguments'],frame,tool_result_bytes=tool_bytes)
        state.clear();state.update(updated)
        controller._event(state,'invocation',attempt_id=frame.invocation_id,call=state['calls'])
        controller._save(state)
        if state['status']=='blocked': return state
    return execute_prepared(controller,state,prepared,frame,pack,reader,time.monotonic()+policy.timeout_s)


def execute_prepared(controller,state,prepared,frame,pack,reader,deadline):
    from prosaic_runtime import InvocationScope
    from ..workflow_rules import compiled,result_with_pack_proof
    workflow=controller.workflow;bindings=workflow._context_packs;aid=frame.invocation_id
    name=state['pending']['step']
    scope=InvocationScope(aid,run_id=state['run_id'],step_id=name,
        operation_namespace=controller._admission.operation_namespace if controller._admission else None)
    def dispatch():
        controller._check_ownership()
        authorize_context_use(bindings,ContextUse.for_pack('invocation',pack,operation_id=aid,run_id=state['run_id'],deadline=deadline))
        authorize_context_use(bindings,ContextUse('validation',scope=bindings.scope,
            exposures=ExposureBindings.from_dict(frame.validation_bindings),operation_id=aid,run_id=state['run_id'],deadline=deadline,
            validation_input={'profile':frame.frozen_input.to_dict()['authoritativeInputProfile'],
                'digest':frame.frozen_input.to_dict()['inputViews']['authoritative']['digest']}))
        updated=mark_workflow_pack_dispatch(state,workflow,aid)
        state.clear();state.update(updated);controller._save(state)
    def checkpoint(work):
        controller._check_ownership()
        updated=checkpoint_workflow_pack_work(state,workflow,aid,work)
        state.clear();state.update(updated);controller._save(state)
    events=[];event_failure=False
    bound=state['contextPacks']['reservations'][aid]
    def record(event):
        nonlocal event_failure
        try:
            event=decode(encode(event,maximum=bound['eventBytes'],nodes=bound['eventNodes']))
            if type(event) is not dict or type(event.get('event')) is not str: raise ContextPackError()
        except ContextPackError:
            event_failure=True
            return
        if event.get('event')=='tool_completed' and event.get('name') in workflow.tool_descriptors:
            event={**event,'tool_version':workflow.tool_descriptors[event['name']]['version']}
        if event.get('event') not in {'text_delta','reasoning_delta','text','progress'}:
            try: encode([*events,event],maximum=bound['eventBytes'],nodes=bound['eventNodes'])
            except ContextPackError:
                event_failure=True
                return
            events.append(event)
        if controller.on_event: controller.on_event({**event,'step':name,'attempt_id':aid})
    activation=(reader.activate(scope,pack,bindings,deadline=deadline,cancelled=lambda:controller._runtime_cancelled(state))
        if reader is not None else nullcontext())
    with activation:
        turn=controller.runtime.turn(prepared,on_event=record,operation_context=scope,
            on_admitted=dispatch,context_checkpoint=checkpoint,cancelled=lambda:event_failure or controller._runtime_cancelled(state),
            **({'token_counters':controller.token_counters,'context_work':frame.context_work} if controller.context_policy is not None else {}),
            **controller._invocation_accounting(state,aid,name),
            **({'tool_journal':controller._admission.tool_journal} if controller._admission and controller._admission.tool_journal is not None else {}),
            **({'observer':controller._observations.observer} if controller._observations.observer is not None else {}))
    controller._check_ownership()
    result=result_with_pack_proof(turn,frame) if name in compiled(workflow) else turn.result
    packet=make_workflow_pack_receipt(state,workflow,turn,events=events,
        result={key:getattr(result,key) for key in ('exit_code','stdout','stderr','token_usage','cost_usd','timed_out','metadata')})
    controller.store.save_receipt(controller._storage_run_id,aid,packet,controller._lease)
    controller._accept(state,packet)
    return state
