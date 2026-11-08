"""Closed invocation data; selection ownership is separate from mutable work."""
from .codec import ContextPackError,closed,decode,digest,encode,integer
from .types import _Record,_hash
from .selection import ContextPackCandidates,ContextPacker,PreparedContextPack
from .projection import StepPackProjection,MODEL_PROFILE,AUTHORITATIVE_PROFILE
from .authorization import ExposureBindings

STAGES=frozenset({'prepared','dispatched','completed','adopted','abandoned'})
FRAME_FIELDS={'version','invocationId','candidatePlan','candidateIdentity','selectedPackReference',
    'frozenInput','runtimeInputMapping','projection','initialExposureBindings','exposureBindings',
    'validationBindings','contextWork','executionEpoch','stage','receiptIdentity','resultEvidenceDigest',
    'ruleReceiptDigest','finalContextReportDigest','frozenIdentity'}


def _frozen_identity(value):
    frozen=dict(value['frozenInput'])
    for field in ('contextWork','initialContextWork','executionAttempt'): frozen.pop(field,None)
    return digest(dict(version=1,candidateIdentity=value['candidateIdentity'],
        selectedPackReference=value['selectedPackReference'],frozenInput=frozen,
        runtimeInputMapping=value['runtimeInputMapping'],projection=value['projection'],
        initialExposureBindings=value['initialExposureBindings'],validationBindings=value['validationBindings'],
        executionEpoch=value['executionEpoch']))


