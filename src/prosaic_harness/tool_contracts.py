"""Trusted tool contract configuration, pure admission and bounded receipt identity."""
from dataclasses import dataclass
from .session_codec import encode, decode, owned, reference, digest

SCHEMA_VERSIONS = dict(run=4, workflowReceipt=3, session=4, sessionReceipt=4)


@dataclass(frozen=True, init=False)
class ToolContracts:
    identity: str
    version: str
    evidence_authorizer: object
    display_authorizer: object
    citations: object
    limits: object
    _encoded: bytes

    def __init__(self, identity, version, *, evidence_authorizer=None, display_authorizer=None, citations=None, limits=None):
        from prosaic_runtime import ToolContractLimitsV1
        reference(identity); reference(version)
        for key, value in dict(identity=identity, version=version, evidence_authorizer=evidence_authorizer,
                display_authorizer=display_authorizer, citations=citations,
                limits=ToolContractLimitsV1() if limits is None else limits).items():
            object.__setattr__(self, key, value)
        object.__setattr__(self, '_encoded', encode(self._material(), maximum=65536))

    def _material(self):
        from prosaic_runtime import ToolContractBindingsV1, InvocationScope
        prototype = ToolContractBindingsV1(self.identity, self.version, InvocationScope('admission'),
            evidence_authorizer=self.evidence_authorizer, display_authorizer=self.display_authorizer,
            citations=self.citations, limits=self.limits).to_dict()
        return {key: value for key, value in prototype.items() if key not in {'scope', 'retained'}}

    def descriptor(self):
        if encode(self._material(), maximum=65536) != self._encoded:
            raise ValueError('tool contract binding drift')
        return decode(self._encoded)

    def frozen_copy(self):
        self.descriptor()
        return ToolContracts(self.identity, self.version, evidence_authorizer=self.evidence_authorizer,
            display_authorizer=self.display_authorizer, citations=self.citations, limits=self.limits)

    def bind(self, scope, *, retained=(), citations=True):
        from prosaic_runtime import ToolContractBindingsV1
        self.descriptor()
        if type(citations) is not bool:
            raise ValueError('invalid citation binding')
        return ToolContractBindingsV1(self.identity, self.version, scope,
            evidence_authorizer=self.evidence_authorizer, display_authorizer=self.display_authorizer,
            citations=self.citations if citations else None, retained=retained, limits=self.limits)


def admit_tool_contracts(runtime, descriptors, bindings, limits):
    """No authorizers, handlers, source capture, provider calls or filesystem probes."""
    if bindings is None:
        if any('result_contract' in item for item in descriptors.values()):
            raise ValueError('typed results need tool contract bindings')
        return {}
    if type(bindings) is not ToolContracts:
        raise ValueError('invalid tool contract bindings')
    declaration = bindings.descriptor()
    required = {'tool_events_v1'}
    typed = any('result_contract' in item for item in descriptors.values())
    if typed:
        required.add('tool_results_v1')
        if bindings.evidence_authorizer is None:
            raise ValueError('typed results require evidence permission')
    if bindings.citations is not None:
        required.update({'tool_results_v1', 'citations_v1', 'frozen_turn_inputs_v1'})
    if required - frozenset(getattr(runtime, 'capabilities', ())):
        raise ValueError('tool contract capability missing')
    actual = getattr(runtime, 'tool_descriptors', {})
    if any(actual.get(name) != descriptor for name, descriptor in descriptors.items()):
        raise ValueError('tool contract registry mismatch')
    caps = owned(limits)
    for key in ('max_provider_requests', 'max_tool_calls'):
        if type(caps.get(key)) is not int or caps[key] < 0:
            raise ValueError('finite tool contract caps required')
    bound = bindings.limits
    maximum_result = max([item['max_result_bytes'] for item in descriptors.values()] or [0])
    receipt = 8192 + bound.max_evidence_bytes + bound.max_citation_bytes + caps['max_tool_calls'] * (
        maximum_result * 2 + bound.max_event_bytes * 2 + 1536)
    for key in ('max_receipt_bytes', 'max_state_bytes'):
        if type(caps.get(key, 8_388_608)) is not int or caps.get(key, 8_388_608) < receipt:
            raise ValueError('tool contract receipt capacity')
    if caps.get('max_event_bytes', bound.max_event_bytes) < bound.max_event_bytes or caps.get('max_evidence_bytes', 4_194_304) < bound.max_evidence_bytes + bound.max_citation_bytes + 2048:
        raise ValueError('tool contract evidence capacity')
    return dict(version=1, bindings=declaration, capabilities=sorted(required), reservations=dict(
        receiptBytes=receipt, eventBytes=bound.max_event_bytes, evidenceBytes=bound.max_evidence_bytes,
        citationBytes=bound.max_citation_bytes))


