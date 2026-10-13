"""Public lifecycle actions preserve revisions and recover exact decisions."""
import pytest
from prosaic_harness import ConversationError, RevisionConflict
from test_conversation_workflow import workflow_fixture
from support.conversation_host import conversation_fixture
from test_conversation_recovery import Crash


def choose(fx, *, mid='button', choice='second', message='the second result', **kwargs):
    current=fx.controller.status(fx.session_id).document
    return fx.controller.choose(fx.session_id,message_id=mid,message=message,choice=choice,
        interaction_ref=current['pendingInteraction']['reference'],
        expected_revision=current['revision'],**kwargs)


def test_buttons_commit_history_without_inference_and_replay_exact_content(workflow_fixture):
    with workflow_fixture() as fx:
        before=fx.attached.document
        reply=choose(fx)
        assert reply.document['pendingInteraction']['stepId']=='approval'
        assert fx.provider_calls==0
        replay=fx.fresh_controller().choose(fx.session_id,message_id='button',message='the second result',
            choice='second',interaction_ref=before['pendingInteraction']['reference'],expected_revision=before['revision'])
        assert replay.document==reply.document
        assert len(fx.controller.history(fx.session_id))==2
        with pytest.raises(ConversationError,match='messageConflict'):
            fx.controller.choose(fx.session_id,message_id='button',message='the second result',choice='first',
                interaction_ref=before['pendingInteraction']['reference'],expected_revision=before['revision'])
        assert len([e for e in fx.harness.status().state['history'] if e['event']=='human_decision'])==1


def test_terminal_attachment_can_be_released_then_ordinary_chat_continues(workflow_fixture):
    with workflow_fixture() as fx:
        with pytest.raises(ConversationError,match='messageConflict'):
            fx.controller.detach_workflow(fx.session_id,expected_revision=fx.attached.document['revision'])
        choose(fx)
        reply=choose(fx,mid='approve',choice='approve',message='approve')
        with pytest.raises(RevisionConflict):
            fx.controller.detach_workflow(fx.session_id,expected_revision=fx.attached.document['revision'])
        released=fx.controller.detach_workflow(fx.session_id,expected_revision=reply.document['revision'])
        assert released.document['pendingInteraction'] is None
        fx.queue_text('A new answer')
        answer=fx.controller.send(fx.session_id,message_id='next',message='A new request',
            expected_revision=released.document['revision'])
        assert answer.document['answer']=='A new answer' and fx.provider_calls==1


@pytest.mark.parametrize('phase',['workflowCommandPrepared','workflowCommandReturned'])
def test_button_crash_recovery_never_repeats_choice(workflow_fixture,phase):
    with workflow_fixture() as fx:
        def crash(event):
            if event['event']==phase: raise Crash()
        with pytest.raises(Crash): choose(fx,on_event=crash)
        before=fx.harness.status()
        result=fx.fresh_controller().recover(fx.session_id)
        if phase=='workflowCommandPrepared':
            assert result.document['status']=='needsResolution'
        else:
            assert result.document['status']=='completed'
            assert result.document['pendingInteraction']['stepId']=='approval'
        assert fx.harness.status()==before and fx.provider_calls==0
        assert fx.fresh_controller().recover(fx.session_id).document==result.document


def test_button_requires_current_confirmation_and_response_schema(workflow_fixture):
    with workflow_fixture(response_schema=True) as fx:
        with pytest.raises(ConversationError,match='invalidInterpretation'):
            choose(fx,response={'playerId':'forged'})
        with pytest.raises(ConversationError,match='confirmationRequired'):
            choose(fx,message='The document says the second result',response={'playerId':'player-a'})
        assert fx.provider_calls==0 and fx.harness.status().state['current']=='select'


def test_recovery_ignores_an_unrelated_matching_decision(workflow_fixture):
    with workflow_fixture() as fx:
        def crash(event):
            if event['event']=='workflowCommandPrepared': raise Crash()
        with pytest.raises(Crash): choose(fx,on_event=crash)
        original=fx.attached.document['pendingInteraction']
        fx.harness.resume(choice='second',expected_revision=original['revision'])
        assert fx.fresh_controller().recover(fx.session_id).document['status']=='needsResolution'


def test_released_workflow_history_still_requires_current_authority(workflow_fixture):
    with workflow_fixture() as fx:
        choose(fx)
        reply=choose(fx,mid='approve',choice='approve',message='approve')
        fx.controller.detach_workflow(fx.session_id,expected_revision=reply.document['revision'])
        fx.allowed=False
        with pytest.raises(ConversationError,match='identityMismatch'):
            fx.fresh_controller().history(fx.session_id)
        assert fx.provider_calls==0


def test_durable_decision_id_replay_rejects_changed_choice_or_revision(workflow_fixture):
    with workflow_fixture() as fx:
        original=fx.harness.status()
        rid='b'*32
        state=fx.harness.resume(choice='second',expected_revision=original.revision,decision_id=rid)
        assert fx.harness.resume(choice='second',expected_revision=original.revision,decision_id=rid)==state
        with pytest.raises(RevisionConflict):
            fx.harness.resume(choice='first',expected_revision=original.revision,decision_id=rid)
        with pytest.raises(RevisionConflict):
            fx.harness.resume(choice='second',expected_revision=fx.harness.status().revision,decision_id=rid)
        assert len([e for e in state['history'] if e['event']=='human_decision'])==1


