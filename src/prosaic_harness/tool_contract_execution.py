"""Role-aware workflow calls on the existing lease and receipt-first adoption path."""
from dataclasses import asdict, replace
import uuid

from prosaic_runtime import TurnLimits, TurnAdmissionError
from .contracts import seal, validate_receipt
from .session_codec import encode, decode
from .tool_contracts import invocation_scope, freeze_tool_contract_receipt, has_packs
from .workflow import digest
from .workflow_rules import compiled, facts, result_with_proof
from .context_packs.workflow_records import storage_policy


def _workspace(controller, policy):
    from prosaic_runtime.policy import BUILTIN_TOOLS
    return controller._cwd if controller._admission is None or policy.allowed_tools & BUILTIN_TOOLS else None


def execute_step(controller, state, name, step, arguments):
    workflow, caps = controller.workflow, storage_policy(controller.workflow)
    aid = uuid.uuid4().hex
    scope = invocation_scope(state, aid, name, workflow)
    policy = controller._invocation_policy(state, name, step)
    if controller._admission is None:
        limits = workflow.definition['limits']
        policy = replace(policy, max_provider_requests=limits['max_provider_requests_per_invocation'],
            max_tool_calls=limits['max_tool_calls_per_invocation'])
    binding = workflow._tool_contracts.bind(scope, citations=step['kind'] != 'tool')
    prepared = None
    if step['kind'] != 'tool':
        try:
            prepared = controller.runtime.prepare_turn(workflow.artifacts[name],
                message='Execute the current workflow step using inputData.workflow.', input_data=facts(name, arguments),
                input_profile='workflow-tool-contract-input-v1', policy=policy,
                limits=TurnLimits(max_input_bytes=caps.max_invocation_bytes, max_user_bytes=caps.max_invocation_bytes,
                    max_assistant_bytes=min(caps.max_output_bytes, 65536), max_turn_bytes=caps.max_receipt_bytes,
                    max_metadata_bytes=caps.max_metadata_bytes, max_event_bytes=caps.max_event_bytes,
                    max_json_depth=min(64, caps.max_json_depth), max_json_nodes=caps.max_json_nodes),
                workspace=_workspace(controller,policy), tool_contract_bindings=binding)
        except (TurnAdmissionError, ValueError, TypeError):
            return controller._block(state, 'invocation_limit')
    state['calls'] += 1
    state['attempt'] += 1
    state['pending'] = dict(id=aid, step=name, arguments_sha256=digest(arguments), arguments=arguments)
    state['invocations'].append(dict(id=aid, step=name, arguments_sha256=digest(arguments), status='pending',
        token_usage=None, receipt_sha256=None))
    state['toolContractV1']['attempts'][aid] = dict(version=1, scope=asdict(scope),
        frozenInput=prepared.export_frozen_input().to_dict() if prepared is not None else None, dispatched=False)
    if has_packs(state):
        state['contextPacks']['attempts'][aid] = None
        state['contextPacks']['reservations'][aid] = None
    controller._event(state, 'invocation', attempt_id=aid, call=state['calls'])
    controller._save(state)
    if state['status'] == 'blocked': return state
    return execute_prepared(controller, state, prepared, binding, policy)


def resume_prepared(controller,state):
    pending=state['pending'];aid,name=pending['id'],pending['step']
    record=state['toolContractV1']['attempts'][aid]
    if record is None or record['dispatched']:
        raise ValueError('tool contract work may already have started')
    step=controller.workflow.definition['steps'][name]
    scope=invocation_scope(state,aid,name,controller.workflow)
    binding=controller.workflow._tool_contracts.bind(scope,citations=step['kind']!='tool')
    policy=controller._invocation_policy(state,name,step)
    prepared=None
    if record['frozenInput'] is not None:
        frozen=record['frozenInput']
        policy=replace(policy,timeout_s=frozen['bindings']['policy']['timeout_s'])
        prepared=controller.runtime.restore_turn(controller.workflow.artifacts[name],frozen_input=frozen,
            policy=policy,limits=TurnLimits(**frozen['bindings']['limits']),workspace=_workspace(controller,policy),
            tool_contract_bindings=binding)
    state.update(status='running',reason=None)
    controller._save(state)
    return execute_prepared(controller,state,prepared,binding,policy)


def execute_prepared(controller, state, prepared, binding, policy):
    workflow, caps = controller.workflow, storage_policy(controller.workflow)
    pending = state['pending']; aid, name = pending['id'], pending['step']
    step = workflow.definition['steps'][name]
    events, event_bytes = [], 2
    event_failure = False
    def record(event):
        nonlocal event_failure, event_bytes
        try:
            event = decode(encode(event, maximum=caps.max_event_bytes, nodes=caps.max_json_nodes))
            if type(event) is not dict or type(event.get('event')) is not str: raise ValueError()
        except (ValueError, TypeError):
            event_failure = True
            return
        if event['event'] not in {'text_delta', 'reasoning_delta', 'text', 'progress'}:
            size = len(encode(event)) + 1
            if event_bytes + size > caps.max_event_bytes or len(events) >= 2048:
                event_failure = True
                return
            event_bytes += size
            events.append(event)
        if controller.on_event:
            controller.on_event({**event, 'step': name, 'attempt_id': aid})
    def dispatch():
        controller._check_ownership()
        state['toolContractV1']['attempts'][aid]['dispatched'] = True
        controller._save(state)
    options = dict(on_event=record, operation_context=binding.scope, tool_contract_bindings=binding,
        cancelled=lambda: event_failure or controller._runtime_cancelled(state),
        **controller._invocation_accounting(state, aid, name))
    if controller._admission and controller._admission.tool_journal is not None:
        options['tool_journal'] = controller._admission.tool_journal
    if controller._observations.observer is not None:
        options['observer'] = controller._observations.observer
    controller._check_ownership(); controller._admit()
    turn = None
    if step['kind'] == 'tool':
        dispatch()
        result = controller.runtime.run_tool(step['tool'], pending['arguments']['tool_arguments'], policy=policy,
            cwd=controller._cwd, **options)
    else:
        turn = controller.runtime.turn(prepared, on_admitted=dispatch, **options)
        result = result_with_proof(turn, name, pending['arguments'], prepared) if name in compiled(workflow) else turn.result
    controller._check_ownership()
    proof = freeze_tool_contract_receipt(workflow, binding.scope, result, turn=turn, prepared=prepared)
    payload = {key: getattr(result, key) for key in ('exit_code', 'stdout', 'stderr', 'token_usage', 'cost_usd', 'timed_out', 'metadata')}
    payload['metadata'] = {key: value for key, value in payload['metadata'].items() if key != 'tool_contract_v1'}
    if event_failure:
        payload = controller._failure_result(payload, 'event_limit')
        proof['answer']=result.stdout
    packet = seal(dict(version=4 if state['version']==5 else 3, **({'parallelToolsV1':state['parallelToolsV1']} if state['version']==5 else {}), recordType='workflowReceipt', run_id=state['run_id'], **pending,
        result=payload, events=events, contextPack=None, contextPackResult=None, toolContractV1=proof))
    validate_receipt(packet, state, pending, workflow)
    controller._bounded_document(packet, caps.max_receipt_bytes)
    controller.store.save_receipt(controller._storage_run_id, aid, packet, controller._lease)
    controller._accept(state, packet)
    return state
