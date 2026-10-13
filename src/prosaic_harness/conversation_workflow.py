"""Tool-free interpretation and conservative handoff to the existing Harness."""
from .engine import Harness
from .conversation_errors import ConversationError
from .run_store import RevisionConflict, validate_id, validate_revision
from .session_codec import encode, decode, digest, owned, reference
from .session_contracts import (seal, verify_session, freeze_workflow_command,
    finish_host_turn, public_node_limit, reserve_host_command)
from .schema_validation import evaluate_schema, SchemaEvaluationError
from .conversation_bindings import encoded_answer_bound


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
        answer_bound=encoded_answer_bound(p['maxAssistantBytes'],p['maxTurnBytes'])
        raw=harness.interaction(review_outputs=tuple(registration.readmit()['reviewOutputs']),
            include_response_schema=True,maximum_bytes=p['maxPublicBytes']-answer_bound-8192)
        if raw is None: return None
        view=raw.to_dict()
        presented=len(state['turns']) if sequence is None else sequence
        view['reference']=digest({'sessionId':state['sessionId'],'registration':state['workflow']['registration'],
            'presentedTurn':presented,'interaction':view})
        return owned(view,maximum=p['maxPublicBytes']-answer_bound-4096,
                     depth=p['maxJsonDepth']-8,nodes=public_node_limit(p)-128)

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
            'sourceMessageId':message_id,'interactionRef':interaction_ref,'interaction':view,
            'workflow':state['workflow']}}
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
        command={'version':1,'decisionId':digest({'session':state['sessionId'],'message':turn['messageId'],
            'interaction':original['reference']})[:32],
            'registration':state['workflow']['registration'],'runId':original['runId'],
            'revision':original['revision'],'interactionRef':original['reference'],
            'sourceMessageId':turn['messageId'],'turnSequence':turn['sequence'],
            'choice':proposal['choice'],'response':proposal.get('response')}
        snapshot=self._save(snapshot,freeze_workflow_command(state,command),lease)
        self._phase(on_event,'workflowCommandPrepared',snapshot)
        lease.check_valid()
        _,harness=self._workflow(snapshot.state,lease=lease)
        harness.resume(choice=command['choice'],response=command['response'],expected_revision=command['revision'],
            decision_id=command['decisionId'])
        self._phase(on_event,'workflowCommandReturned',snapshot)
        lease.check_valid()
        return self._finish_workflow_command(snapshot,lease,on_event)

    def detach_workflow(self,session_id,*,expected_revision):
        """Release only a terminal owned workflow; unresolved evidence stays attached."""
        with self.store.lease(session_id,scope=self.scope) as lease:
            snapshot=self._load(session_id)
            validate_revision(expected_revision)
            if snapshot.revision!=expected_revision: raise RevisionConflict()
            if snapshot.state['pending'] is not None: raise ConversationError('messageConflict')
            if snapshot.state['workflow'] is None: return self._reply(snapshot)
            _,harness=self._workflow(snapshot.state,lease=lease)
            if harness.status().state['status'] not in {'completed','rejected'}:
                raise ConversationError('messageConflict')
            return self._reply(self._save(snapshot,seal(snapshot.state|{'workflow':None}),lease))

    def choose(self,session_id,*,message_id,message,choice,interaction_ref,expected_revision,
               response=None,on_event=None):
        """Commit an authenticated structured choice without model interpretation."""
        try:
            reference(message_id)
            reference(interaction_ref)
            if type(message) is not str or not message or len(message.encode())>self.bindings.policy.max_user_bytes:
                raise ValueError()
        except (ValueError,UnicodeError): raise ConversationError('invalidMessage') from None
        try:
            response=owned(response,maximum=self.bindings.policy.max_public_bytes,
                depth=self.bindings.policy.max_json_depth-8,
                nodes=(self.bindings.policy.max_json_nodes-8192)//8)
        except (ValueError,TypeError,UnicodeError): raise ConversationError('invalidInterpretation') from None
        with self.store.lease(session_id,scope=self.scope) as lease:
            snapshot=self._load(session_id)
            state=snapshot.state
            for turn in state['turns']:
                if turn['messageId']==message_id:
                    data=turn['inputData'] or {}
                    if (turn['message']!=message or turn['interactionRef']!=interaction_ref
                            or data.get('structuredChoice')!={'choice':choice,'response':response}):
                        raise ConversationError('messageConflict')
                    return self._reply(snapshot,turn)
            validate_revision(expected_revision)
            if expected_revision!=snapshot.revision: raise RevisionConflict()
            if state['pending'] is not None: raise ConversationError('messageConflict')
            view=self._interaction(state)
            if view is None or interaction_ref!=view['reference']: raise ConversationError('interactionStale')
            proposal={'sourceMessageId':message_id,'interactionRef':interaction_ref,'ambiguous':False,'choice':choice}
            if 'responseSchema' in view:
                try: errors=evaluate_schema(view['responseSchema'],response)
                except (ValueError,TypeError,SchemaEvaluationError): errors=True
                if errors: raise ConversationError('invalidInterpretation')
                proposal['response']=response
            elif response is not None: raise ConversationError('invalidInterpretation')
            if type(choice) is not str or choice not in view['choices']: raise ConversationError('invalidInterpretation')
            registration,_=self._workflow(state)
            try:
                confirmed=registration._confirmation is not None and registration._confirmation.admit(
                    message,owned(proposal),owned(view)) is True
            except Exception: confirmed=False
            if not confirmed: raise ConversationError('confirmationRequired')
            self.bindings.readmit()
            if self._interaction(state)!=view: raise ConversationError('interactionStale')
            command={'version':1,'decisionId':digest({'session':session_id,'message':message_id,
                'interaction':interaction_ref})[:32],'registration':state['workflow']['registration'],
                'runId':view['runId'],'revision':view['revision'],'interactionRef':interaction_ref,
                'sourceMessageId':message_id,'turnSequence':len(state['turns'])+1,'choice':choice,'response':response}
            data={'sourceMessageId':message_id,'interactionRef':interaction_ref,'interaction':view,
                'workflow':state['workflow'],'structuredChoice':{'choice':choice,'response':response}}
            snapshot=self._save(snapshot,reserve_host_command(state,message_id=message_id,message=message,
                interaction_ref=interaction_ref,input_data=data,command=command),lease)
            self._phase(on_event,'workflowCommandPrepared',snapshot)
            lease.check_valid()
            _,harness=self._workflow(snapshot.state,lease=lease)
            harness.resume(choice=choice,response=response,expected_revision=view['revision'],decision_id=command['decisionId'])
            self._phase(on_event,'workflowCommandReturned',snapshot)
            lease.check_valid()
            return self._finish_workflow_command(snapshot,lease,on_event)

    def _finish_workflow_command(self,snapshot,lease,on_event):
        _,harness=self._workflow(snapshot.state,lease=lease)
        actual=harness.status().state['status']
        if actual not in {'waiting','completed','rejected'}:
            from .session_contracts import mark_interrupted
            return self._reply(self._save(snapshot,mark_interrupted(snapshot.state),lease))
        answer=('Workflow completed.' if actual=='completed' else 'Workflow rejected.' if actual=='rejected'
            else 'Workflow is '+actual+'.')
        return self._host_finish(snapshot,lease,on_event,answer=answer)

    def _recover_workflow_command(self,snapshot,lease):
        """Reconcile only an exact saved decision; never dispatch/resume during recovery."""
        from .session_contracts import mark_interrupted
        command=snapshot.state['pending']['command']
        _,harness=self._workflow(snapshot.state,lease=lease)
        actual=harness.status().state
        matched=[e for e in actual['history'] if e.get('decision_id')==command.get('decisionId')]
        if (command.get('decisionId') is not None and len(matched)==1
                and matched[0]['choice']==command['choice'] and matched[0].get('response')==command['response']
                and matched[0].get('decision_revision')==command['revision']
                and actual['status'] in {'waiting','completed','rejected'} and actual['pending'] is None):
            return self._finish_workflow_command(snapshot,lease,None)
        state=mark_interrupted(snapshot.state)
        return self._reply(snapshot if state==snapshot.state else self._save(snapshot,state,lease))

    def retry_workflow_command(self,session_id,*,expected_revision,acknowledge_effect_risk,on_event=None):
        """Explicitly retry only the frozen command against its original workflow revision."""
        if acknowledge_effect_risk is not True: raise ConversationError('confirmationRequired')
        with self.store.lease(session_id,scope=self.scope) as lease:
            snapshot=self._load(session_id)
            validate_revision(expected_revision)
            if expected_revision!=snapshot.revision: raise RevisionConflict()
            pending=snapshot.state['pending']
            if pending is None or pending['phase']!='workflowCommand': raise ConversationError('messageConflict')
            command=pending['command']
            if command.get('decisionId') is None: raise ConversationError('capabilityMissing')
            # First adopt saved completion, if present, without repeating any effect.
            reply=self._recover_workflow_command(snapshot,lease)
            if reply.document['status']!='needsResolution': return reply
            snapshot=self._load(session_id)
            _,harness=self._workflow(snapshot.state,lease=lease)
            current=harness.status()
            if current.revision!=command['revision'] or current.state['status']!='waiting':
                raise ConversationError('interactionStale')
            turn=snapshot.state['turns'][-1]
            view=self._interaction(snapshot.state,sequence=turn['sequence']-1)
            if view!=turn['inputData']['interaction']: raise ConversationError('interactionStale')
            registration,_=self._workflow(snapshot.state,lease=lease)
            proposal={'sourceMessageId':turn['messageId'],'interactionRef':command['interactionRef'],
                'ambiguous':False,'choice':command['choice']}
            if 'responseSchema' in view: proposal['response']=command['response']
            try:
                confirmed=registration._confirmation is not None and registration._confirmation.admit(
                    turn['message'],owned(proposal),owned(view)) is True
            except Exception: confirmed=False
            if not confirmed: raise ConversationError('confirmationRequired')
            self.bindings.readmit()
            lease.check_valid()
            _,harness=self._workflow(snapshot.state,lease=lease)
            harness.resume(choice=command['choice'],response=command['response'],expected_revision=command['revision'],
                decision_id=command['decisionId'])
            self._phase(on_event,'workflowCommandReturned',snapshot)
            lease.check_valid()
            return self._finish_workflow_command(snapshot,lease,on_event)
