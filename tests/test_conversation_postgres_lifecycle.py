"""Optional real PostgreSQL acceptance for the public lifecycle and decision journal."""
import os
from uuid import uuid4
import pytest
from test_conversation_workflow import workflow_fixture
from support.conversation_host import conversation_fixture
from test_conversation_recovery import Crash
from test_workflow_rules_execution import rule_endpoint, strict


@pytest.fixture
def lifecycle_stores():
    base=os.environ.get('PROSAIC_LIFECYCLE_TEST_DSN')
    if not base: pytest.skip('explicit disposable lifecycle database is not configured')
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from prosaic_harness_postgres import PostgresSessionStore, PostgresRunStore
    name='lifecycle_'+uuid4().hex
    with psycopg.connect(base,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    dsn=make_conninfo(base,dbname=name)
    sessions=PostgresSessionStore(dsn,namespace='test')
    runs=PostgresRunStore(dsn,namespace='test')
    try:
        sessions.initialize()
        runs.initialize()
        yield sessions,runs
    finally:
        sessions.close()
        runs.close()
        with psycopg.connect(base,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def choose(fx,mid,choice,message,on_event=None):
    current=fx.controller.status(fx.session_id).document
    return fx.controller.choose(fx.session_id,message_id=mid,message=message,choice=choice,
        interaction_ref=current['pendingInteraction']['reference'],expected_revision=current['revision'],on_event=on_event)


def test_postgres_choice_recovery_release_and_new_turn(workflow_fixture,lifecycle_stores):
    sessions,runs=lifecycle_stores
    with workflow_fixture(session_store=sessions,run_store=runs) as fx:
        def crash(event):
            if event['event']=='workflowCommandReturned': raise Crash()
        with pytest.raises(Crash): choose(fx,'select','second','the second result',crash)
        reply=fx.fresh_controller().recover(fx.session_id)
        assert reply.document['status']=='completed' and fx.provider_calls==0
        assert reply.document['pendingInteraction']['stepId']=='approval'
        approved=choose(fx,'approve','approve','approve')
        released=fx.fresh_controller().detach_workflow(fx.session_id,expected_revision=approved.document['revision'])
        fx.queue_text('Next preview')
        answer=fx.fresh_controller().send(fx.session_id,message_id='next',message='Another preview',
            expected_revision=released.document['revision'])
        assert answer.document['answer']=='Next preview' and fx.provider_calls==1
        assert len(fx.controller.history(fx.session_id))==6
        assert len([e for e in fx.harness.status().state['history'] if e['event']=='human_decision'])==2
        assert fx.harness.recovery_evidence()['recoveryStatus']=='ready'


def test_postgres_prepared_action_never_dispatches_on_recovery(workflow_fixture,lifecycle_stores):
    sessions,runs=lifecycle_stores
    with workflow_fixture(session_store=sessions,run_store=runs) as fx:
        def crash(event):
            if event['event']=='workflowCommandPrepared': raise Crash()
        with pytest.raises(Crash): choose(fx,'select','second','the second result',crash)
        before=fx.harness.status()
        reply=fx.fresh_controller().recover(fx.session_id)
        assert reply.document['status']=='needsResolution'
        assert fx.harness.status()==before and fx.provider_calls==0


def test_postgres_guarded_failure_receipt_recovers_without_dispatch(conversation_fixture, lifecycle_stores):
    from prosaic_harness import ConversationBindings
    from prosaic_runtime.guards import strict_json
    from test_conversation_rules import artifact
    sessions, _ = lifecycle_stores
    with conversation_fixture(store=sessions) as fx:
        fx.bindings = ConversationBindings(artifact(), version='guard-v1', config=fx.bindings.config,
            policy=fx.bindings.policy, run_policy=fx.bindings.run_policy, guards=[strict_json()])
        fx.controller = fx.fresh_controller()
        snapshot = fx.controller.create()
        fx.queue_text('invalid JSON')
        def crash(event):
            if event['event'] == 'receiptSaved': raise Crash()
        with pytest.raises(Crash):
            fx.controller.send(snapshot.session_id, message_id='one', message='Hello',
                expected_revision=snapshot.revision, on_event=crash)
        reply = fx.fresh_controller().recover(snapshot.session_id).document
        assert reply['failureCode'] == 'ruleViolation' and reply['status'] == 'failed'
        state = sessions.load_session(snapshot.session_id, scope=fx.scope).state
        aid = state['turns'][-1]['attempts'][-1]
        assert sessions.load_receipt(snapshot.session_id, aid, scope=fx.scope)['rules']['violated'] == [
            'companions/check.md:1:strict_json']
        assert fx.fresh_controller().recover(snapshot.session_id).document == reply
        assert fx.provider_calls == 1


def test_postgres_workflow_rule_receipt_recovers_without_dispatch(rule_endpoint, lifecycle_stores, monkeypatch):
    from prosaic_harness import Harness
    from test_workflow_rules_admission import factory, definition, guard
    cfg, requests, replies = rule_endpoint
    _, runs = lifecycle_stores
    flow = factory(cfg=cfg, registered=[guard(check=strict)]).build(definition())
    run_id = uuid4().hex
    h = Harness(flow, store=runs, run_id=run_id)
    replies.extend(['{"ok":false}', '{"ok":true}'])
    def crash(*args): raise Crash()
    monkeypatch.setattr(h, '_accept', crash)
    with pytest.raises(Crash): h.run({})
    fresh = Harness(flow, store=runs, run_id=run_id)
    evidence = fresh.recovery_evidence()
    assert evidence['recoveryStatus'] == 'receiptAvailable'
    assert evidence['receipts'][0]['result']['metadata']['workflow_rules_v1']['rules']['violated']
    assert fresh.resume()['status'] == 'completed'
    assert fresh.resume()['status'] == 'completed' and len(requests) == 2
