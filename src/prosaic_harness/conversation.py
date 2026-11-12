"""Graph-free ordered conversations over public Runtime turns and SessionStore."""
from prosaic_runtime.lifecycle import ExecutionLifecycle, tracked
from dataclasses import dataclass, replace
from uuid import uuid4

from prosaic_runtime import (ConversationMessage, ProsaicArtifact, InvocationScope,
    ExecutionContext, ResolvedContext, TurnAdmissionError)
from .conversation_bindings import ConversationBindings, ConversationScope
from .conversation_errors import ConversationError, SessionNotFound, SessionAlreadyExists
from .run_store import RevisionConflict, StoreUnavailable, validate_id, validate_revision
from .session_store import SessionSnapshot
from .session_codec import encode, decode, digest, reference
from .session_contracts import (new_session, reserve_attempt, mark_dispatch, make_receipt,
    adopt_receipt, history_of, public_node_limit, mark_interrupted, match_receipt)
from .conversation_workflow import ConversationWorkflow
from .session_tool_contracts import has_packs,HistoricalEvidenceDenied
from .conversation_packs import (pack_errors,admit_candidates,authorize_history,authorize_private_view,
    prepare_pack,frame_for,tool_reservations,reader_for,authorize_pack)


@dataclass(frozen=True, init=False, repr=False)
class ConversationReply:
    _encoded: bytes
    def __init__(self, document, *, maximum=262144, depth=64, nodes=65536):
        object.__setattr__(self,'_encoded',encode(document,maximum=maximum,depth=depth,nodes=nodes))
    @property
    def document(self): return decode(self._encoded)


