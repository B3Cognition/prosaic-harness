"""Graph-free ordered conversations over public Runtime turns and SessionStore."""
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
    adopt_receipt, history_of, public_node_limit, mark_interrupted)


@dataclass(frozen=True, init=False, repr=False)
class ConversationReply:
    _encoded: bytes
    def __init__(self, document, *, maximum=262144, depth=64, nodes=65536):
        object.__setattr__(self,'_encoded',encode(document,maximum=maximum,depth=depth,nodes=nodes))
    @property
    def document(self): return decode(self._encoded)


class Conversation:
    """The embedding host authenticates and authorizes every operation first."""
    def __init__(self, bindings, *, store, scope, context=None, accounting=None, observer=None):
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
        self.bindings,self.store,self.scope=bindings,store,scope
        self.context,self.accounting,self.observer=context,accounting,observer

    def _load(self, session_id):
        validate_id(session_id)
        snapshot=self.store.load_session(session_id,scope=self.scope)
        material=self.bindings.readmit()
        state=snapshot.state
        if state['bindingIdentity']!=self.bindings.identity or state['bindingVersion']!=self.bindings.version:
            raise ConversationError('bindingMismatch')
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

    def create(self, *, session_id=None):
        sid=uuid4().hex if session_id is None else validate_id(session_id)
        self.bindings.readmit()
        with self.store.lease(sid,scope=self.scope) as lease:
            try: return self._load(sid)
            except SessionNotFound: pass
            state=new_session(sid,self.scope,self.bindings,accounting=self._accounting_context(sid),
                              accounting_scope=self._accounting_scope())
            try: revision=self.store.create_session(sid,state,lease,scope=self.scope)
            except (SessionAlreadyExists,StoreUnavailable):
                # Reconcile an acknowledged/unknown creation, preserving its original context.
                return self._load(sid)
            return SessionSnapshot(sid,state,revision)

    def _reply(self, snapshot, turn=None):
        state=snapshot.state
        if turn is None and state['turns']: turn=state['turns'][-1]
        view={'version':1,'sessionId':snapshot.session_id,'revision':snapshot.revision,
              'status':'ready','pendingInteraction':None,'recoveryStatus':None}
        if turn is not None:
            view.update({key:turn[key] for key in ('messageId','status','failureCode','pendingInteraction','recoveryStatus')})
            view['turnSequence']=turn['sequence']
            if turn['answer'] is not None: view['answer']=turn['answer']
        if state['workflow'] is not None:
            view['pendingInteraction']=self._interaction(state)
        p=state['policy']
        return ConversationReply(view,maximum=p['maxPublicBytes'],depth=p['maxJsonDepth']-8,
                                 nodes=public_node_limit(p))

    def status(self, session_id): return self._reply(self._load(session_id))
    def history(self, session_id):
        return tuple(ConversationMessage.from_dict(m) for m in history_of(self._load(session_id).state))

    def _save(self,snapshot,state,lease):
        lease.check_valid()
        self.bindings.readmit()
        revision=self.store.save_session(snapshot.session_id,state,snapshot.revision,lease,scope=self.scope)
        return SessionSnapshot(snapshot.session_id,state,revision)

    def _prepare(self, state, turn, *, purpose='ordinary'):
        data=self.bindings.readmit()
        rt=self.bindings.runtime()
        interpreting=purpose=='interpretation'
        phase=data['interpreter'] if interpreting else None
        if interpreting and phase is None: raise ConversationError('capabilityMissing')
        try:
            prepared=rt.prepare_turn(ProsaicArtifact.from_inspection(phase['artifact']) if phase else self.bindings.agent,
                message=turn['message'],history=tuple(ConversationMessage.from_dict(m) for m in
                    history_of(state,before_sequence=turn['sequence'])),input_data=turn['inputData'],
                policy=self.bindings.interpretation_policy if interpreting else self.bindings.run_policy,
                limits=self.bindings.turn_limits,workspace=None if interpreting else self.bindings._workspace)
            return rt,prepared
        except TurnAdmissionError as exc:
            if exc.code in {'contextLimit','inputLimit'}: raise ConversationError('contextLimit',exc.limit) from None
            if exc.code=='invalidMessage': raise ConversationError('invalidMessage',exc.limit) from None
            raise ConversationError('bindingMismatch',exc.limit) from None

    @staticmethod
    def _phase(on_event,name,snapshot,invocation_id=None):
        if on_event is not None:
            event={'event':name,'sessionId':snapshot.session_id}
            if invocation_id is not None: event['invocationId']=invocation_id
            if snapshot.state['turns']: event['turnSequence']=snapshot.state['turns'][-1]['sequence']
            on_event(event)

    def send(self, session_id, *, message_id, message, expected_revision,
             interaction_ref=None, on_event=None, cancelled=None):
        try:
            reference(message_id)
            if interaction_ref is not None: reference(interaction_ref)
            if type(message) is not str or not message or len(message.encode())>self.bindings.policy.max_user_bytes:
                raise ValueError()
        except (ValueError,UnicodeError): raise ConversationError('invalidMessage') from None
        with self.store.lease(session_id,scope=self.scope) as lease:
            snapshot=self._load(session_id)
            state=snapshot.state
            for turn in state['turns']:
                if turn['messageId']==message_id:
                    if turn['message']!=message or turn['interactionRef']!=interaction_ref:
                        raise ConversationError('messageConflict')
                    return self._reply(snapshot,turn)
            validate_revision(expected_revision)
            if expected_revision!=snapshot.revision: raise RevisionConflict()
            if state['pending'] is not None: raise ConversationError('messageConflict')
            if state['workflow'] is not None:
                return self._send_workflow(snapshot,lease,message_id,message,interaction_ref,on_event,cancelled)
            if interaction_ref is not None: raise ConversationError('interactionStale')
            turn={'sequence':len(state['turns'])+1,'message':message,'inputData':None}
            rt,prepared=self._prepare(state,turn)
            snapshot=self._reserve(snapshot,lease,message_id,turn,prepared)
            return self._execute(snapshot,lease,rt,prepared,on_event,cancelled)

    def _reserve(self,snapshot,lease,message_id,turn,prepared, *, purpose='ordinary',interaction_ref=None,retry=False):
        state=snapshot.state
        aid=uuid4().hex
        context=(ResolvedContext.from_dict(state['accounting']).child(invocation_id=aid,
            run_id=snapshot.session_id,step_id='turn.'+str(turn['sequence'])+'.'+purpose).to_dict()
            if state['accounting'] is not None else None)
        policy=self.bindings.interpretation_policy if purpose=='interpretation' else self.bindings.run_policy
        pending=reserve_attempt(state,message_id=message_id,message=turn['message'],invocation_id=aid,
            context_identity=prepared.context_identity,encoding_version=prepared.encoding_version,
            input_bytes=prepared.input_bytes,provider_allowance=policy.max_provider_requests,
            tool_allowance=policy.max_tool_calls,input_data=turn['inputData'],interaction_ref=interaction_ref,
            purpose=purpose,context=context,retry=retry)
        return self._save(snapshot,pending,lease)

    def _execute(self,snapshot,lease,rt,prepared,on_event,cancelled):
        aid=snapshot.state['pending']['invocationId']
        attempt=snapshot.state['attempts'][aid]
        if attempt['dispatchMarker']: raise ConversationError('messageConflict')
        try: snapshot=self._save(snapshot,mark_dispatch(snapshot.state,aid),lease)
        except StoreUnavailable:
            # An unknown marker acknowledgement never grants dispatch. Recovery reads authority.
            raise
        ownership_error=[]
        def cancellation():
            try:
                lease.check_valid()
                self.bindings.readmit()
            except Exception as exc:
                ownership_error.append(exc)
                return True
            return bool(cancelled()) if cancelled is not None else False
        def provisional(event):
            lease.check_valid()
            if attempt['purpose']=='ordinary' and on_event is not None: on_event(event)
        self.bindings.readmit()
        result=rt.turn(prepared,on_event=provisional,cancelled=cancellation,
            context=ResolvedContext.from_dict(attempt['context']) if attempt['context'] is not None else None,
            accounting=self.accounting,observer=self.observer,
            operation_context=InvocationScope(aid,operation_namespace=(self.bindings.readmit()['operationNamespace']
                if attempt['purpose']=='ordinary' else None)),
            tool_journal=self.bindings.tool_journal if attempt['purpose']=='ordinary' else None)
        if ownership_error: raise ownership_error[0]
        lease.check_valid()
        self.bindings.readmit()
        packet=make_receipt(snapshot.state,aid,result)
        self.store.save_receipt(snapshot.session_id,aid,packet,lease,scope=self.scope)
        self._phase(on_event,'receiptSaved',snapshot,aid)
        return self._adopt(snapshot,lease,packet,on_event)

    def _adopt(self,snapshot,lease,packet,on_event):
        attempt=snapshot.state['attempts'][packet['invocationId']]
        interpreting=attempt['purpose']=='interpretation'
        state=adopt_receipt(snapshot.state,packet,finalize=not interpreting)
        snapshot=self._save(snapshot,state,lease)
        if interpreting: return self._after_interpretation(snapshot,lease,packet,on_event)
        self._phase(on_event,'turnCommitted',snapshot,packet['invocationId'])
        return self._reply(snapshot)

    def _readmit_attempt(self,snapshot):
        state=snapshot.state
        pending=state['pending']
        attempt=state['attempts'][pending['invocationId']]
        turn=state['turns'][pending['turnSequence']-1]
        if digest(history_of(state,before_sequence=turn['sequence']))!=turn['historyIdentity']:
            raise ConversationError('bindingMismatch')
        rt,prepared=self._prepare(state,turn,purpose=attempt['purpose'])
        if (prepared.context_identity,prepared.encoding_version,prepared.input_bytes)!=(
                attempt['contextIdentity'],attempt['encodingVersion'],attempt['inputBytes']):
            raise ConversationError('bindingMismatch')
        return rt,prepared

    def recover(self,session_id):
        with self.store.lease(session_id,scope=self.scope) as lease:
            snapshot=self._load(session_id)
            pending=snapshot.state['pending']
            if pending is None: return self._reply(snapshot)
            if pending['phase']=='workflowCommand':
                return self._reply(self._save(snapshot,mark_interrupted(snapshot.state),lease))
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
            rt,prepared=self._readmit_attempt(snapshot)
            return self._execute(snapshot,lease,rt,prepared,None,None)

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
            rt,prepared=self._readmit_attempt(snapshot)
            turn=snapshot.state['turns'][-1]
            purpose=snapshot.state['attempts'][pending['invocationId']]['purpose']
            snapshot=self._reserve(snapshot,lease,turn['messageId'],turn,prepared,purpose=purpose,
                interaction_ref=turn['interactionRef'],retry=True)
            return self._execute(snapshot,lease,rt,prepared,on_event,cancelled)
