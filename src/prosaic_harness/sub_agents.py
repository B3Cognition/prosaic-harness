"""Trusted specialist bindings and durable receipt correlation."""
from dataclasses import asdict, dataclass, field
from types import MappingProxyType
import time

from .session_codec import decode, digest, encode, reference


@dataclass(frozen=True)
class SubAgentRetainedUseV1:
    """Trusted current viewer and the original frozen parent invocation."""
    viewer: object
    invocation: object


@dataclass(frozen=True, init=False)
class SubAgentBindingsV1:
    """Register named delegates and independently selected, inline child packs."""
    policy: object
    pack_bindings: object
    session_token_allowance: int
    revision: str
    _tools: object = field(repr=False)
    _authorizers: tuple = field(repr=False)
    _encoded: bytes = field(repr=False)

    def __init__(self, *, specs, policy, pack_bindings, pack_names, revision, authorize_launch,
                 authorize_result, session_token_allowance, evidence=None):
        from prosaic_runtime import SubAgentPolicyV1, bind_sub_agent_tools
        from .context_packs import ContextPackBindings
        tools = bind_sub_agent_tools(specs)
        if (type(policy) is not SubAgentPolicyV1 or type(pack_bindings) is not ContextPackBindings
                or type(pack_names) is not dict or set(pack_names) != tools.keys()
                or not 1 <= len(tools) <= 8 or not callable(authorize_launch) or not callable(authorize_result)
                or type(session_token_allowance) is not int or session_token_allowance < policy.max_reported_tokens):
            raise ValueError('invalid Harness delegation bindings')
        for name in pack_names.values():
            if name not in pack_bindings.specs:
                raise ValueError('unknown specialist pack')
        for key, value in dict(policy=policy, pack_bindings=pack_bindings.frozen_copy(),
                session_token_allowance=session_token_allowance, revision=reference(revision),
                _tools=MappingProxyType(tools), _authorizers=(authorize_launch, authorize_result),
                _encoded=encode({'packNames': pack_names, 'evidence': evidence or {}}, maximum=524288)).items():
            object.__setattr__(self, key, value)

    def descriptor(self):
        return dict(version=1, revision=self.revision, policy=asdict(self.policy),
                    sessionTokenAllowance=self.session_token_allowance,
                    packBinding=self.pack_bindings.identity, sourceBinding=digest(decode(self._encoded)),
                    tools={name: tool.version for name, tool in self._tools.items()})

    def bind_tools(self, existing=None):
        tools = dict(existing or {})
        if tools.keys() & self._tools.keys():
            raise ValueError('delegate alias collision')
        return {**tools, **self._tools}

    def frame(self, artifact, scope, *, arguments=None, evidence=None, probe=False, session_id=None, run_id=None, timeout_s=10):
        from prosaic_runtime import SubAgentFrameV1
        from prosaic_runtime.policy import requested_tools
        from .context_packs import ContextPacker, ContextUse, ExposureBindings, authorize_context_use
        from .context_packs.sources import capture_sources
        from .context_packs.codec import digest as pack_digest
        source = decode(self._encoded)
        selected = requested_tools(artifact.frontmatter.get('tools')) & self._tools.keys()
        if not selected:
            return None
        projections = {}
        for name in sorted(selected):
            if probe:
                projections[name] = {'context': {}, 'sources': []}
                continue
            spec = self.pack_bindings.specs[source['packNames'][name]]
            snapshot = capture_sources(spec, arguments or {'request': {}},
                                       {**source['evidence'], **(evidence or {})}, self.pack_bindings)
            candidates = ContextPacker().compose(spec, snapshot)
            pack = ContextPacker().select(candidates, 0, pack_digest(candidates.variants[0]))
            authorize_context_use(self.pack_bindings, ContextUse.for_pack('invocation', pack,
                operation_id=scope.invocation_id, session_id=session_id, run_id=run_id,
                deadline=time.monotonic() + timeout_s))
            envelope = pack.to_dict()['envelope']
            if envelope['index']:
                raise ValueError('deferred specialist evidence is unsupported')
            refs = [entry['citationId'] or 'ctxstatus_' + pack_digest(entry)
                    for entry in ExposureBindings.from_pack(pack).entries]
            projections[name] = {'context': {'contextPack': envelope}, 'sources': refs}
        return SubAgentFrameV1(scope, self.policy, self.revision, projections)

    def access(self, check_owner):
        from prosaic_runtime import SubAgentAccessV1
        return SubAgentAccessV1(self.revision, *self._authorizers, check_owner)

    def may_reuse(self, proof, trusted_scope, purpose):
        if proof is None:
            return True
        try:
            from prosaic_runtime import InvocationScope
            use = SubAgentRetainedUseV1(trusted_scope, InvocationScope(**proof['scope']))
            return all(self._authorizers[1](entry['alias'], use,
                tuple(entry['sources']), purpose) is True for entry in proof['receipts'])
        except Exception:
            return False


def bound_frame(frozen):
    document = frozen['bindings'].get('subAgentsV1') if frozen is not None else None
    if document is None:
        return None
    from prosaic_runtime import SubAgentFrameV1
    return SubAgentFrameV1.from_dict(document)


def proof_for(frozen, result):
    frame = bound_frame(frozen)
    if frame is None:
        if getattr(result, 'sub_agent_proof', None) is not None:
            raise ValueError('unbound delegation proof')
        return None
    if result.sub_agent_proof is None:
        evidence = result.evidence.to_dict()
        if evidence['providerAttempts'] or evidence['toolAttempts'] or result.result.exit_code == 0:
            raise ValueError('delegation evidence is missing')
        return dict(version=1, frameSha256=frame.identity, scope=asdict(frame.scope), launches=0,
                    providerRequests=0, toolCalls=0, reportedTokens=0, usageComplete=True, receipts=[])
    return validate_proof(frozen, result.sub_agent_proof, result.evidence.to_dict())