class ContextPackInvocation(_Record):
    @classmethod
    def from_prepared(cls,invocation_id,candidates,selected_pack,prepared,*,projection=None,
                      runtime_input_mapping=None,history_exposures=None,validation_bindings=None):
        if type(candidates) is not ContextPackCandidates or type(selected_pack) is not PreparedContextPack:
            raise ContextPackError()
        if projection is not None and type(projection) is not StepPackProjection: raise ContextPackError()
        if runtime_input_mapping is not None and type(runtime_input_mapping) not in (list,tuple): raise ContextPackError()
        if history_exposures is not None and type(history_exposures) is not ExposureBindings: raise ContextPackError()
        if validation_bindings is not None and type(validation_bindings) is not ExposureBindings: raise ContextPackError()
        from prosaic_runtime import PreparedTurn
        if type(prepared) is not PreparedTurn or not callable(getattr(prepared,'export_frozen_input',None)):
            raise ContextPackError('contextCapabilityMissing')
        frozen=prepared.export_frozen_input().to_dict()
        if runtime_input_mapping is None:
            count=len(frozen['inputVariantSelection']['candidateDigests'])
            runtime_input_mapping=(list(range(len(candidates.variants))) if count==len(candidates.variants)
                                   else [selected_pack.reference['selectedVariantIndex']])
        initial=ExposureBindings.from_pack(selected_pack)
        if history_exposures is not None: initial=initial.union(history_exposures)
        if validation_bindings is None and frozen['authoritativeInputData'] is not None:
            validation_bindings=ExposureBindings.from_snapshot(candidates.snapshot)
        document=dict(version=1,invocationId=invocation_id,candidatePlan=candidates.to_dict(),
            candidateIdentity=candidates.candidate_identity,selectedPackReference=selected_pack.reference,
            frozenInput=frozen,runtimeInputMapping=list(runtime_input_mapping),
            projection=projection.to_dict() if type(projection) is StepPackProjection else None,
            initialExposureBindings=initial.to_dict(),exposureBindings=initial.to_dict(),
            validationBindings=validation_bindings.to_dict() if type(validation_bindings) is ExposureBindings else None,
            contextWork=prepared.context_work.to_dict() if prepared.context_work is not None else None,
            executionEpoch=frozen['executionAttempt'],stage='prepared',receiptIdentity=None,resultEvidenceDigest=None,
            ruleReceiptDigest=None,finalContextReportDigest=None)
        document['frozenIdentity']=_frozen_identity(document)
        return cls.from_dict(document)

    @classmethod
    def from_dict(cls,value):
        try:
            closed(value,FRAME_FIELDS)
            data=decode(encode(value,maximum=8388608))
            if type(data['version']) is not int or data['version']!=1: raise ContextPackError()
            from ..run_store import validate_id
            validate_id(data['invocationId'])
            candidates=ContextPackCandidates.from_dict(data['candidatePlan'])
            if data['candidateIdentity']!=candidates.candidate_identity: raise ContextPackError('contextBindingMismatch')
            ref=data['selectedPackReference']
            if type(ref) is not dict: raise ContextPackError()
            selected=ContextPacker().select(candidates,ref['selectedVariantIndex'],ref['envelopeDigest'])
            if selected.reference!=ref: raise ContextPackError('contextBindingMismatch')
            from prosaic_runtime import FrozenTurnInput,ContextWorkState
            frozen=FrozenTurnInput.from_dict(data['frozenInput']).to_dict()
            mapping=data['runtimeInputMapping']
            if type(mapping) is not list or not 1<=len(mapping)<=8: raise ContextPackError()
            for index in mapping: integer(index,0,len(candidates.variants)-1)
            if len(set(mapping))!=len(mapping): raise ContextPackError()
            runtime_selection=frozen['inputVariantSelection']
            if len(mapping)!=len(runtime_selection['candidateDigests']): raise ContextPackError('contextBindingMismatch')
            selected_index=mapping[runtime_selection['selectedIndex']]
            if selected_index!=ref['selectedVariantIndex']: raise ContextPackError('contextBindingMismatch')
            if data['projection'] is None:
                if frozen['inputProfile']!='context-pack-input-v1': raise ContextPackError('contextBindingMismatch')
                roots=[{'contextPack':envelope} for envelope in candidates.variants]
                authoritative=frozen['authoritativeInputData']
                if authoritative is not None and (frozen['authoritativeInputProfile']!='context-pack-snapshot-v1' or encode(authoritative)!=encode(candidates.snapshot.to_dict())):
                    raise ContextPackError('contextBindingMismatch')
            else:
                projection=StepPackProjection.from_dict(data['projection'])
                if (projection.candidate_identity!=candidates.candidate_identity or encode(projection.spec)!=encode(candidates.spec.to_dict())
                        or projection.profile!=MODEL_PROFILE or frozen['inputProfile']!=MODEL_PROFILE):
                    raise ContextPackError('contextBindingMismatch')
                roots=projection.variants
                if len(roots)!=len(candidates.variants) or any(encode(root['contextPack'])!=encode(envelope) for root,envelope in zip(roots,candidates.variants)):
                    raise ContextPackError('contextBindingMismatch')
                authoritative=frozen['authoritativeInputData']
                if authoritative is not None and (frozen['authoritativeInputProfile']!=AUTHORITATIVE_PROFILE or encode(authoritative)!=encode(projection.authoritative_input_data)):
                    raise ContextPackError('contextBindingMismatch')
            if ([digest(roots[index]) for index in mapping]!=runtime_selection['candidateDigests']
                    or encode(frozen['selectedInputData'])!=encode(roots[selected_index])):
                raise ContextPackError('contextBindingMismatch')
            if frozen['bindings'].get('rules',{}).get('bindings') and frozen['authoritativeInputData'] is None:
                raise ContextPackError('contextBindingMismatch')
            initial=ExposureBindings.from_dict(data['initialExposureBindings'])
            current=ExposureBindings.from_dict(data['exposureBindings'])
            pack_exposure=ExposureBindings.from_pack(selected)
            if initial.scope.to_dict()!=candidates.snapshot.scope_binding.to_dict() or not initial.contains(pack_exposure) or not initial.contains(current):
                raise ContextPackError('contextBindingMismatch')
            if not current.contains(initial):
                # Child reads may be added, but the original exposure is never
                # pruned because a result or answer can derive from all of it.
                raise ContextPackError('contextBindingMismatch')
            if data['validationBindings'] is not None:
                private=ExposureBindings.from_dict(data['validationBindings'])
                if private.scope.to_dict()!=initial.scope.to_dict() or any(e['disclosure']!='validation' for e in private.entries):
                    raise ContextPackError('contextBindingMismatch')
                if not private.contains(ExposureBindings.from_snapshot(candidates.snapshot)):
                    raise ContextPackError('contextBindingMismatch')
            elif frozen['authoritativeInputData'] is not None:
                raise ContextPackError('contextBindingMismatch')
            initial_work=frozen['initialContextWork']
            if initial_work is None:
                if data['contextWork'] is not None: raise ContextPackError('contextBindingMismatch')
            else:
                work=ContextWorkState.from_dict(data['contextWork']).to_dict()
                for key in ('candidateChecks','candidateBytes','activeAssemblyMicros','checkpointSequence'):
                    if work[key]<initial_work[key]: raise ContextPackError('contextBindingMismatch')
            integer(data['executionEpoch'],1,2**31-1)
            if data['executionEpoch']!=frozen['executionAttempt']: raise ContextPackError('contextBindingMismatch')
            if type(data['stage']) is not str or data['stage'] not in STAGES: raise ContextPackError()
            complete=data['stage'] in {'completed','adopted'}
            if complete: _hash(data['resultEvidenceDigest'])
            elif any(data[k] is not None for k in ('resultEvidenceDigest','ruleReceiptDigest','finalContextReportDigest')):
                raise ContextPackError('contextBindingMismatch')
            for key in ('ruleReceiptDigest','finalContextReportDigest'):
                if data[key] is not None: _hash(data[key])
            if data['stage']=='adopted': _hash(data['receiptIdentity'])
            elif data['receiptIdentity'] is not None: raise ContextPackError('contextBindingMismatch')
            if data['frozenIdentity']!=_frozen_identity(data): raise ContextPackError('contextBindingMismatch')
            result=object.__new__(cls);result._own(data,maximum=8388608)
            return result
        except ContextPackError:
            raise
        except ImportError:
            raise ContextPackError('contextCapabilityMissing') from None
        except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,RecursionError,OverflowError):
            raise ContextPackError('contextBindingMismatch') from None

    @property
    def frozen_input(self):
        try:
            from prosaic_runtime import FrozenTurnInput
        except ImportError:
            raise ContextPackError('contextCapabilityMissing') from None
        return FrozenTurnInput.from_dict(self.to_dict()['frozenInput'])

    @property
    def candidates(self): return ContextPackCandidates.from_dict(self.to_dict()['candidatePlan'])

    @property
    def prepared_pack(self):
        ref=self.selected_pack_reference
        return ContextPacker().select(self.candidates,ref['selectedVariantIndex'],ref['envelopeDigest'])

    @property
    def context_work(self):
        from prosaic_runtime import ContextWorkState
        value=self.to_dict()['contextWork']
        return ContextWorkState.from_dict(value) if value is not None else None

    def checkpoint(self,work):
        try:
            if self.stage not in {'prepared','dispatched'} or self.context_work is None:
                raise ContextPackError('contextBindingMismatch')
            from ..session_context import validate_work_transition
            validate_work_transition(self.context_work,work)
            document=self.to_dict();document['contextWork']=work.to_dict()
            return ContextPackInvocation.from_dict(document)
        except ContextPackError:
            raise
        except (ValueError,TypeError,KeyError,AttributeError):
            raise ContextPackError('contextBindingMismatch') from None

    def mark_dispatched(self):
        if self.stage=='dispatched': return self
        if self.stage!='prepared': raise ContextPackError('contextBindingMismatch')
        value=self.to_dict();value['stage']='dispatched'
        return ContextPackInvocation.from_dict(value)

    def complete(self,result,*,exposure_bindings=None):
        try:
            from prosaic_runtime import TurnResult,TurnEvidence,ContextWorkState,ContextAssemblyReport
            if type(result) is not TurnResult or self.stage not in {'prepared','dispatched'}:
                raise ContextPackError('contextBindingMismatch')
            evidence=TurnEvidence.from_dict(result.evidence.to_dict()).to_dict()
            frozen=self.frozen_input.to_dict()
            if evidence.get('version')!=2 or evidence.get('inputViews')!=frozen['inputViews']:
                raise ContextPackError('contextBindingMismatch')
            if self.stage!='dispatched' and (evidence['providerAttempts'] or evidence['toolAttempts'] or evidence['failureCode'] is None):
                raise ContextPackError('contextBindingMismatch')
            policy=frozen['bindings']['policy']
            if evidence['providerAttempts']>policy['max_provider_requests'] or evidence['toolAttempts']>policy['max_tool_calls']:
                raise ContextPackError('contextBindingMismatch')
            from ..conversation_rules import rule_receipt
            rules=rule_receipt(result)
            declared=frozen['bindings'].get('rules',{})
            if (rules['fingerprint'] if rules else None)!=declared.get('fingerprint'):
                raise ContextPackError('contextBindingMismatch')
            if rules is not None:
                ids={b['id'] for b in declared['bindings']}
                if any(set(rules[k])-ids for k in ('evaluated','violated','fixed','faulted')):
                    raise ContextPackError('contextBindingMismatch')
                if any(set(rules[k])-set(rules['evaluated']) for k in ('violated','fixed','faulted')) or set(rules['fixed'])-set(rules['violated']):
                    raise ContextPackError('contextBindingMismatch')
                if result.result.exit_code==0 and (rules['faulted'] or {b['id'] for b in declared['bindings'] if b['stage'] in {'before_answer','final'}}-set(rules['evaluated'])):
                    raise ContextPackError('contextBindingMismatch')
            value=self.to_dict()
            if value['contextWork'] is None:
                if result.context_work is not None or result.context_report is not None:
                    raise ContextPackError('contextBindingMismatch')
                report=None
            else:
                if type(result.context_work) is not ContextWorkState or type(result.context_report) is not ContextAssemblyReport:
                    raise ContextPackError('contextBindingMismatch')
                before=value['contextWork'];after=result.context_work.to_dict()
                for key in ('candidateChecks','candidateBytes','activeAssemblyMicros','checkpointSequence'):
                    if after[key]<before[key]: raise ContextPackError('contextBindingMismatch')
                if before['reservedActiveMicros'] and after['reservedActiveMicros']<before['reservedActiveMicros']:
                    # A durable completion checkpoint must release a known
                    # slice; an outstanding unknown reservation cannot vanish
                    # merely because a result was supplied later.
                    raise ContextPackError('contextBindingMismatch')
                report=result.context_report.to_dict()
                expected={**frozen['contextReport'],'candidateChecks':after['candidateChecks'],'candidateBytes':after['candidateBytes']}
                if report!=expected: raise ContextPackError('contextBindingMismatch')
                value['contextWork']=after
            if exposure_bindings is not None:
                if type(exposure_bindings) is not ExposureBindings: raise ContextPackError()
                value['exposureBindings']=exposure_bindings.to_dict()
            value.update(stage='completed',resultEvidenceDigest=digest(evidence),
                ruleReceiptDigest=digest(rules) if rules is not None else None,
                finalContextReportDigest=digest(report) if report is not None else None)
            return ContextPackInvocation.from_dict(value)
        except ContextPackError:
            raise
        except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,RecursionError):
            raise ContextPackError('contextBindingMismatch') from None

    def adopt(self,receipt_identity):
        _hash(receipt_identity)
        if self.stage=='adopted':
            if self.receipt_identity!=receipt_identity: raise ContextPackError('contextBindingMismatch')
            return self
        if self.stage!='completed': raise ContextPackError('contextBindingMismatch')
        value=self.to_dict();value.update(stage='adopted',receiptIdentity=receipt_identity)
        return ContextPackInvocation.from_dict(value)


