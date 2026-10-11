"""Tool-free interpretation and conservative handoff to the existing Harness."""
from .engine import Harness
from .conversation_errors import ConversationError
from .run_store import RevisionConflict, validate_id, validate_revision
from .session_codec import encode, decode, digest, owned, reference
from .session_contracts import (seal, verify_session, freeze_workflow_command,
    finish_host_turn, public_node_limit)
from .schema_validation import evaluate_schema, SchemaEvaluationError


class ConversationWorkflow:
    def _workflow(self,state,*,lease=None):
        linked=state['workflow']
        if linked is None: raise ConversationError('capabilityMissing')
        try: registration=self.bindings._workflows[linked['registration']]
        except KeyError: raise ConversationError('bindingMismatch') from None
        registration.readmit()
        try: allowed=registration._authorizer.authorize(self.scope,linked['runId'])
        except Exception: raise ConversationError('identityMismatch') from None
        if allowed is not True: raise ConversationError('identityMismatch')
        registration.readmit()
        def cancelled():
            if lease is not None:
                lease.check_valid()
                self.bindings.readmit()
            return False
        harness=Harness(registration._workflow,store=registration._store,run_id=linked['runId'],
            runtime=registration._runtime,validators=dict(registration._validators),
            context=registration._context,accounting=registration._accounting,cancelled=cancelled)
        saved=harness.status()
        accounting=saved.state.get('accounting_context')
        if accounting is not None and any(accounting.get(key)!=expected for key,expected in (
                ('application_id',self.scope.application),('tenant_id',self.scope.tenant),
                ('actor_id',self.scope.actor),('billing_account_id',self.scope.billing_account))):
            raise ConversationError('identityMismatch')
        return registration,harness

    def _interaction(self,state,*,sequence=None):
        registration,harness=self._workflow(state)
        p=state['policy']
        raw=harness.interaction(review_outputs=tuple(registration.readmit()['reviewOutputs']),
            include_response_schema=True,maximum_bytes=p['maxPublicBytes'])
        if raw is None: return None
        view=raw.to_dict()
        presented=len(state['turns']) if sequence is None else sequence
        view['reference']=digest({'sessionId':state['sessionId'],'registration':state['workflow']['registration'],
            'presentedTurn':presented,'interaction':view})
        return owned(view,maximum=p['maxPublicBytes'],depth=p['maxJsonDepth']-8,nodes=public_node_limit(p))

    def attach_workflow(self,session_id,*,registration,run_id,expected_revision):
        reference(registration)
        validate_id(run_id)
        with self.store.lease(session_id,scope=self.scope) as lease:
            snapshot=self._load(session_id)
            validate_revision(expected_revision)
            if expected_revision!=snapshot.revision: raise RevisionConflict()
            if snapshot.state['pending'] is not None: raise ConversationError('messageConflict')
            linked={'registration':registration,'runId':run_id}
            if snapshot.state['workflow'] is not None:
                if snapshot.state['workflow']!=linked: raise ConversationError('messageConflict')
                return self._reply(snapshot)
            state=verify_session(seal(snapshot.state|{'workflow':linked}))
            self._workflow(state)
            self._interaction(state)
            return self._reply(self._save(snapshot,state,lease))

    def _send_workflow(self,snapshot,lease,message_id,message,interaction_ref,on_event,cancelled):
        state=snapshot.state
        view=self._interaction(state)
        if view is None or interaction_ref!=view['reference']: raise ConversationError('interactionStale')
        turn={'sequence':len(state['turns'])+1,'message':message,'inputData':{
            'sourceMessageId':message_id,'interactionRef':interaction_ref,'interaction':view}}
        rt,prepared=self._prepare(state,turn,purpose='interpretation')
        snapshot=self._reserve(snapshot,lease,message_id,turn,prepared,purpose='interpretation',
            interaction_ref=interaction_ref)
        return self._execute(snapshot,lease,rt,prepared,on_event,cancelled)

    def _host_finish(self,snapshot,lease,on_event,*,answer=None,failure_code=None):
        view=self._interaction(snapshot.state)
        state=finish_host_turn(snapshot.state,answer=answer,failure_code=failure_code,interaction=view)
        snapshot=self._save(snapshot,state,lease)
        self._phase(on_event,'turnCommitted',snapshot)
        return self._reply(snapshot)

    def _after_interpretation(self,snapshot,lease,packet,on_event):
        if packet['result']['failureCode'] is not None:
            return self._host_finish(snapshot,lease,on_event,failure_code=packet['result']['failureCode'])
        state=snapshot.state
        turn=state['turns'][-1]
        original=turn['inputData']['interaction']
        policy=state['policy']
        data=self.bindings.readmit()['interpreter']
        try:
            proposal=decode(packet['result']['answer'].encode(),maximum=policy['maxPublicBytes'],
                depth=policy['maxJsonDepth']-8,nodes=public_node_limit(policy))
            if (evaluate_schema(data['schema'],proposal) or proposal['sourceMessageId']!=turn['messageId']
                    or proposal['interactionRef']!=turn['interactionRef']): raise ValueError()
        except (ValueError,TypeError,KeyError,SchemaEvaluationError):
            return self._host_finish(snapshot,lease,on_event,answer='Please clarify your current choice.',
                                     failure_code='invalidInterpretation')
        current=self._interaction(state,sequence=turn['sequence']-1)
        if current!=original:
            return self._host_finish(snapshot,lease,on_event,answer='Please respond to the current interaction.',
                                     failure_code='interactionStale')
        if proposal['ambiguous']:
            return self._host_finish(snapshot,lease,on_event,answer='Please clarify your current choice.')
        try:
            if proposal.get('choice') not in original['choices']: raise ValueError()
            if 'responseSchema' in original:
                if 'response' not in proposal or evaluate_schema(original['responseSchema'],proposal['response']):
                    raise ValueError()
            elif 'response' in proposal: raise ValueError()
        except (ValueError,KeyError,SchemaEvaluationError):
            return self._host_finish(snapshot,lease,on_event,answer='Please clarify your current choice.',
                                     failure_code='invalidInterpretation')
        registration,_=self._workflow(state)
        rule=registration._confirmation
        try: confirmed=rule.admit(turn['message'],owned(proposal),owned(original)) if rule else False
        except Exception: confirmed=False
        if confirmed is not True:
            return self._host_finish(snapshot,lease,on_event,answer='Please confirm your current choice explicitly.',
                                     failure_code='confirmationRequired')
        # Callback mutation or a concurrent direct human action cannot refresh the original command.
        self.bindings.readmit()
        if self._interaction(state,sequence=turn['sequence']-1)!=original:
            return self._host_finish(snapshot,lease,on_event,answer='Please respond to the current interaction.',
                                     failure_code='interactionStale')
        command={'version':1,'registration':state['workflow']['registration'],'runId':original['runId'],
            'revision':original['revision'],'interactionRef':original['reference'],
            'sourceMessageId':turn['messageId'],'turnSequence':turn['sequence'],
            'choice':proposal['choice'],'response':proposal.get('response')}
        snapshot=self._save(snapshot,freeze_workflow_command(state,command),lease)
        self._phase(on_event,'workflowCommandPrepared',snapshot)
        lease.check_valid()
        _,harness=self._workflow(snapshot.state,lease=lease)
        harness.resume(choice=command['choice'],response=command['response'],expected_revision=command['revision'])
        self._phase(on_event,'workflowCommandReturned',snapshot)
        lease.check_valid()
        actual=harness.status().state['status']
        answer='Workflow completed.' if actual=='completed' else 'Workflow rejected.' if actual=='rejected' else 'Workflow is '+actual+'.'
        return self._host_finish(snapshot,lease,on_event,answer=answer)