def material(workflow, runtime=None):
    bindings = getattr(workflow, '_tool_contracts', None)
    descriptors = workflow.tool_descriptors
    if bindings is None:
        if any('result_contract' in item for item in descriptors.values()):
            raise ValueError('typed results need tool contract bindings')
        return {}
    for name,artifact in workflow.artifacts.items():
        step=workflow.definition['steps'][name]
        if (name in workflow.acquisitions or step.get('require_reads') or '{{args}}' in artifact.body or
                any('{{args}}' in resource['content'] for resource in artifact.resources)):
            raise ValueError('workflow tool contracts require role-aware steps')
    if runtime is None:
        from prosaic_runtime import ProsaicRuntime
        runtime = ProsaicRuntime(workflow.config, custom_tools=workflow.custom_tools, **workflow._rule_bindings.runtime_options())
    limits = workflow.definition['limits']
    admitted = admit_tool_contracts(runtime, descriptors, bindings, dict(
        max_provider_requests=limits.get('max_provider_requests_per_invocation'),
        max_tool_calls=limits.get('max_tool_calls_per_invocation')))
    return {'toolContractV1': admitted}


def conversation_material(runtime, descriptors, bindings, policy, run_policy, turn_limits):
    if bindings is None:
        return admit_tool_contracts(runtime, descriptors, None, {})
    return admit_tool_contracts(runtime, descriptors, bindings, dict(max_provider_requests=run_policy.max_provider_requests,
        max_tool_calls=run_policy.max_tool_calls, max_receipt_bytes=policy.max_receipt_bytes, max_state_bytes=policy.max_state_bytes,
        max_event_bytes=turn_limits.max_event_bytes, max_evidence_bytes=turn_limits.max_evidence_bytes))


def has_packs(state):
    return state.get('version') in (3, 4, 5) and type(state.get('contextPacks')) is dict


def upgrade_workflow(state, workflow):
    from .contracts import seal
    state = owned(state)
    state.update(version=4, recordType='workflow', contextPacks=state.get('contextPacks'), toolContractV1=dict(
        version=1, bindings=material(workflow)['toolContractV1'], attempts={}))
    from .parallel_tools import parallel_material
    parallel=parallel_material(workflow)
    if parallel:state.update(version=5,**parallel)
    return seal(state)


def invocation_scope(state, invocation_id, step, workflow):
    from prosaic_runtime import InvocationScope
    admission = getattr(workflow, '_admission', None)
    return InvocationScope(invocation_id, run_id=state['run_id'], step_id=step,
        operation_namespace=admission.operation_namespace if admission else None)


def validate_workflow_state(state, workflow):
    from prosaic_runtime import FrozenTurnInput
    side = state['toolContractV1']
    if (type(side) is not dict or set(side) != {'version', 'bindings', 'attempts'} or type(side['version']) is not int or
            side['version'] != 1 or side['bindings'] != material(workflow).get('toolContractV1') or type(side['attempts']) is not dict or
            set(side['attempts']) != {item['id'] for item in state['invocations']}):
        raise ValueError('invalid workflow tool contract state')
    for invocation in state['invocations']:
        record = side['attempts'][invocation['id']]
        if record is None:
            if not has_packs(state) or state['contextPacks']['attempts'].get(invocation['id']) is None:
                raise ValueError('missing tool contract attempt')
            continue
        if type(record) is not dict or set(record) != {'version', 'scope', 'frozenInput', 'dispatched'} or record['version'] != 1 or type(record['dispatched']) is not bool:
            raise ValueError('invalid tool contract attempt')
        scope = invocation_scope(state, invocation['id'], invocation['step'], workflow)
        from dataclasses import asdict
        if record['scope'] != asdict(scope): raise ValueError('foreign tool contract attempt')
        if record['frozenInput'] is not None:
            frozen = FrozenTurnInput.from_dict(record['frozenInput']).to_dict()
            if frozen['encodingVersion'] != ('conversation-turn-v5' if __import__('prosaic_harness.parallel_tools',fromlist=['parallel_policy']).parallel_policy(workflow,invocation['step']) is not None else 'conversation-turn-v4') or frozen['bindings']['toolContractV1'] != workflow._tool_contracts.bind(scope).to_dict():
                raise ValueError('tool contract input mismatch')


def freeze_tool_contract_receipt(workflow, scope, result, *, turn=None, prepared=None, frame=None):
    import hashlib
    from dataclasses import asdict
    answer_hash=hashlib.sha256(result.stdout.encode('utf-8')).hexdigest()
    completed=None
    if turn is not None and turn.completed_turn is not None:
        original=turn.completed_turn.to_dict()
        if original['messages'][-1]!={'role':'assistant','content':[{'type':'text','text':result.stdout}]}:
            raise ValueError('unexpected completed answer')
        completed=dict(version=2,messages=original['messages'][:-1],
            answerReference=dict(path='/result/stdout',sha256=answer_hash))
    document = dict(version=1, scope=asdict(scope), bindings=material(workflow)['toolContractV1'],
        frozenInput=prepared.export_frozen_input().to_dict() if prepared is not None and frame is None else None,
        frozenInputReference=dict(path='/contextPack/frozenInput', sha256=digest(
            frame.frozen_input.to_dict())) if frame is not None else None,
        evidence=turn.evidence.to_dict() if turn is not None and frame is None else None,
        evidenceReference=dict(path='/contextPackResult/evidence', sha256=digest(
            turn.evidence.to_dict())) if frame is not None else None,
        directEvidence=result.metadata.get('tool_contract_v1') if turn is None else None,
        completedTurn=completed,citations=result.metadata.get('citations_v1'),answer=None,answerSha256=answer_hash)
    return owned(document)


