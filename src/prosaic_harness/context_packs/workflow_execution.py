"""Pack execution on the existing Harness lease, checkpoint and receipt boundary."""
from contextlib import nullcontext
import time
import uuid
from .codec import ContextPackError,digest
from .selection import ContextPacker
from .sources import capture_sources
from .projection import project_step
from .authorization import ContextUse,authorize_context_use
from .records import ContextPackInvocation
from .workflow_records import (reserve_workflow_pack_attempt,mark_workflow_pack_dispatch,
    checkpoint_workflow_pack_work,make_workflow_pack_receipt,storage_policy)


def assembly_material(controller):
    from prosaic_runtime import ContextPolicy,TokenCounterRegistry
    policy=controller.context_policy;counters=controller.token_counters
    if policy is None and counters is None: return None
    if type(policy) is not ContextPolicy or type(counters) is not TokenCounterRegistry: raise ContextPackError()
    return dict(contextPolicy=policy.to_dict(),counterDescriptor=counters.resolve(policy.counter_identity).descriptor.to_dict())


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
    # Authorize each candidate before it reaches Runtime fitting/counter code.
    aid=uuid.uuid4().hex;policy=controller._invocation_policy(state,name,step)
    deadline=time.monotonic()+policy.timeout_s
    reader=None
    if any(slot.availability=='discoverable' for slot in bindings.specs[alias].slots):
        from .reader import ContextPackReader,NAME
        from prosaic_runtime.policy import requested_tools
        tool=workflow.custom_tools.get(NAME)
        reader=getattr(getattr(tool,'handler',None),'__self__',None)
        if (type(reader) is not ContextPackReader or NAME not in policy.allowed_tools
                or NAME not in workflow.config.allowed_tools
                or NAME not in requested_tools(workflow.artifacts[name].frontmatter.get('tools'))):
            raise ContextPackError('contextCapabilityMissing')
    for index,envelope in enumerate(candidates.variants):
        pack=ContextPacker().select(candidates,index,digest(envelope))
        authorize_context_use(bindings,ContextUse.for_pack('invocation',pack,operation_id=aid,run_id=state['run_id'],deadline=deadline))
    # Without a counter the mandatory candidate is the only admitted input.
    index=len(candidates.variants)-1
    pack=ContextPacker().select(candidates,index,digest(candidates.variants[index]))
    authorize_context_use(bindings,ContextUse.for_pack('validation',pack,operation_id=aid,run_id=state['run_id'],deadline=deadline))
    limits=TurnLimits(max_input_bytes=caps.max_invocation_bytes,max_user_bytes=caps.max_invocation_bytes,
        max_assistant_bytes=min(caps.max_output_bytes,65536),max_turn_bytes=caps.max_receipt_bytes,
        max_metadata_bytes=caps.max_metadata_bytes,max_event_bytes=caps.max_event_bytes,
        max_evidence_bytes=caps.max_metadata_bytes,max_json_depth=caps.max_json_depth,max_json_nodes=caps.max_json_nodes)
    options=dict(message='Execute the current workflow step using inputData.workflow and inputData.contextPack.',input_profile=projection.profile,
        authoritative_input_data=projection.authoritative_input_data,authoritative_input_profile=projection.authoritative_input_profile,
        policy=policy,limits=limits,workspace=controller._cwd)
    mapping=[index]
    if controller.context_policy is not None:
        prepared=controller.runtime.prepare_turn_variants(workflow.artifacts[name],input_data_variants=projection.variants,
            context_policy=controller.context_policy,token_counters=controller.token_counters,**options)
        index=prepared.input_variant_selection.to_dict()['selectedIndex']
        pack=ContextPacker().select(candidates,index,digest(candidates.variants[index]))
        mapping=list(range(len(candidates.variants)))
    else:
        prepared=controller.runtime.prepare_turn(workflow.artifacts[name],input_data=projection.variants[index],**options)
    frame=ContextPackInvocation.from_prepared(aid,candidates,pack,prepared,projection=projection,runtime_input_mapping=mapping)
    # Each allowed call could choose the largest granted custom result. Builtin
    # results are bounded conservatively by the complete admitted input ceiling.
    result_bound=max([workflow.tool_descriptors[tool]['max_result_bytes'] if tool in workflow.tool_descriptors
        else caps.max_invocation_bytes for tool in policy.allowed_tools] or [0])
    tool_reservations=[result_bound]*policy.max_tool_calls if result_bound else []
    updated=reserve_workflow_pack_attempt(state,workflow,name,arguments,frame,tool_result_bytes=tool_reservations)
    state.clear();state.update(updated)
    controller._event(state,'invocation',attempt_id=aid,call=state['calls'])
    controller._save(state)
    if state['status']=='blocked': return state
    return execute_prepared(controller,state,prepared,frame,pack,reader,deadline)


