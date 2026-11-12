"""Citations derive from selected/read captured representations, never pack indexes."""
from dataclasses import replace
import hashlib
import time

from prosaic_runtime import (EvidenceAuthorizerV1, EvidenceDraftV1, HostEvidenceImportV1,
    ToolContractBindingsV1, TurnEvidence)
from ..tool_contracts import ToolContracts
from .codec import ContextPackError, encode, decode, digest
from .selection import PreparedContextPack, project, _content_bytes
from .authorization import ExposureBindings, ContextUse, authorize_context_use
from .bindings import ContextPackBindings

MODEL_PROFILE = 'workflow-pack-citations-input-v1'
CONVERSATION_PROFILE = 'context-pack-citations-input-v1'


def _public_entry(entry, *, index=False):
    keys = {'citationId', 'contentKind', 'representation'} | ({'label', 'contentBytes'} if index else {'content'})
    return {key: value for key, value in entry.items() if key in keys}


def public_pack_input(value):
    value = decode(encode(value))
    pack = value.get('contextPack') if type(value) is dict else None
    if type(pack) is not dict or type(pack.get('items')) is not list or type(pack.get('index')) is not list:
        raise ContextPackError('contextBindingMismatch')
    pack['items'] = [_public_entry(entry) for entry in pack['items']]
    pack['index'] = [_public_entry(entry, index=True) for entry in pack['index']]
    return value


def source_locator(entry):
    # Retain the original locator in the pack receipt. The generic bounded
    # contract needs only a stable private reference back to that exact origin.
    return 'pack_' + digest({key: entry[key] for key in ('sourceIdentity', 'sourceLocator', 'itemId')})


def read_data(body):
    return {key: body[key] for key in ('citationId', 'representation', 'content', 'contentKind',
        'complete', 'nextOffset', 'continuationAvailable')}


def read_source(body):
    return EvidenceDraftV1(body['citationId'], body['sourceRevision'], source_locator(body), '/content', 'Captured context')


class PackEvidenceBindings:
    def __init__(self, pack, bindings, contracts, scope, *, deadline, session_id=None):
        if type(pack) is not PreparedContextPack or type(bindings) is not ContextPackBindings or type(contracts) is not ToolContracts:
            raise ContextPackError('contextBindingMismatch')
        pack = PreparedContextPack.from_dict(pack.to_dict())
        self.pack, self.bindings, self.contracts = pack, bindings.frozen_copy(), contracts.frozen_copy()
        self.scope, self.deadline, self.session_id = scope, deadline, session_id
        self.entries = {}
        grants = ExposureBindings.from_pack(pack)
        if grants.scope.to_dict() != bindings.scope.to_dict():
            raise ContextPackError('contextScopeMismatch')
        self.grants = grants
        generic = contracts.evidence_authorizer
        if generic is None:
            # Event-only adoption does not require evidence registration or
            # change legacy reader return types.
            self.runtime_bindings=contracts.bind(scope)
            return
        imports = []
        for item in pack.envelope['items']:
            grant = next(entry for entry in grants.entries if entry['citationId'] == item['citationId'] and entry['disclosure'] == 'inline')
            source = EvidenceDraftV1(item['citationId'], grant['sourceRevision'], source_locator(grant), '', grant['sourceAlias'])
            imported = HostEvidenceImportV1(scope, source, evidence_id=item['citationId'], origin_kind='contextPack',
                origin_receipt_sha256=pack.pack_identity, model_view=_public_entry(item),
                content_pointer='/content', reference_pointer='/citationId')
            self.entries[(source.source_key, source.selector, imported.to_dict()['contentSha256'])] = grant
            imports.append(imported)
        identity = 'pack_' + digest(dict(host=generic.to_dict(), pack=bindings.authorizer.descriptor()))
        self.runtime_bindings = ToolContractBindingsV1(contracts.identity, contracts.version, scope,
            evidence_authorizer=EvidenceAuthorizerV1(identity, '1', self.authorize),
            display_authorizer=contracts.display_authorizer, citations=contracts.citations,
            retained=tuple(imports), limits=contracts.limits)

    def authorize(self, use):
        try:
            self.contracts.descriptor(); self.bindings.readmit()
            if use.scope != self.scope or self.contracts.evidence_authorizer.authorize(use) is not True:
                return False
            entry = self.entries.get((use.source_key, use.selector, use.content_sha256))
            if entry is None:
                # Other registered tool producers retain the generic host grant.
                # A claim to a pack identifier must have a captured pack origin.
                return not use.source_key.startswith('ctx_')
            if use.source_revision != entry['sourceRevision'] or use.locator != source_locator(entry):
                return False
            purpose = {'modelUse': 'invocation', 'cite': 'citation', 'retainedRead': 'retainedRead'}[use.purpose]
            exposures = ExposureBindings(self.bindings.scope, [entry])
            authorize_context_use(self.bindings, ContextUse(purpose, scope=self.bindings.scope,
                operation_id=self.scope.invocation_id, run_id=self.scope.run_id, session_id=self.session_id,
                exposures=exposures, deadline=None if purpose == 'retainedRead' else self.deadline))
            return True
        except Exception:
            return False

    def capture_read(self, body):
        body = decode(encode(body))
        grant = next((entry for entry in self.grants.entries if entry['citationId'] == body.get('citationId') and
            entry['disclosure'] == 'discoverable'), None)
        if grant is None or body.get('snapshotDigest') != self.pack.snapshot.identity or body.get('packReference') != self.pack.reference:
            raise ContextPackError('contextBindingMismatch')
        if any(body.get(key) != grant[key] for key in ('sourceAlias', 'sourceIdentity', 'sourceRevision', 'sourceLocator', 'itemId')):
            raise ContextPackError('contextBindingMismatch')
        item = next(item for item in self.pack.snapshot.to_dict()['items'] if
            item['sourceAlias'] == grant['sourceAlias'] and item['itemId'] == grant['itemId'])
        selected = project(item['content'], body['representation'])
        raw = _content_bytes(selected)
        if encode(selected) != encode(body['content']) or hashlib.sha256(raw).hexdigest() != body['contentSha256']:
            raise ContextPackError('contextBindingMismatch')
        entry = {**grant, 'disclosure': 'read', 'representation': body['representation'],
            'contentSha256': body['contentSha256'], 'contentBytes': len(raw), 'contentKind': body['contentKind']}
        if not self.grants.contains(ExposureBindings(self.bindings.scope, [entry])):
            raise ContextPackError('contextBindingMismatch')
        key = (grant['citationId'], '/content', digest(selected))
        if key not in self.entries and len(self.entries) >= self.contracts.limits.max_registry_items:
            raise ContextPackError('contextPackLimit')
        self.entries[key] = entry