def validate_tool_contract_receipt(receipt, state, pending, workflow):
    import hashlib
    from dataclasses import asdict
    from prosaic_runtime import FrozenTurnInput, TurnEvidence, CompletedTurn, CitationsV1
    value = receipt['toolContractV1']
    fields = {'version', 'scope', 'bindings', 'frozenInput', 'frozenInputReference', 'evidence', 'evidenceReference', 'directEvidence', 'completedTurn',
        'citations', 'answer', 'answerSha256'}
    if type(value) is not dict or set(value) != fields or type(value['version']) is not int or value['version'] != 1:
        raise ValueError('invalid tool contract receipt')
    scope = invocation_scope(state, pending['id'], pending['step'], workflow)
    if value['scope'] != asdict(scope) or value['bindings'] != state['toolContractV1']['bindings']:
        raise ValueError('foreign tool contract receipt')
    answer=receipt_answer(receipt)
    if type(answer) is not str or value['answerSha256'] != hashlib.sha256(answer.encode()).hexdigest():
        raise ValueError('tool contract answer mismatch')
    if receipt['result']['exit_code'] == 0 and answer != receipt['result']['stdout']:
        raise ValueError('accepted answer differs from receipt')
    frozen_value,evidence_value=receipt_contract_material(receipt)
    frozen = FrozenTurnInput.from_dict(frozen_value).to_dict() if frozen_value is not None else None
    before = state['toolContractV1']['attempts'][pending['id']]
    if before is not None and before['frozenInput'] != value['frozenInput']:
        raise ValueError('tool contract selected input changed')
    if evidence_value is not None:
        evidence = TurnEvidence.from_dict(evidence_value).to_dict()
        if evidence['version'] != (4 if frozen is not None and frozen['encodingVersion']=='conversation-turn-v5' else 3) or frozen is None or evidence['toolContractV1']['bindings'] != frozen['bindings']['toolContractV1']:
            raise ValueError('tool contract execution binding mismatch')
        if evidence['toolContractV1']['bindings']['scope'] != asdict(scope) or evidence['toolContractV1']['citations'] != value['citations']:
            raise ValueError('tool contract citation binding mismatch')
        if value['directEvidence'] is not None: raise ValueError('conflicting tool evidence routes')
        if value['completedTurn'] is not None:
            complete=value['completedTurn']
            if (type(complete) is not dict or set(complete)!={'version','messages','answerReference'} or
                    type(complete['version']) is not int or complete['version']!=2 or type(complete['messages']) is not list or
                    complete['answerReference']!={'path':'/result/stdout','sha256':value['answerSha256']}):
                raise ValueError('invalid completed answer reference')
            CompletedTurn.from_dict(dict(version=1,messages=[*complete['messages'],
                {'role':'assistant','content':[{'type':'text','text':answer}]}]))
    else:
        from prosaic_runtime.tool_evidence import validate_invocation_evidence
        direct = validate_invocation_evidence(value['directEvidence'])
        if frozen is not None or value['citations'] is not None or direct['deliveries'] or value['completedTurn'] is not None:
            raise ValueError('direct tools cannot establish model delivery')
    if value['citations'] is not None and not CitationsV1.from_dict(value['citations']).verify_answer(answer):
        raise ValueError('citation answer hash mismatch')


def receipt_contract_material(receipt):
    from .session_codec import digest
    value=receipt['toolContractV1']
    result=[]
    for key,reference_key,path,section,field in (
            ('frozenInput','frozenInputReference','/contextPack/frozenInput','contextPack','frozenInput'),
            ('evidence','evidenceReference','/contextPackResult/evidence','contextPackResult','evidence')):
        data=value[key];ref=value[reference_key]
        if ref is not None:
            if data is not None or type(ref) is not dict or set(ref)!={'path','sha256'} or ref['path']!=path:
                raise ValueError('invalid receipt body reference')
            data=receipt[section][field]
            if digest(data)!=ref['sha256']: raise ValueError('receipt body reference mismatch')
        result.append(data)
    return tuple(result)


def receipt_answer(receipt):
    value=receipt['toolContractV1']['answer']
    if value is not None and type(value) is not str: raise ValueError('invalid retained answer')
    return receipt['result']['stdout'] if value is None else value