def upgrade_pack_session(document,scope,binding_identity):
    """Explicitly choose the v3 family for a newly created, empty session.

    Store namespace migration is a separate operation. This pure constructor
    cannot upgrade existing conversations or infer authority from a hash.
    """
    from ..session_contracts import verify_session,seal
    from .types import ContextScope
    state=verify_session(document)
    _hash(binding_identity)
    if type(scope) is not ContextScope or state['turns'] or state['attempts'] or state['pending'] is not None:
        raise ContextPackError('contextBindingMismatch')
    scope=scope.to_dict()
    if scope!=state['scope']: raise ContextPackError('contextScopeMismatch')
    state.update(version=3,contextBindings=state.get('contextBindings',{'ordinary':None,'interpretation':None}),
        contextPacks=dict(version=1,scope=scope,bindingIdentity=binding_identity,attempts={},turnExposures={},reservations={}))
    return verify_session(seal(state))


def attach_pack_attempt(state,frame,invocation_id):
    if frame is not None and type(frame) is not ContextPackInvocation: raise ContextPackError()
    side=state['contextPacks']
    side['attempts'][invocation_id]=frame.to_dict() if frame is not None else None
    side['reservations'][invocation_id]=None
    sequence=str(state['attempts'][invocation_id]['turnSequence'])
    side['turnExposures'].setdefault(sequence,None)


