"""Optional real PostgreSQL acceptance for the public lifecycle and decision journal."""
import os
from uuid import uuid4
import pytest
from test_conversation_workflow import workflow_fixture
from support.conversation_host import conversation_fixture
from test_conversation_recovery import Crash


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