def resume_prepared(controller,state):
    """Restore the selected bytes, with current host authority and saved work."""
    from dataclasses import replace
    from prosaic_runtime import TurnLimits
    controller._admit()
    workflow=controller.workflow;pending=state['pending'];name=pending['step'];step=workflow.definition['steps'][name]
    frame=ContextPackInvocation.from_dict(state['contextPacks']['attempts'][pending['id']])
    if frame.stage!='prepared': raise ContextPackError('contextBindingMismatch')
    if state['contextPacks'].get('assemblyBindings')!=assembly_material(controller): raise ContextPackError('contextBindingMismatch')
    frozen=frame.frozen_input.to_dict();policy=controller._invocation_policy(state,name,step)
    saved_timeout=frozen['bindings']['policy']['timeout_s']
    if saved_timeout>workflow.definition['limits']['timeout_s']: raise ContextPackError('contextBindingMismatch')
    policy=replace(policy,timeout_s=saved_timeout)
    caps=storage_policy(workflow)
    limits=TurnLimits(max_input_bytes=caps.max_invocation_bytes,max_user_bytes=caps.max_invocation_bytes,
        max_assistant_bytes=min(caps.max_output_bytes,65536),max_turn_bytes=caps.max_receipt_bytes,
        max_metadata_bytes=caps.max_metadata_bytes,max_event_bytes=caps.max_event_bytes,
        max_evidence_bytes=caps.max_metadata_bytes,max_json_depth=caps.max_json_depth,max_json_nodes=caps.max_json_nodes)
    prepared=controller.runtime.restore_turn(workflow.artifacts[name],frozen_input=frame.frozen_input,policy=policy,limits=limits,
        context_policy=controller.context_policy,token_counters=controller.token_counters,workspace=controller._cwd,context_work=frame.context_work)
    pack=frame.prepared_pack;reader=None
    if any(slot.availability=='discoverable' for slot in pack.spec.slots):
        from .reader import ContextPackReader,NAME
        tool=workflow.custom_tools.get(NAME);reader=getattr(getattr(tool,'handler',None),'__self__',None)
        if type(reader) is not ContextPackReader or NAME not in policy.allowed_tools: raise ContextPackError('contextCapabilityMissing')
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
        authorize_context_use(bindings,ContextUse.for_pack('validation',pack,operation_id=aid,run_id=state['run_id'],deadline=deadline))
        updated=mark_workflow_pack_dispatch(state,workflow,aid)
        state.clear();state.update(updated);controller._save(state)
    def checkpoint(work):
        controller._check_ownership()
        updated=checkpoint_workflow_pack_work(state,workflow,aid,work)
        state.clear();state.update(updated);controller._save(state)
    events=[]
    def record(event):
        if event.get('event')=='tool_completed' and event.get('name') in workflow.tool_descriptors:
            event={**event,'tool_version':workflow.tool_descriptors[event['name']]['version']}
        if event.get('event') not in {'text_delta','reasoning_delta','text','progress'}: events.append(event)
        if controller.on_event: controller.on_event({**event,'step':name,'attempt_id':aid})
    activation=(reader.activate(scope,pack,bindings,deadline=deadline,cancelled=lambda:controller._runtime_cancelled(state))
        if reader is not None else nullcontext())
    with activation:
        turn=controller.runtime.turn(prepared,on_event=record,operation_context=scope,
            on_admitted=dispatch,context_checkpoint=checkpoint,cancelled=lambda:controller._runtime_cancelled(state),
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