def reserve_pack_attempt(document,frame,*,message_id,input_data=None,interaction_ref=None,
                         purpose='ordinary',context=None,retry=False,tool_result_bytes=(),acknowledge_unknown=False):
    from ..session_contracts import reserve_attempt,seal,verify_session,_bounds
    from prosaic_runtime import ContextSelection,ContextAssemblyReport
    from .capacity import reserve_pack_capacity
    if type(frame) is not ContextPackInvocation or frame.stage!='prepared': raise ContextPackError()
    admitted=verify_session(document)
    if retry:
        if not admitted['turns']: raise ContextPackError('contextBindingMismatch')
        previous=admitted['attempts'][admitted['turns'][-1]['attempts'][-1]]
        prior=admitted['contextPacks']['attempts'][previous['invocationId']]
        if (prior is None or frame.execution_epoch!=prior['executionEpoch']+1
                or (previous['dispatchMarker'] and not previous['receiptAdopted'] and acknowledge_unknown is not True)):
            raise ContextPackError('contextBindingMismatch')
    frozen=frame.frozen_input.to_dict()
    policy=frozen['bindings']['policy']
    state=reserve_attempt(admitted,message_id=message_id,message=frozen['message'],invocation_id=frame.invocation_id,
        context_identity=frozen['contextIdentity'],encoding_version=frozen['encodingVersion'],input_bytes=frozen['inputBytes'],
        provider_allowance=policy['max_provider_requests'],tool_allowance=policy['max_tool_calls'],
        input_data=input_data,interaction_ref=interaction_ref,purpose=purpose,context=context,retry=retry,
        context_selection=ContextSelection.from_dict(frozen['contextSelection']) if frozen['contextSelection'] is not None else None,
        context_report=ContextAssemblyReport.from_dict(frozen['contextReport']) if frozen['contextReport'] is not None else None,
        context_work=frame.context_work,pack_invocation=frame)
    p=state['policy']
    # Count the retained frame in both records; terminal hashes and wrappers
    # consume the fixed failure/metadata headroom as well.
    packet={'version':3,'recordType':'receipt','contextPack':frame.to_dict(),
        'exposureBindings':frame.exposure_bindings,'completedTurn':None,'evidence':None,'result':None}
    reservation=reserve_pack_capacity(state,packet,max_state_bytes=p['maxStateBytes']-state['reservedStateBytes'],
        max_receipt_bytes=p['maxReceiptBytes'],max_json_nodes=p['maxJsonNodes']-state['reservedStateNodes'],
        family='conversation',output_bytes=p['maxAssistantBytes'],tool_result_bytes=tool_result_bytes,
        user_message=frozen['message'],provider_allowance=policy['max_provider_requests'])
    state['contextPacks']['reservations'][frame.invocation_id]=reservation.to_dict()
    state=verify_session(seal(state));_bounds(state,admission=True)
    return state