def pack_evidence_bindings(frame, runtime_evidence, bindings, *, tool_contracts, scope, deadline=None, session_id=None):
    from .records import ContextPackInvocation, reader_exposures
    pack = frame if type(frame) is PreparedContextPack else ContextPackInvocation.from_dict(frame.to_dict()).prepared_pack
    result = PackEvidenceBindings(pack, bindings, tool_contracts, scope,
        deadline=deadline if deadline is not None else time.monotonic() + 60, session_id=session_id)
    if runtime_evidence is not None:
        evidence = TurnEvidence.from_dict(runtime_evidence).to_dict()
        if type(frame) is not ContextPackInvocation:
            raise ContextPackError('contextBindingMismatch')
        reader_exposures(frame, evidence)
        for outcome in evidence['toolOutcomes']:
            from .reader import NAME
            value = outcome.get('outcome', {})
            if outcome.get('name') != NAME or value.get('status') != 'ok':
                continue
            tagged = value.get('result')
            if type(tagged) is dict and tagged.get('version') == 1 and 'sources' in tagged:
                data = tagged['data']
                grant = next(entry for entry in result.grants.entries if entry['citationId'] == data['citationId'] and entry['disclosure'] == 'discoverable')
                result.capture_read({**grant, **data, 'snapshotDigest': pack.snapshot.identity, 'packReference': pack.reference,
                    'contentSha256': hashlib.sha256(_content_bytes(data['content'])).hexdigest()})
    return result


def prepare_pack_contract(runtime, artifact, candidates, roots, *, bindings, contracts, scope, options,
                          context_policy=None, token_counters=None, deadline=None, session_id=None,binding_factory=None):
    from .selection import ContextPacker
    if contracts.evidence_authorizer is not None and any(root['contextPack']['index'] for root in roots):
        from .reader import NAME
        if runtime.tool_descriptors.get(NAME,{}).get('result_contract') is None:
            raise ContextPackError('contextCapabilityMissing')
    public_roots=[public_pack_input(root) for root in roots]
    selected=len(public_roots)-1
    prepared=None
    if context_policy is not None:
        prepared=runtime.prepare_turn_variants(artifact,input_data_variants=public_roots,
            context_policy=context_policy,token_counters=token_counters,
            tool_contract_bindings=contracts.bind(scope),**options)
        selected=prepared.input_variant_selection.to_dict()['selectedIndex']
    pack=ContextPacker().select(candidates,selected,digest(candidates.variants[selected]))
    adapter=pack_evidence_bindings(pack,None,bindings,tool_contracts=contracts,scope=scope,
        deadline=deadline,session_id=session_id)
    restore={}
    if prepared is not None:
        restore=dict(context_policy=context_policy,token_counters=token_counters,
            context_selection=prepared.context_selection,context_report=prepared.context_report,
            context_work=prepared.context_work,_warn_rules=False)
    binding=adapter.runtime_bindings if binding_factory is None else binding_factory(adapter)
    prepared=runtime.prepare_turn(artifact,input_data=public_roots[selected],
        tool_contract_bindings=binding,**restore,**options)
    return prepared,pack,[selected],adapter


