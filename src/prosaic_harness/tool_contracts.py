"""Trusted tool contract configuration, pure admission and bounded receipt identity."""
from dataclasses import dataclass
from .session_codec import encode, decode, owned, reference

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
    if runtime is None:
        from prosaic_runtime import ProsaicRuntime
        runtime = ProsaicRuntime(workflow.config, custom_tools=workflow.custom_tools)
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