def validate_pack_attempt_context(state,attempt):
    """Correlate exact profiled data; do not reconstruct or count messages."""
    from ..session_contracts import history_of
    frame=ContextPackInvocation.from_dict(state['contextPacks']['attempts'][attempt['invocationId']])
    frozen=frame.frozen_input.to_dict()
    turn=state['turns'][attempt['turnSequence']-1]
    if (frame.invocation_id!=attempt['invocationId'] or frozen['message']!=turn['message']
            or any(attempt[k]!=frozen[k] for k in ('contextIdentity','encodingVersion','inputBytes'))
            or frozen['sourceHistoryDigest']!=digest(history_of(state,before_sequence=turn['sequence']))
            or attempt['contextSelection']!=frozen['contextSelection']
            or attempt['initialContextReport']!=frozen['contextReport']
            or attempt['contextWork']!=frame.to_dict()['contextWork']):
        raise ContextPackError('contextBindingMismatch')
    policy=frozen['bindings']['policy']
    if (attempt['providerAllowance']!=policy['max_provider_requests'] or attempt['toolAllowance']!=policy['max_tool_calls']):
        raise ContextPackError('contextBindingMismatch')
    purpose=state['contextBindings'][attempt['purpose']]
    binding=frozen['bindings']
    if purpose is None:
        if frozen['contextSelection'] is not None or 'contextPolicy' in binding: raise ContextPackError('contextBindingMismatch')
    elif (binding.get('contextPolicy')!=purpose['policy'] or binding.get('counterDescriptor')!=purpose['counter']):
        raise ContextPackError('contextBindingMismatch')
    if attempt['finalContextReport'] is not None:
        from ..session_context import validate_final_report
        from prosaic_runtime import ContextAssemblyReport
        validate_final_report(ContextAssemblyReport.from_dict(frozen['contextReport']),attempt['finalContextReport'],frame.context_work)