def resume_contract_pack(controller,state,frame,*,fresh_attempt=False):
    from dataclasses import replace
    import uuid
    from prosaic_runtime import TurnLimits,ContextPolicy,ContextSelection,ContextAssemblyReport,ContextWorkState,AuthoritativeInputLimits
    from ..tool_contracts import invocation_scope
    from .records import ContextPackInvocation
    from .projection import StepPackProjection
    from .workflow_records import reserve_workflow_pack_attempt
    from .workflow_execution import execute_prepared,reader_for_pack
    workflow=controller.workflow;pending=state['pending'];name=pending['step'];step=workflow.definition['steps'][name]
    if frame.stage not in ({'prepared','dispatched'} if fresh_attempt else {'prepared'}):
        raise ContextPackError('contextBindingMismatch')
    frozen=frame.frozen_input.to_dict();pack=frame.prepared_pack
    if not fresh_attempt and frame.context_work is not None and frame.context_work.reserved_active_micros:
        return controller._block(state,'interrupted_call')
    policy=replace(controller._invocation_policy(state,name,step),timeout_s=frozen['bindings']['policy']['timeout_s'])
    aid=uuid.uuid4().hex if fresh_attempt else frame.invocation_id
    scope=invocation_scope(state,aid,name,workflow)
    deadline=time.monotonic()+policy.timeout_s
    adapter=pack_evidence_bindings(pack,None,workflow._context_packs,tool_contracts=workflow._tool_contracts,
        scope=scope,deadline=deadline)
    from .workflow_execution import pack_workspace
    options=dict(policy=policy,limits=TurnLimits(**frozen['bindings']['limits']),workspace=pack_workspace(controller),
        tool_contract_bindings=adapter.runtime_bindings)
    from ..sub_agents import bound_frame
    delegates=bound_frame(frozen)
    if delegates is not None:
        if fresh_attempt: return controller._block(state,'interrupted_call')
        options['sub_agent_frame']=delegates
    if fresh_attempt:
        options.update(message=frozen['message'],input_data=frozen['selectedInputData'],input_profile=frozen['inputProfile'],
            authoritative_input_data=frozen['authoritativeInputData'],authoritative_input_profile=frozen['authoritativeInputProfile'])
        if frozen['authoritativeInputLimits'] is not None:
            options['authoritative_input_limits']=AuthoritativeInputLimits(**frozen['authoritativeInputLimits'])
        if 'contextPolicy' in frozen['bindings']:
            options.update(context_policy=ContextPolicy.from_dict(frozen['bindings']['contextPolicy']),token_counters=controller.token_counters,
                context_selection=ContextSelection.from_dict(frozen['contextSelection']),
                context_report=ContextAssemblyReport.from_dict(frozen['contextReport']),
                context_work=ContextWorkState.from_dict(frozen['initialContextWork']))
        prepared=controller.runtime.prepare_turn(workflow.artifacts[name],**options)
        old=frame.to_dict();old['stage']='abandoned'
        state['contextPacks']['attempts'][frame.invocation_id]=ContextPackInvocation.from_dict(old).to_dict()
        state['invocations'][-1]['status']='abandoned';state['pending']=None;state['attempt']-=1
        state.update(status='running',reason=None)
        controller._event(state,'interrupted_retry',abandoned=frame.invocation_id);controller._save(state)
        reason=controller._resource_reason(state,before_call=True)
        if reason: return controller._block(state,reason)
        if state['calls']>=workflow.definition['limits']['max_calls']: return controller._block(state,'call_limit')
        frame=ContextPackInvocation.from_prepared(aid,frame.candidates,pack,prepared,
            projection=StepPackProjection.from_dict(frame.projection),runtime_input_mapping=frame.runtime_input_mapping,
            validation_bindings=ExposureBindings.from_dict(frame.validation_bindings),execution_epoch=frame.execution_epoch+1)
        old_bound=state['contextPacks']['reservations'][old['invocationId']]
        updated=reserve_workflow_pack_attempt(state,workflow,name,pending['arguments'],frame,
            tool_result_bytes=old_bound['toolResultBytes'])
        state.clear();state.update(updated)
        controller._event(state,'invocation',attempt_id=aid,call=state['calls']);controller._save(state)
    else:
        prepared=controller.runtime.restore_turn(workflow.artifacts[name],frozen_input=frame.frozen_input,
            context_policy=controller.context_policy,token_counters=controller.token_counters,
            context_work=frame.context_work,**options)
    return execute_prepared(controller,state,prepared,frame,pack,reader_for_pack(controller,pack,policy),deadline)