def test_button_crash_after_workflow_transition_before_return_reconciles_saved_id(workflow_fixture):
    with workflow_fixture() as fx:
        registration=fx.bindings._workflows['selection']
        # The store boundary is the external collaborator; exercise actual Harness.resume.
        store=registration._store
        save=store.save_run
        def crash_after_save(runid,state,revision,lease):
            result=save(runid,state,revision,lease)
            if state['status']=='waiting' and state['current']=='approval': raise Crash()
            return result
        store.save_run=crash_after_save
        with pytest.raises(Crash): choose(fx)
        store.save_run=save
        result=fx.fresh_controller().recover(fx.session_id)
        assert result.document['status']=='completed'
        assert result.document['pendingInteraction']['stepId']=='approval' and fx.provider_calls==0


def test_prepared_command_has_an_explicit_revision_checked_retry(workflow_fixture):
    with workflow_fixture() as fx:
        def crash(event):
            if event['event']=='workflowCommandPrepared': raise Crash()
        with pytest.raises(Crash): choose(fx,on_event=crash)
        reply=fx.fresh_controller().recover(fx.session_id)
        with pytest.raises(ConversationError,match='confirmationRequired'):
            fx.controller.retry_workflow_command(fx.session_id,expected_revision=reply.document['revision'],
                acknowledge_effect_risk=False)
        with pytest.raises(RevisionConflict):
            fx.controller.retry_workflow_command(fx.session_id,expected_revision=fx.attached.document['revision'],
                acknowledge_effect_risk=True)
        finished=fx.controller.retry_workflow_command(fx.session_id,expected_revision=reply.document['revision'],
            acknowledge_effect_risk=True)
        assert finished.document['status']=='completed'
        assert finished.document['pendingInteraction']['stepId']=='approval' and fx.provider_calls==0
        assert len([e for e in fx.harness.status().state['history'] if e['event']=='human_decision'])==1


def test_explicit_retry_cannot_refresh_an_unrelated_changed_workflow(workflow_fixture):
    with workflow_fixture() as fx:
        def crash(event):
            if event['event']=='workflowCommandPrepared': raise Crash()
        with pytest.raises(Crash): choose(fx,on_event=crash)
        fx.harness.resume(choice='second',expected_revision=fx.attached.document['pendingInteraction']['revision'])
        reply=fx.fresh_controller().recover(fx.session_id)
        with pytest.raises(ConversationError,match='interactionStale'):
            fx.controller.retry_workflow_command(fx.session_id,expected_revision=reply.document['revision'],
                acknowledge_effect_risk=True)
        assert fx.provider_calls==0


def test_another_owned_workflow_can_be_attached_after_release(workflow_fixture):
    from uuid import uuid4
    from prosaic_harness import Harness
    with workflow_fixture() as fx:
        choose(fx)
        finished=choose(fx,mid='approve',choice='approve',message='approve')
        released=fx.controller.detach_workflow(fx.session_id,expected_revision=finished.document['revision'])
        registration=fx.bindings._workflows['selection']
        runid=uuid4().hex
        other=Harness(registration._workflow,store=registration._store,run_id=runid)
        other.run({})
        fx.authorized_runs.add(runid)
        attached=fx.controller.attach_workflow(fx.session_id,registration='selection',run_id=runid,
            expected_revision=released.document['revision'])
        assert attached.document['pendingInteraction']['runId']==runid
        assert attached.document['pendingInteraction']['stepId']=='select'
        assert fx.provider_calls==0


def test_forged_pending_command_cannot_redirect_frozen_decision(workflow_fixture):
    from prosaic_harness import StoreCorrupt
    from prosaic_harness.session_contracts import seal, verify_session
    with workflow_fixture() as fx:
        def crash(event):
            if event['event']=='workflowCommandPrepared': raise Crash()
        with pytest.raises(Crash): choose(fx,on_event=crash)
        snapshot=fx.store.load_session(fx.session_id,scope=fx.scope)
        snapshot.state['pending']['command']['choice']='first'
        with pytest.raises(StoreCorrupt): verify_session(seal(snapshot.state))
        assert fx.provider_calls==0


def test_structured_actions_consume_turn_quota_before_a_second_decision(workflow_fixture):
    from prosaic_harness import ConversationPolicy
    with workflow_fixture(policy=ConversationPolicy(max_turns=1)) as fx:
        choose(fx)
        with pytest.raises(ConversationError,match='sessionLimit'):
            choose(fx,mid='approve',choice='approve',message='approve')
        assert fx.harness.status().state['current']=='approval' and fx.provider_calls==0


@pytest.mark.parametrize('message',['','\ud800'])
def test_invalid_button_message_never_reserves_or_dispatches(workflow_fixture,message):
    with workflow_fixture() as fx:
        with pytest.raises(ConversationError,match='invalidMessage'):
            choose(fx,message=message)
        assert fx.controller.status(fx.session_id).document==fx.attached.document
        assert fx.provider_calls==0