def validate_proof(frozen, proof, evidence=None):
    frame = bound_frame(frozen)
    if frame is None and proof is None:
        return None
    from prosaic_runtime.sub_agents import digest as frame_digest
    if (frame is None or type(proof) is not dict or set(proof) != {
            'version', 'frameSha256', 'scope', 'launches', 'providerRequests', 'toolCalls', 'reportedTokens',
            'usageComplete', 'receipts'} or type(proof['version']) is not int or proof['version'] != 1
            or proof['frameSha256'] != frame.identity or proof['scope'] != asdict(frame.scope)
            or type(proof['usageComplete']) is not bool):
        raise ValueError('invalid delegation proof')
    for name, maximum in (('launches', frame.policy.max_delegations),
                          ('providerRequests', frame.policy.max_provider_requests), ('toolCalls', frame.policy.max_tool_calls),
                          ('reportedTokens', 2**63 - 1)):
        if type(proof[name]) is not int or not 0 <= proof[name] <= maximum:
            raise ValueError('delegation proof exceeds its allowance')
    if evidence is not None and (proof['providerRequests'] < evidence['providerAttempts']
                                 or proof['toolCalls'] < evidence['toolAttempts']):
        raise ValueError('delegation proof omits parent work')
    if type(proof['receipts']) is not list or len(proof['receipts']) > proof['toolCalls']:
        raise ValueError('invalid child receipts')
    seen = set()
    outcomes = {row['callIndex']: row for row in evidence['toolOutcomes']} if evidence is not None else None
    for row in proof['receipts']:
        if (type(row) is not dict or set(row) != {'alias', 'callIndex', 'childInvocationId', 'sources'}
                or row['alias'] not in frame.projections or type(row['callIndex']) is not int
                or not 0 <= row['callIndex'] < proof['toolCalls'] or row['callIndex'] in seen
                or row['childInvocationId'] != 'child-' + frame_digest(
                    [frame.scope.operation_namespace, frame.scope.invocation_id, row['callIndex']])
                or type(row['sources']) is not list or len(row['sources']) > 64
                or any(type(ref) is not str or not 1 <= len(ref.encode()) <= 256 for ref in row['sources'])
                or row['sources'] != sorted(set(row['sources']))):
            raise ValueError('invalid child receipt identity')
        if outcomes is not None:
            outcome = outcomes.get(row['callIndex'])
            if (outcome is None or outcome['name'] != row['alias']
                    or outcome['status'] not in {'completed','replayed'}):
                raise ValueError('child receipt does not match parent tool evidence')
            if (outcome.get('outcome', {}).get('status') == 'ok'
                    and not set(frame.projections[row['alias']]['sources']).issubset(row['sources'])):
                raise ValueError('child receipt omits a frozen source')
        seen.add(row['callIndex'])
    if outcomes is not None and any(index not in seen and outcome['name'] in frame.projections
                                    and outcome.get('outcome', {}).get('status') == 'ok'
                                    for index, outcome in outcomes.items()):
        raise ValueError('successful delegate lacks its receipt')
    return decode(encode(proof, maximum=524288))


def workflow_binding(workflow):
    binding = getattr(workflow, '_sub_agents', None)
    if binding is None:
        return {}
    selected = set(workflow.tool_descriptors) & binding._tools.keys()
    if not selected:
        return {}
    if workflow._tool_contracts is None:
        raise ValueError('workflow delegates require tool contracts')
    for name, step in workflow.definition['steps'].items():
        if step.get('tool') in selected or step.get('initial_tool') in selected:
            raise ValueError('workflow delegates require ordinary agent tool dispatch')
    caps = workflow.definition['limits']
    for local, limit in (('max_provider_requests', 'max_provider_requests_per_invocation'),
                         ('max_tool_calls', 'max_tool_calls_per_invocation'),
                         ('max_reported_tokens', 'max_tokens')):
        maximum = caps.get(limit)
        if type(maximum) is not int or getattr(binding.policy, local) > maximum:
            raise ValueError('delegation exceeds workflow allowance')
    return {'subAgentsV1': binding.descriptor()}


def reserve_workflow_frame(state, aid, frame):
    if frame is not None:
        state['subAgentsV1']['reservations'][aid] = frame.policy.max_reported_tokens


def workflow_usage(state, *, exclude=None):
    reservations = state.get('subAgentsV1', {}).get('reservations', {})
    return [reservations.get(item['id'], item['token_usage'])
            for item in state['invocations']
            if item['id'] != exclude and (item['status'] != 'pending' or item['id'] in reservations)]


def workflow_receipt_usage(receipt):
    proof = receipt.get('subAgentsV1')
    if proof is None:
        return receipt['result']['token_usage']
    return proof['reportedTokens'] if proof['usageComplete'] else None


def workflow_grant_check(controller, state):
    binding = getattr(controller.workflow, '_sub_agents', None)
    if state['version'] != 6 or binding is None:
        return lambda _purpose: True
    proofs = []
    for item in state['invocations']:
        if item['status'] != 'complete':
            continue
        packet = controller.store.load_receipt(controller._storage_run_id, item['id'])
        if packet is None or packet['sha256'] != item['receipt_sha256']:
            return lambda _purpose: False
        if packet['subAgentsV1'] is not None:
            proofs.append(packet['subAgentsV1'])
    return lambda purpose: all(binding.may_reuse(proof, binding.pack_bindings.scope, purpose)
                               for proof in proofs)


def workflow_granted(controller, state, purpose):
    return workflow_grant_check(controller, state)(purpose)