def validate_pack_session(state):
    from .types import ContextScope
    from .capacity import PackReservation
    side=state['contextPacks']
    closed(side,{'version','scope','bindingIdentity','attempts','turnExposures','reservations'})
    if type(side['version']) is not int or side['version']!=1: raise ContextPackError()
    _hash(side['bindingIdentity']);scope=ContextScope.from_dict(side['scope'])
    if scope.to_dict()!=state['scope']: raise ContextPackError('contextScopeMismatch')
    if any(type(side[k]) is not dict for k in ('attempts','turnExposures','reservations')): raise ContextPackError()
    if set(side['attempts'])!=set(state['attempts']) or set(side['reservations'])!=set(state['attempts']): raise ContextPackError()
    if set(side['turnExposures'])!={str(t['sequence']) for t in state['turns']}: raise ContextPackError()
    for aid,value in side['attempts'].items():
        attempt=state['attempts'][aid]
        reservation=side['reservations'][aid]
        if reservation is not None: PackReservation.from_dict(reservation)
        if value is None:
            if reservation is not None: raise ContextPackError()
            continue
        frame=ContextPackInvocation.from_dict(value)
        if reservation is None and frame.stage!='prepared': raise ContextPackError('contextSnapshotLimit')
        if frame.candidates.snapshot.scope_binding.to_dict()!=scope.to_dict(): raise ContextPackError('contextScopeMismatch')
        if (attempt['receiptAdopted']!=(frame.stage=='adopted')
                or attempt['receiptIdentity']!=frame.receipt_identity
                or (not attempt['receiptAdopted'] and frame.stage!=('dispatched' if attempt['dispatchMarker'] else 'prepared'))):
            raise ContextPackError('contextBindingMismatch')
    for sequence,value in side['turnExposures'].items():
        if value is not None:
            exposure=ExposureBindings.from_dict(value)
            if exposure.scope.to_dict()!=scope.to_dict(): raise ContextPackError('contextScopeMismatch')
        for aid in state['turns'][int(sequence)-1]['attempts']:
            frame=side['attempts'][aid]
            if frame is not None and state['attempts'][aid]['receiptAdopted']:
                if value is None or not exposure.contains(ExposureBindings.from_dict(frame['exposureBindings'])):
                    raise ContextPackError('contextBindingMismatch')