class Conversation(ConversationWorkflow):
    """The embedding host authenticates and authorizes every operation first."""
    def __init__(self, bindings, *, store, scope, context=None, accounting=None, observer=None, lifecycle=None):
        if type(bindings) is not ConversationBindings or type(scope) is not ConversationScope:
            raise ConversationError('bindingMismatch')
        if store.namespace!=scope.namespace: raise ConversationError('identityMismatch')
        if context is not None and type(context) not in (ExecutionContext,ResolvedContext):
            raise ConversationError('identityMismatch')
        if accounting is not None and context is None: raise ConversationError('identityMismatch')
        if context is not None and (context.application_id,context.tenant_id,context.actor_id,
                context.billing_account_id)!=(scope.application,scope.tenant,scope.actor,scope.billing_account):
            raise ConversationError('identityMismatch')
        bindings.readmit()
        if bindings.context_packs is not None and bindings.context_packs.scope.to_dict()!=scope.to_dict():
            raise ConversationError('contextScopeMismatch')
        self.lifecycle = lifecycle if lifecycle is not None else ExecutionLifecycle()
        if not isinstance(self.lifecycle, ExecutionLifecycle):
            raise TypeError("lifecycle must be an ExecutionLifecycle")
        self.bindings,self.store,self.scope=bindings,store,scope
        self.context,self.accounting,self.observer=context,accounting,observer
        if bindings.sub_agents is not None and (
                accounting is None or bindings.sub_agents.pack_bindings.scope.to_dict() != scope.to_dict()):
            raise ConversationError('identityMismatch')

    def _load(self, session_id):
        validate_id(session_id)
        snapshot=self.store.load_session(session_id,scope=self.scope)
        material=self.bindings.readmit()
        state=snapshot.state
        if state['bindingIdentity']!=self.bindings.identity or state['bindingVersion']!=self.bindings.version:
            raise ConversationError('bindingMismatch')
        if state['version'] != (6 if self.bindings.sub_agents is not None else 5 if self.bindings.run_policy.parallel_tools is not None else 4 if self.bindings.tool_contracts else 3 if self.bindings.context_packs else 2 if self.bindings.context_enabled else 1):
            raise ConversationError('bindingMismatch')
        if state['version'] in (2,3,4,5,6):
            from .session_context import binding_context
            if state['contextBindings'] != binding_context(self.bindings):
                raise ConversationError('bindingMismatch')
        if has_packs(state) and state['contextPacks']['bindingIdentity']!=self.bindings.context_packs.identity:
            raise ConversationError('contextBindingMismatch')
        if state.get('parallelToolsV1') != material.get('parallelToolsV1'):
            raise ConversationError('bindingMismatch')
        if state.get('subAgentsV1') != material.get('subAgentsV1'):
            raise ConversationError('bindingMismatch')
        if state['version'] in (4,5,6) and state['toolContractV1']['bindings']!=material['toolContractV1']: raise ConversationError('bindingMismatch')
        if (state['accounting'] is None)!=(self.context is None): raise ConversationError('identityMismatch')
        if state['accountingScope']!=self._accounting_scope(): raise ConversationError('identityMismatch')
        if self.context is not None:
            original=ResolvedContext.from_dict(state['accounting'])
            for key in ('application_id','tenant_id','billing_account_id','actor_id','project_id'):
                if getattr(self.context,key)!=getattr(original,key): raise ConversationError('identityMismatch')
            for key in ('request_id','run_id'):
                provided=getattr(self.context,key)
                if provided is not None and provided!=session_id: raise ConversationError('identityMismatch')
            for key in ('invocation_id','parent_invocation_id'):
                provided=getattr(self.context,key)
                if provided is not None and provided!=getattr(original,key): raise ConversationError('identityMismatch')
        if state['workflow'] is not None:
            self._workflow(state)  # Authorize linked reads and exact replay too.
        seen=set()
        for turn in state['turns']:
            linked=(turn['inputData'] or {}).get('workflow')
            if linked is not None:
                identity=(linked['registration'],linked['runId'])
                if identity not in seen:
                    self._workflow(state|{'workflow':linked})
                    seen.add(identity)
        return snapshot

    def _accounting_context(self, session_id):
        if self.context is None: return None
        for key in ('request_id','run_id'):
            value=getattr(self.context,key)
            if value is not None and value!=session_id: raise ConversationError('identityMismatch')
        context=replace(self.context,request_id=session_id,run_id=session_id,
            invocation_id=self.context.invocation_id or uuid4().hex)
        return (context.resolve() if type(context) is ExecutionContext else context).to_dict()

    def _accounting_scope(self):
        if self.accounting is None: return None
        try:
            return {k:reference(getattr(self.accounting,k)) for k in ('namespace','environment')}
        except (ValueError,AttributeError): raise ConversationError('identityMismatch') from None

    @tracked
    @pack_errors
    def create(self, *, session_id=None):
        if (self.bindings.context_enabled and
                'context_assembly_v1' not in getattr(self.store, 'capabilities', frozenset())):
            raise ConversationError('capabilityMissing')
        if self.bindings.context_packs and 'context_packs_v1' not in getattr(self.store,'capabilities',()):
            raise ConversationError('contextCapabilityMissing')
        if self.bindings.run_policy.parallel_tools is not None and 'parallel_tool_calls_v1' not in getattr(self.store,'capabilities',()):raise ConversationError('capabilityMissing')
        if self.bindings.tool_contracts and 'tool_contracts_v1' not in getattr(self.store,'capabilities',()):
            raise ConversationError('capabilityMissing')
        if self.bindings.sub_agents is not None and 'sub_agents_v1' not in getattr(self.store, 'capabilities', ()):
            raise ConversationError('capabilityMissing')
        sid=uuid4().hex if session_id is None else validate_id(session_id)
        self.bindings.readmit()
        with self.store.lease(sid,scope=self.scope) as lease:
            try: return self._snapshot_view(self._load(sid))
            except SessionNotFound: pass
            state=new_session(sid,self.scope,self.bindings,accounting=self._accounting_context(sid),
                              accounting_scope=self._accounting_scope())
            if self.bindings.context_packs:
                from .context_packs.records import upgrade_pack_session
                state=upgrade_pack_session(state,self.bindings.context_packs.scope,self.bindings.context_packs.identity)
            try: revision=self.store.create_session(sid,state,lease,scope=self.scope)
            except (SessionAlreadyExists,StoreUnavailable):
                # Reconcile an acknowledged/unknown creation, preserving its original context.
                return self._snapshot_view(self._load(sid))
            return self._snapshot_view(SessionSnapshot(sid,state,revision))

    def _snapshot_view(self,snapshot):
        authorize_history(self,snapshot.state,snapshot.session_id,purpose='retainedRead')
        authorize_private_view(self,snapshot.state)
        return snapshot

    def _delegation_visible(self, state, purpose, *, before_sequence=None):
        if state['version'] != 6:
            return True
        for aid, attempt in state['attempts'].items():
            if not attempt['receiptAdopted'] or (before_sequence is not None and attempt['turnSequence'] >= before_sequence):
                continue
            packet = self.store.load_receipt(state['sessionId'], aid, scope=self.scope)
            if packet is None or not self.bindings.sub_agents.may_reuse(packet['subAgentsV1'], self.scope, purpose):
                return False
        return True

    def _reply(self, snapshot, turn=None):
        state=snapshot.state
        authorize_history(self,state,snapshot.session_id,purpose='retainedRead')
        replay=turn is not None
        if replay and turn.get('inputData') and turn['inputData'].get('workflow'):
            self._workflow(state|{'workflow':turn['inputData']['workflow']})
        if turn is None and state['turns']: turn=state['turns'][-1]
        view={'version':1,'sessionId':snapshot.session_id,'revision':snapshot.revision,
              'status':'ready','pendingInteraction':None,'recoveryStatus':None}
        if turn is not None:
            view.update({key:turn[key] for key in ('messageId','status','failureCode','pendingInteraction','recoveryStatus')})
            view['turnSequence']=turn['sequence']
            if turn['answer'] is not None: view['answer']=turn['answer']
            if state['version'] in (4,5,6) and turn['attempts'] and turn['answer'] is not None:
                packet=self.store.load_receipt(snapshot.session_id,turn['attempts'][-1],scope=self.scope)
                side=packet['toolContractV1'] if packet else None
                if side and side['citations'] is not None: view['citations']=side['citations']
            if state['version'] in (2,3,4,5,6) and turn['attempts']:
                report=state['attempts'][turn['attempts'][-1]]['finalContextReport']
                if report is not None: view['contextAssembly']=report
        if not self._delegation_visible(state, 'retainedRead',
                before_sequence=turn['sequence'] + 1 if turn is not None else None):
            view.pop('answer', None)
            view.pop('citations', None)
            view.update(status='failed', failureCode='evidenceUseDenied')
        if state['workflow'] is not None and not replay:
            view['pendingInteraction']=self._interaction(state)
        p=state['policy']
        return ConversationReply(view,maximum=p['maxPublicBytes'],depth=p['maxJsonDepth']-8,
                                 nodes=public_node_limit(p))

    def retain_citation(self,session_id,invocation_id,evidence_id):
        from .session_tool_contracts import retain
        if not self._delegation_visible(self._load(session_id).state, 'retainedRead'):
            raise ConversationError('evidenceUseDenied')
        return retain(self,session_id,invocation_id,evidence_id)

    def citation_view(self,session_id,invocation_id,evidence_id):
        from .session_tool_contracts import verified,origin_receipts
        from .tool_contract_views import ToolContractViewBindings,resolve_citation_view
        if not self._delegation_visible(self._load(session_id).state, 'retainedRead'):
            raise ConversationError('evidenceUseDenied')
        receipt=verified(self,session_id,invocation_id)
        origins=origin_receipts(self,session_id,receipt.to_dict()['toolContractV1']['retainedReferences'])
        return resolve_citation_view(receipt,evidence_id,ToolContractViewBindings(self.scope,
            evidence_authorizer=self.bindings.tool_contracts.evidence_authorizer,context_packs=self.bindings.context_packs,origins=origins))

    @pack_errors
    def status(self, session_id): return self._reply(self._load(session_id))
    @pack_errors
    def history(self, session_id):
        state=self._load(session_id).state
        if not self._delegation_visible(state, 'retainedRead'):
            raise ConversationError('evidenceUseDenied')
        authorize_history(self,state,session_id,purpose='retainedRead')
        from .session_tool_contracts import authorize_tool_history,HistoricalEvidenceDenied
        try:authorize_tool_history(self,state,'retainedRead')
        except HistoricalEvidenceDenied:raise ConversationError('evidenceUseDenied') from None
        return tuple(ConversationMessage.from_dict(m) for m in history_of(state))

    def _save(self,snapshot,state,lease):
        lease.check_valid()
        self.bindings.readmit()
        revision=self.store.save_session(snapshot.session_id,state,snapshot.revision,lease,scope=self.scope)
        return SessionSnapshot(snapshot.session_id,state,revision)

    def _prepare(self, state, turn, *, purpose='ordinary', saved_attempt=None):
        data=self.bindings.readmit()
        if not self._delegation_visible(state, 'modelUse', before_sequence=turn['sequence']):
            raise ConversationError('evidenceUseDenied')
        authorize_history(self,state,turn.get('_packInvocationId',state['sessionId']),before_sequence=turn['sequence'])
        if turn.get('_contextPack') is not None:
            return prepare_pack(self,state,turn,turn['_contextPack'])
        rt=self.bindings.runtime(lifecycle=self.lifecycle)
        interpreting=purpose=='interpretation'
        phase=data['interpreter'] if interpreting else None
        if interpreting and phase is None: raise ConversationError('capabilityMissing')
        try:
            context_args={}
            context_policy=(self.bindings.interpretation_context_policy if interpreting
                            else self.bindings.context_policy)
            if context_policy is not None:
                context_args={'context_policy':context_policy,'token_counters':self.bindings.token_counters}
                if saved_attempt is not None:
                    from prosaic_runtime import ContextSelection,ContextAssemblyReport,ContextWorkState
                    context_args.update(context_selection=ContextSelection.from_dict(saved_attempt['contextSelection']),
                        context_report=ContextAssemblyReport.from_dict(saved_attempt['initialContextReport']),
                        context_work=ContextWorkState.from_dict(saved_attempt['contextWork']))
            if self.bindings.tool_contracts is not None and not interpreting:
                from .session_tool_contracts import invocation_bindings
                binding,models=invocation_bindings(self,state,turn['_packInvocationId'],references=turn.get('_retainedReferences',()))
                context_args['tool_contract_bindings']=binding
                if self.bindings.sub_agents is not None:
                    context_args['sub_agent_frame'] = self.bindings.sub_agents.frame(
                        self.bindings.agent, binding.scope, arguments={'request': turn['inputData'] or {}},
                        session_id=state['sessionId'])
                if models:
                    turn['inputData']={**(turn['inputData'] or {}),'retainedEvidence':models}
            prepared=rt.prepare_turn(ProsaicArtifact.from_inspection(phase['artifact']) if phase else self.bindings.agent,
                message=turn['message'],history=tuple(ConversationMessage.from_dict(m) for m in
                    history_of(state,before_sequence=turn['sequence'])),input_data=turn['inputData'],
                policy=self.bindings.interpretation_policy if interpreting else self.bindings.run_policy,
                limits=self.bindings.turn_limits,workspace=None if interpreting else self.bindings._workspace,
                **context_args)
            return rt,prepared
        except TurnAdmissionError as exc:
            if exc.code in {'contextLimit','inputLimit'}: raise ConversationError('contextLimit',exc.limit) from None
            if exc.code=='invalidMessage': raise ConversationError('invalidMessage',exc.limit) from None
            if exc.code=='unsupportedCapability': raise ConversationError('capabilityMissing') from None
            raise ConversationError('bindingMismatch',exc.limit) from None

    @staticmethod
    def _phase(on_event,name,snapshot,invocation_id=None):
        if on_event is not None:
            event={'event':name,'sessionId':snapshot.session_id}
            if invocation_id is not None: event['invocationId']=invocation_id
            if snapshot.state['turns']: event['turnSequence']=snapshot.state['turns'][-1]['sequence']
            on_event(event)

    @tracked
    @pack_errors
    def send(self, session_id, *, message_id, message, expected_revision,
             interaction_ref=None, on_event=None, cancelled=None,context_pack=None,retained_evidence=()):
        try:
            reference(message_id)
            if interaction_ref is not None: reference(interaction_ref)
            if type(message) is not str or not message or len(message.encode())>self.bindings.policy.max_user_bytes:
                raise ValueError()
        except (ValueError,UnicodeError): raise ConversationError('invalidMessage') from None
        from .session_tool_contracts import RetainedCitationReference,validate_refs
        if type(retained_evidence) is not tuple or any(type(ref) is not RetainedCitationReference for ref in retained_evidence):
            raise ConversationError('bindingMismatch')
        refs=[ref.to_dict() for ref in retained_evidence];validate_refs(refs)
        if refs and self.bindings.tool_contracts is None:raise ConversationError('capabilityMissing')
        candidates=admit_candidates(self,context_pack) if context_pack is not None else None
        with self.store.lease(session_id,scope=self.scope) as lease:
            snapshot=self._load(session_id)
            state=snapshot.state
            for turn in state['turns']:
                if turn['messageId']==message_id:
                    if state['version'] in (4,5,6) and turn['attempts']:
                        prior_refs=state['toolContractV1']['attempts'][turn['attempts'][0]]
                        if refs!=(prior_refs['retainedReferences'] if prior_refs else []):raise ConversationError('messageConflict')
                    prior=(state['contextPacks']['attempts'][turn['attempts'][0]]
                        if has_packs(state) and turn['attempts'] else None)
                    if (prior['candidateIdentity'] if prior else None)!=(candidates.candidate_identity if candidates else None):
                        raise ConversationError('messageConflict')
                    if (turn['message']!=message or turn['interactionRef']!=interaction_ref
                            or (turn['inputData'] or {}).get('structuredChoice') is not None):
                        raise ConversationError('messageConflict')
                    return self._reply(snapshot,turn)
            validate_revision(expected_revision)
            if expected_revision!=snapshot.revision: raise RevisionConflict()
            if state['pending'] is not None: raise ConversationError('messageConflict')
            if state['workflow'] is not None:
                if candidates is not None: raise ConversationError('contextCapabilityMissing')
                return self._send_workflow(snapshot,lease,message_id,message,interaction_ref,on_event,cancelled)
            if interaction_ref is not None: raise ConversationError('interactionStale')
            turn={'sequence':len(state['turns'])+1,'message':message,'inputData':None}
            if self.bindings.tool_contracts is not None:turn.update(_packInvocationId=uuid4().hex,_retainedReferences=refs)
            if candidates is not None: turn.update(_contextPack=candidates,_packInvocationId=uuid4().hex)
            rt,prepared=self._prepare(state,turn)
            snapshot=self._reserve(snapshot,lease,message_id,turn,prepared)
            return self._execute(snapshot,lease,rt,prepared,on_event,cancelled)

    def _reserve(self,snapshot,lease,message_id,turn,prepared, *, purpose='ordinary',interaction_ref=None,retry=False):
        state=snapshot.state
        aid=(prepared.export_frozen_input().to_dict()['bindings']['toolContractV1']['scope']['invocation_id']
            if prepared.encoding_version in ('conversation-turn-v4','conversation-turn-v5','conversation-turn-v6') else turn.get('_packInvocationId',uuid4().hex))
        context=(ResolvedContext.from_dict(state['accounting']).child(invocation_id=aid,
            run_id=snapshot.session_id,step_id='turn.'+str(turn['sequence'])+'.'+purpose).to_dict()
            if state['accounting'] is not None else None)
        policy=self.bindings.interpretation_policy if purpose=='interpretation' else self.bindings.run_policy
        from .sub_agents import bound_frame
        delegates = bound_frame(prepared.export_frozen_input().to_dict()) if prepared.encoding_version == 'conversation-turn-v6' else None
        allowance = delegates.policy if delegates is not None else policy
        context_args=({'context_selection':prepared.context_selection,
                       'context_report':prepared.context_report,'context_work':prepared.context_work}
                      if state['version'] in (2,3,4,5,6) else {})
        if prepared.encoding_version=='conversation-turn-v3' or (prepared.encoding_version in ('conversation-turn-v4','conversation-turn-v5','conversation-turn-v6') and (turn.get('_contextPack') is not None or (retry and has_packs(state) and state['contextPacks']['attempts'].get(turn['attempts'][-1]) is not None))):
            from .context_packs.records import reserve_pack_attempt,ContextPackInvocation
            previous=(ContextPackInvocation.from_dict(state['contextPacks']['attempts'][turn['attempts'][-1]]) if retry else None)
            frame=frame_for(self,state,turn,prepared,aid,previous=previous)
            reader_for(self,frame.prepared_pack)
            pending=reserve_pack_attempt(state,frame,message_id=message_id,input_data=turn['inputData'],
                interaction_ref=interaction_ref,purpose=purpose,context=context,retry=retry,
                tool_result_bytes=tool_reservations(self),acknowledge_unknown=retry,
                **({'retained_references':state['toolContractV1']['attempts'][turn['attempts'][-1]]['retainedReferences'] if retry else turn.get('_retainedReferences',())} if state['version'] in (4,5,6) else {}))
            return self._save(snapshot,pending,lease)
        pending=reserve_attempt(state,message_id=message_id,message=turn['message'],invocation_id=aid,
            context_identity=prepared.context_identity,encoding_version=prepared.encoding_version,
            input_bytes=prepared.input_bytes,provider_allowance=allowance.max_provider_requests,
            tool_allowance=allowance.max_tool_calls,input_data=turn['inputData'],interaction_ref=interaction_ref,
            purpose=purpose,context=context,retry=retry,
            **({'tool_contract_frozen':prepared.export_frozen_input().to_dict() if purpose=='ordinary' else None,
                'retained_references':(state['toolContractV1']['attempts'][turn['attempts'][-1]]['retainedReferences'] if retry and purpose=='ordinary' else turn.get('_retainedReferences',()))} if state['version'] in (4,5,6) else {}),**context_args)
        if has_packs(state):
            from .session_contracts import seal,verify_session
            inherited=authorize_history(self,state,aid,before_sequence=turn['sequence'])
            pending['contextPacks']['turnExposures'][str(turn['sequence'])]=inherited.to_dict()
            pending=verify_session(seal(pending))
        return self._save(snapshot,pending,lease)

    def _execute(self,snapshot,lease,rt,prepared,on_event,cancelled):
        aid=snapshot.state['pending']['invocationId']
        attempt=snapshot.state['attempts'][aid]
        if attempt['dispatchMarker']: raise ConversationError('messageConflict')
        context_enabled=snapshot.state['version'] in (4,5,6) or prepared.encoding_version in ('conversation-turn-v2','conversation-turn-v3','conversation-turn-v4','conversation-turn-v5','conversation-turn-v6')
        if not context_enabled:
            authorize_history(self,snapshot.state,aid)
            snapshot=self._save(snapshot,mark_dispatch(snapshot.state,aid),lease)
        ownership_error=[]
        def cancellation():
            try:
                lease.check_valid()
                self.bindings.readmit()
            except Exception as exc:
                ownership_error.append(exc)
                return True
            return bool(cancelled()) if cancelled is not None else False
        captured_events=[];event_bytes=2;events_truncated=False
        def provisional(event):
            nonlocal event_bytes,events_truncated
            lease.check_valid()
            if snapshot.state['version'] in (4,5,6) and event.get('event') in {'tool_started','tool_completed'} and 'toolEventV1' in event:
                size=len(encode(event))+1
                if event_bytes+size<=self.bindings.turn_limits.max_event_bytes and len(captured_events)<2048:
                    captured_events.append(decode(encode(event)));event_bytes+=size
                else:events_truncated=True
            if attempt['purpose']=='ordinary' and on_event is not None:
                on_event({**event,'sessionId':snapshot.session_id,'turnSequence':attempt['turnSequence'],'invocationId':aid} if snapshot.state['version'] in (4,5,6) else event)
        self.bindings.readmit()
        context_args={}
        if context_enabled:
            from .session_context import checkpoint_context_work
            def checkpoint(work):
                nonlocal snapshot
                snapshot=self._save(snapshot,checkpoint_context_work(snapshot.state,aid,work),lease)
                self._phase(on_event,'contextCheckpointSaved',snapshot,aid)
            def admitted():
                nonlocal snapshot
                if not self._delegation_visible(snapshot.state,'modelUse',before_sequence=attempt['turnSequence']):
                    raise ConversationError('evidenceUseDenied')
                if snapshot.state['version'] in (4,5,6):
                    from .session_tool_contracts import authorize_tool_history,scope_for
                    authorize_tool_history(self,snapshot.state,'modelUse',before_sequence=attempt['turnSequence'],
                        report=prepared.context_report,scope=scope_for(snapshot.state,aid,purpose=attempt['purpose'],
                            namespace=self.bindings.readmit()['operationNamespace'] if attempt['purpose']=='ordinary' else None))
                if has_packs(snapshot.state):
                    import time
                    authorize_history(self,snapshot.state,aid)
                    saved=snapshot.state['contextPacks']['attempts'][aid]
                    if saved is not None:
                        from .context_packs.records import ContextPackInvocation
                        authorize_pack(self,snapshot.state,ContextPackInvocation.from_dict(saved),deadline=time.monotonic()+self.bindings.run_policy.timeout_s)
                snapshot=self._save(snapshot,mark_dispatch(snapshot.state,aid),lease)
                self._phase(on_event,'turnAdmitted',snapshot,aid)
            context_args={'token_counters':self.bindings.token_counters,
                **({'context_checkpoint':checkpoint} if prepared.context_work is not None else {}),'on_admitted':admitted}
        try:
            from contextlib import nullcontext
            import time
            operation=InvocationScope(aid,operation_namespace=(self.bindings.readmit()['operationNamespace'] if attempt['purpose']=='ordinary' else None))
            saved=snapshot.state['contextPacks']['attempts'][aid] if has_packs(snapshot.state) else None
            reader=None;adapter=None
            if snapshot.state['version'] in (4,5,6) and attempt['purpose']=='ordinary':
                from .session_tool_contracts import invocation_bindings
                if saved is not None:
                    from .context_packs.records import ContextPackInvocation
                    from .context_packs.tool_contracts import pack_evidence_bindings
                    from .session_tool_contracts import scope_for
                    adapter=pack_evidence_bindings(ContextPackInvocation.from_dict(saved),None,self.bindings.context_packs,
                        tool_contracts=self.bindings.tool_contracts,scope=scope_for(snapshot.state,aid,namespace=self.bindings.readmit()['operationNamespace']),
                        session_id=snapshot.session_id)
                binding,_=invocation_bindings(self,snapshot.state,aid,references=snapshot.state['toolContractV1']['attempts'][aid]['retainedReferences'],pack_adapter=adapter)
                operation=binding.scope;context_args['tool_contract_bindings']=binding
                if prepared.encoding_version == 'conversation-turn-v6':
                    def owner_valid():
                        lease.check_valid()
                        return True
                    context_args['sub_agent_access'] = self.bindings.sub_agents.access(owner_valid)
            if saved is not None:
                from .context_packs.records import ContextPackInvocation
                pack=ContextPackInvocation.from_dict(saved).prepared_pack;reader=reader_for(self,pack)
            activation=reader.activate(operation,pack,self.bindings.context_packs,
                deadline=time.monotonic()+self.bindings.run_policy.timeout_s,cancelled=cancellation,
                session_id=snapshot.session_id,**({'evidence_capture':adapter.capture_read} if adapter else {})) if reader else nullcontext()
            with activation:
                result=rt.turn(prepared,on_event=provisional,cancelled=cancellation,
                context=ResolvedContext.from_dict(attempt['context']) if attempt['context'] is not None else None,
                accounting=self.accounting,observer=self.observer,
                operation_context=operation,
                tool_journal=self.bindings.tool_journal if attempt['purpose']=='ordinary' else None,
                **context_args)
        except HistoricalEvidenceDenied:
            result=self._failed_context_readmission(snapshot.state,aid,'evidenceUseDenied')
        except TurnAdmissionError as exc:
            if not context_enabled or snapshot.state['attempts'][aid]['dispatchMarker']: raise
            result=self._failed_context_readmission(snapshot.state,aid,
                'contextLimit' if exc.code=='contextLimit' else 'bindingMismatch')
        if ownership_error: raise ownership_error[0]
        lease.check_valid()
        self.bindings.readmit()
        packet=make_receipt(snapshot.state,aid,result,**({'tool_events':captured_events,'events_truncated':events_truncated} if snapshot.state['version'] in (4,5,6) else {}))
        self.store.save_receipt(snapshot.session_id,aid,packet,lease,scope=self.scope)
        self._phase(on_event,'receiptSaved',snapshot,aid)
        return self._adopt(snapshot,lease,packet,on_event)

    @staticmethod
    def _failed_context_readmission(state,aid,code):
        from prosaic_runtime import Result,TurnResult,TurnEvidence,ContextAssemblyReport,ContextWorkState
        attempt=state['attempts'][aid]
        attribution=({'context':attempt['context'],**state['accountingScope'],'provider_call_ids':[]}
                     if attempt['context'] is not None and state['accountingScope'] is not None else None)
        frame=state['contextPacks']['attempts'][aid] if has_packs(state) else None
        views=frame['frozenInput']['inputViews'] if frame is not None else None
        contract={}
        if state['version'] in (4,5,6) and attempt['purpose']=='ordinary':
            from .session_tool_contracts import attempt_frozen
            frozen=attempt_frozen(state,aid);views=frozen['inputViews']
            contract={'toolContractV1':{'bindings':frozen['bindings']['toolContractV1'],
                'evidence':{'version':1,'records':[],'calls':[],'deliveries':{}},'citations':None}}
        if 'parallelToolsV1' in state and contract:
            parallel=frozen['bindings']['parallelToolsV1']
            contract['parallelToolsV1']={'bindings':parallel,'schedule':dict(**parallel,batches=[])}
        evidence=TurnEvidence.from_dict({'version':4 if 'parallelToolsV1' in contract else 3 if contract else 2 if views else 1,'providerAttempts':0,'toolAttempts':0,
            'knownUsage':{},'usageComplete':True,'toolOutcomes':[],'failureCode':code,'accounting':attribution,
            **({'inputViews':views} if views is not None or contract else {}),**contract})
        work=ContextWorkState.from_dict(attempt['contextWork']) if attempt['contextWork'] is not None else None
        report=(ContextAssemblyReport.from_dict({**attempt['initialContextReport'],
            'candidateChecks':work.candidate_checks,'candidateBytes':work.candidate_bytes}) if work is not None else None)
        fingerprint=frame['frozenInput']['bindings'].get('rules',{}).get('fingerprint') if frame is not None else None
        return TurnResult(Result(1,'',code),None,evidence,context_report=report,context_work=work,
            **({'rules_fingerprint':fingerprint} if fingerprint else {}))

    def _adopt(self,snapshot,lease,packet,on_event):
        attempt=snapshot.state['attempts'][packet['invocationId']]
        interpreting=attempt['purpose']=='interpretation'
        state=adopt_receipt(snapshot.state,packet,finalize=not interpreting)
        snapshot=self._save(snapshot,state,lease)
        if interpreting: return self._after_interpretation(snapshot,lease,packet,on_event)
        self._phase(on_event,'turnCommitted',snapshot,packet['invocationId'])
        return self._reply(snapshot)

    def _readmit_attempt(self,snapshot,*,fresh_attempt=False,attempt_id=None):
        state=snapshot.state
        pending=state['pending']
        attempt=state['attempts'][attempt_id or pending['invocationId']]
        turn=state['turns'][attempt['turnSequence']-1]
        if fresh_attempt and attempt['encodingVersion'] == 'conversation-turn-v6':
            raise ConversationError('messageConflict')
        if attempt['encodingVersion']in ('conversation-turn-v4','conversation-turn-v5','conversation-turn-v6'):
            from .session_tool_contracts import restore_attempt
            return restore_attempt(self,state,attempt,turn,fresh_attempt=fresh_attempt)
        if attempt['encodingVersion']=='conversation-turn-v3':
            import time
            from .context_packs.records import ContextPackInvocation
            frame=ContextPackInvocation.from_dict(state['contextPacks']['attempts'][attempt['invocationId']])
            authorize_history(self,state,attempt['invocationId'],before_sequence=turn['sequence'])
            authorize_pack(self,state,frame,deadline=time.monotonic()+self.bindings.run_policy.timeout_s)
            rt=self.bindings.runtime(lifecycle=self.lifecycle)
            prepared=rt.restore_turn(self.bindings.agent,history=tuple(ConversationMessage.from_dict(m) for m in
                history_of(state,before_sequence=turn['sequence'])),frozen_input=frame.frozen_input,
                policy=self.bindings.run_policy,limits=self.bindings.turn_limits,workspace=self.bindings._workspace,
                context_policy=self.bindings.context_policy,token_counters=self.bindings.token_counters,
                context_work=None if fresh_attempt else frame.context_work,fresh_attempt=fresh_attempt)
            return rt,prepared
        if digest(history_of(state,before_sequence=turn['sequence']))!=turn['historyIdentity']:
            raise ConversationError('bindingMismatch')
        saved_attempt=attempt
        if fresh_attempt and attempt['encodingVersion']=='conversation-turn-v2':
            # Explicit consent allocates a new attempt, retaining the frozen
            # preparation but not the previous execution's spent allowance.
            report=attempt['initialContextReport']
            saved_attempt={**attempt,'contextWork':{'version':1,
                'candidateChecks':report['candidateChecks'],
                'candidateBytes':report['candidateBytes'],
                'activeAssemblyMicros':0,'reservedActiveMicros':0,
                'readmissionCandidateBytes':report['encodedInputBytes'],
                'readmissionPending':True,'checkpointSequence':0}}
        rt,prepared=self._prepare(state,turn,purpose=attempt['purpose'],saved_attempt=saved_attempt)
        if (prepared.context_identity,prepared.encoding_version,prepared.input_bytes)!=(
                attempt['contextIdentity'],attempt['encodingVersion'],attempt['inputBytes']):
            raise ConversationError('bindingMismatch')
        return rt,prepared

    @tracked
    @pack_errors
    def recover(self,session_id):
        with self.store.lease(session_id,scope=self.scope) as lease:
            snapshot=self._load(session_id)
            pending=snapshot.state['pending']
            if pending is None: return self._reply(snapshot)
            if pending['phase']=='workflowCommand':
                return self._recover_workflow_command(snapshot,lease)
            aid=pending['invocationId']
            attempt=snapshot.state['attempts'][aid]
            packet=self.store.load_receipt(session_id,aid,scope=self.scope)
            if packet is not None:
                if attempt['receiptAdopted']:
                    if attempt['purpose']=='interpretation' and snapshot.state['turns'][-1]['status']!='needsResolution':
                        return self._after_interpretation(snapshot,lease,packet,None)
                    return self._reply(snapshot)
                return self._adopt(snapshot,lease,packet,None)
            if attempt['dispatchMarker']:
                state=mark_interrupted(snapshot.state)
                return self._reply(snapshot if state==snapshot.state else self._save(snapshot,state,lease))
            if has_packs(snapshot.state):
                frame=snapshot.state['contextPacks']['attempts'][aid]
                if frame is not None and frame['contextWork'] is not None and frame['contextWork']['reservedActiveMicros']:
                    return self._reply(self._save(snapshot,mark_interrupted(snapshot.state),lease))
            rt,prepared=self._readmit_attempt(snapshot)
            return self._execute(snapshot,lease,rt,prepared,None,None)

    @tracked
    @pack_errors
    def retry_interrupted(self,session_id,*,expected_revision,acknowledge_effect_risk,on_event=None,cancelled=None):
        if acknowledge_effect_risk is not True: raise ConversationError('confirmationRequired')
        with self.store.lease(session_id,scope=self.scope) as lease:
            snapshot=self._load(session_id)
            validate_revision(expected_revision)
            if expected_revision!=snapshot.revision: raise RevisionConflict()
            pending=snapshot.state['pending']
            if (pending is None or pending['phase']!='modelInvocation' or
                    snapshot.state['turns'][-1]['status']!='needsResolution'):
                raise ConversationError('messageConflict')
            rt,prepared=self._readmit_attempt(snapshot,fresh_attempt=True)
            turn=snapshot.state['turns'][-1]
            purpose=snapshot.state['attempts'][pending['invocationId']]['purpose']
            snapshot=self._reserve(snapshot,lease,turn['messageId'],turn,prepared,purpose=purpose,
                interaction_ref=turn['interactionRef'],retry=True)
            return self._execute(snapshot,lease,rt,prepared,on_event,cancelled)


    @tracked
    @pack_errors
    def retry_failed(self,session_id,*,expected_revision,acknowledge_effect_risk,on_event=None,cancelled=None):
        """Explicitly retry the latest proven no-effect failure under its original identity.

        The host retains authorization, expiry and aggregate token admission. No
        recovery read spends provider calls or replenishes a host budget.
        """
        if acknowledge_effect_risk is not True: raise ConversationError('confirmationRequired')
        with self.store.lease(session_id,scope=self.scope) as lease:
            snapshot=self._load(session_id)
            validate_revision(expected_revision)
            if expected_revision!=snapshot.revision: raise RevisionConflict()
            state=snapshot.state
            if state['pending'] is not None or state['workflow'] is not None or not state['turns']:
                raise ConversationError('messageConflict')
            turn=state['turns'][-1]
            if turn['status']!='failed' or not turn['attempts']:
                raise ConversationError('messageConflict')
            for aid in turn['attempts']:
                attempt=state['attempts'][aid]
                if (attempt['purpose']!='ordinary' or not attempt['receiptAdopted'] or
                        attempt['effectUncertain'] or attempt['toolAttempts'] or
                        attempt['providerReservation'] or attempt['toolReservation']):
                    raise ConversationError('messageConflict')
                packet=self.store.load_receipt(session_id,aid,scope=self.scope)
                if packet is None: raise ConversationError('messageConflict')
                receipt=match_receipt(state,packet)
                evidence=receipt['evidence']
                if (receipt['sha256']!=attempt['receiptIdentity'] or
                        len(encode(receipt))!=attempt['receiptBytes'] or
                        receipt['result']['failureCode'] is None or
                        evidence['providerAttempts']!=attempt['providerAttempts'] or
                        evidence['toolAttempts']!=0 or evidence['toolOutcomes'] or
                        evidence['usageComplete'] is not True or (evidence['providerAttempts']>0 and
                        type(evidence['knownUsage'].get('totalTokens')) is not int)):
                    raise ConversationError('messageConflict')
            rt,prepared=self._readmit_attempt(snapshot,fresh_attempt=True,attempt_id=turn['attempts'][-1])
            snapshot=self._reserve(snapshot,lease,turn['messageId'],turn,prepared,
                interaction_ref=turn['interactionRef'],retry=True)
            return self._execute(snapshot,lease,rt,prepared,on_event,cancelled)