def validate_pack_receipt_context(value):
    frame=ContextPackInvocation.from_dict(value['contextPack']);frozen=frame.frozen_input.to_dict()
    if (value['contextSelection']!=frozen['contextSelection'] or value['initialContextReport']!=frozen['contextReport']
            or value['contextWork']!=frame.to_dict()['contextWork']
            or value['contextCounter']!=frozen['bindings'].get('counterDescriptor')):
        raise ContextPackError('contextBindingMismatch')
    if frame.final_context_report_digest!=(digest(value['finalContextReport']) if value['finalContextReport'] is not None else None):
        raise ContextPackError('contextBindingMismatch')


def validate_pack_receipt(value):
    exposure=value['exposureBindings']
    if exposure is not None:
        exposure=ExposureBindings.from_dict(exposure)
        if exposure.scope.to_dict()!=value['scope']: raise ContextPackError('contextScopeMismatch')
    if value['contextPack'] is None:
        if value['encodingVersion']=='conversation-turn-v3': raise ContextPackError('contextBindingMismatch')
        return
    frame=ContextPackInvocation.from_dict(value['contextPack']);frozen=frame.frozen_input.to_dict()
    validate_completed_pack_evidence(frame,value['evidence'],value.get('rules'),value['result']['exitCode']==0,
        value['finalContextReport'])
    if (frame.stage!='completed' or frame.invocation_id!=value['invocationId']
            or frame.candidates.snapshot.scope_binding.to_dict()!=value['scope']
            or any(value[k]!=frozen[k] for k in ('contextIdentity','encodingVersion'))
            or frame.result_evidence_digest!=digest(value['evidence'])
            or frame.rule_receipt_digest!=(digest(value['rules']) if 'rules' in value else None)
            or value['evidence'].get('inputViews')!=frozen['inputViews']
            or value['exposureBindings']!=frame.exposure_bindings):
        raise ContextPackError('contextBindingMismatch')


def validate_completed_pack_evidence(frame,evidence,rules,success,report):
    """Check retained proof coverage without rerunning any guard or counter."""
    frozen=frame.frozen_input.to_dict();declared=frozen['bindings'].get('rules',{})
    if (success!=(evidence['failureCode'] is None) or evidence.get('inputViews')!=frozen['inputViews']
            or (rules['fingerprint'] if rules is not None else None)!=declared.get('fingerprint')):
        raise ContextPackError('contextBindingMismatch')
    if rules is not None:
        from ..conversation_rules import validate_rule_receipt
        validate_rule_receipt(rules)
        ids={b['id'] for b in declared['bindings']}
        required={b['id'] for b in declared['bindings'] if b['stage'] in {'before_answer','final'}}
        if set(rules['evaluated'])-ids or (success and (rules['faulted'] or required-set(rules['evaluated']))):
            raise ContextPackError('contextBindingMismatch')
    initial=frozen['contextReport']
    if initial is None:
        if report is not None or frame.context_work is not None: raise ContextPackError('contextBindingMismatch')
    else:
        from ..session_context import validate_final_report
        from prosaic_runtime import ContextAssemblyReport
        validate_final_report(ContextAssemblyReport.from_dict(initial),report,frame.context_work)


def complete_pack_receipt(state,packet,result):
    value=state['contextPacks']['attempts'][packet['invocationId']]
    completed=ContextPackInvocation.from_dict(value).complete(result) if value is not None else None
    sequence=str(packet['turnSequence'])
    return {**packet,'contextPack':completed.to_dict() if completed is not None else None,
        'exposureBindings':completed.exposure_bindings if completed is not None else state['contextPacks']['turnExposures'][sequence]}


def match_pack_receipt(state,value):
    aid=value['invocationId'];before=state['contextPacks']['attempts'][aid]
    after=value['contextPack']
    if (before is None)!=(after is None): raise ContextPackError('contextBindingMismatch')
    if before is None:
        if value['exposureBindings']!=state['contextPacks']['turnExposures'][str(value['turnSequence'])]:
            raise ContextPackError('contextBindingMismatch')
        return value
    frame=ContextPackInvocation.from_dict(before);completed=ContextPackInvocation.from_dict(after)
    if frame.frozen_identity!=completed.frozen_identity: raise ContextPackError('contextBindingMismatch')
    if frame.stage=='adopted':
        if frame.receipt_identity!=value['sha256']: raise ContextPackError('contextBindingMismatch')
    elif frame.stage not in {'prepared','dispatched'}: raise ContextPackError('contextBindingMismatch')
    if not state['attempts'][aid]['dispatchMarker'] and (
            value['evidence']['providerAttempts'] or value['evidence']['toolAttempts'] or value['result']['exitCode']==0):
        raise ContextPackError('contextBindingMismatch')
    if frame.to_dict()['contextWork']!=completed.to_dict()['contextWork']:
        from ..session_context import validate_work_transition
        validate_work_transition(frame.context_work,completed.context_work)
    return value


def adopt_pack_receipt(state,value):
    """Internal mutation of the reducer's already-owned state, after matching."""
    side=state['contextPacks'];aid=value['invocationId'];sequence=str(value['turnSequence'])
    if value['contextPack'] is not None:
        side['attempts'][aid]=ContextPackInvocation.from_dict(value['contextPack']).adopt(value['sha256']).to_dict()
    exposure=value['exposureBindings']
    if exposure is not None:
        previous=side['turnExposures'][sequence]
        side['turnExposures'][sequence]=(ExposureBindings.from_dict(previous).union(ExposureBindings.from_dict(exposure)).to_dict()
            if previous is not None else exposure)


def validate_pack_session_transition(old,new):
    before,after=old['contextPacks'],new['contextPacks']
    if any(before[k]!=after[k] for k in ('version','scope','bindingIdentity')): raise ContextPackError('contextBindingMismatch')
    for aid,value in before['attempts'].items():
        following=after['attempts'][aid]
        if (value is None)!=(following is None) or before['reservations'][aid]!=after['reservations'][aid]: raise ContextPackError('contextBindingMismatch')
        if value is None: continue
        frame=ContextPackInvocation.from_dict(value);next_frame=ContextPackInvocation.from_dict(following)
        if frame.frozen_identity!=next_frame.frozen_identity: raise ContextPackError('contextBindingMismatch')
        if frame.stage=='adopted' and value!=following: raise ContextPackError('contextBindingMismatch')
    for sequence,value in before['turnExposures'].items():
        if value is not None and (after['turnExposures'][sequence] is None or not ExposureBindings.from_dict(after['turnExposures'][sequence]).contains(ExposureBindings.from_dict(value))):
            raise ContextPackError('contextBindingMismatch')


def validate_pack_storage_admission(state):
    """A transient preparation is never a durable pre-effect reservation."""
    from ..run_store import StoreCorrupt
    side=state['contextPacks']
    for aid,frame in side['attempts'].items():
        if frame is not None and side['reservations'].get(aid) is None:
            raise StoreCorrupt('context pack capacity was not reserved')


def upgrade_pack_workflow(*args,**kwargs):
    from .workflow_records import upgrade_pack_workflow as reducer
    return reducer(*args,**kwargs)


def reserve_workflow_pack_attempt(*args,**kwargs):
    from .workflow_records import reserve_workflow_pack_attempt as reducer
    return reducer(*args,**kwargs)


def make_workflow_pack_receipt(*args,**kwargs):
    from .workflow_records import make_workflow_pack_receipt as reducer
    return reducer(*args,**kwargs)


def adopt_workflow_pack_receipt(*args,**kwargs):
    from .workflow_records import adopt_workflow_pack_receipt as reducer
    return reducer(*args,**kwargs)


def mark_workflow_pack_dispatch(*args,**kwargs):
    from .workflow_records import mark_workflow_pack_dispatch as reducer
    return reducer(*args,**kwargs)


def checkpoint_workflow_pack_work(*args,**kwargs):
    from .workflow_records import checkpoint_workflow_pack_work as reducer
    return reducer(*args,**kwargs)
