"""Real owned PostgreSQL storage; startup/readiness never enables contracts."""
import pytest
import psycopg
from prosaic_harness import StoreIncompatible,StoreBusy,Conversation,ConversationScope,Harness
from prosaic_harness_postgres import PostgresRunStore,PostgresSessionStore
from prosaic_harness_postgres import schema,session_schema
from test_cli import grant_runtime
from test_session_schema import grant_conversations
from test_workflow_rules_execution import rule_endpoint
from test_tool_contract_workflow import flow,queue_answer
from test_tool_contract_conversation import chat_case


@pytest.mark.parametrize('kind',['workflows','conversations'])
def test_explicit_migration_and_worker_ddl_denial(db_admin_dsn,runtime_dsn,kind):
    cls=PostgresRunStore if kind=='workflows' else PostgresSessionStore
    with cls(db_admin_dsn,namespace='test') as owner:
        owner.initialize()
        assert 'tool_contracts_v1' not in owner.capabilities
        with pytest.raises(StoreIncompatible):owner.initialize(tool_contracts=True)
    (grant_runtime if kind=='workflows' else grant_conversations)(db_admin_dsn,runtime_dsn)
    with cls(runtime_dsn,namespace='test') as worker,cls(db_admin_dsn,namespace='test') as owner:
        with pytest.raises(StoreIncompatible):worker.migrate_tool_contract_storage()
        kwargs={'scope':ConversationScope('test','sandbox','app','tenant','actor')} if kind=='conversations' else {}
        with worker.lease('a'*32,**kwargs):
            with pytest.raises(StoreBusy):owner.migrate_tool_contract_storage()
        owner.migrate_tool_contract_storage()
        worker.check_ready();assert 'tool_contracts_v1' in worker.capabilities
        legacy=schema if kind=='workflows' else session_schema
        with pytest.raises(StoreIncompatible):worker._transport.call(lambda c:legacy.ready_on_connection(c,expected_versions=(1,1) if kind=='workflows' else (2,2)))


@pytest.mark.parametrize('kind',['workflows','conversations'])
def test_enabled_receipt_roundtrip_and_reopen(db_admin_dsn,rule_endpoint,kind):
    cfg,requests,replies=rule_endpoint;calls=[];queue_answer(replies)
    cls=PostgresRunStore if kind=='workflows' else PostgresSessionStore
    with cls(db_admin_dsn,namespace='test') as store:
        store.initialize(tool_contracts=True)
        if kind=='workflows':
            workflow=flow(cfg,calls=calls);state=Harness(workflow,store=store,run_id='a'*32).run({'task':'Review'})
            assert state['status']=='completed'
            aid=state['invocations'][0]['id'];saved=store.load_receipt(state['run_id'],aid)
        else:
            _,bindings,_,scope=chat_case(cfg,calls=calls)
            chat=Conversation(bindings,store=store,scope=scope);session=chat.create()
            result=chat.send(session.session_id,message_id='one',message='Review',expected_revision=session.revision)
            assert result.document['status']=='completed'
            state=store.load_session(session.session_id,scope=scope).state;aid=state['turns'][0]['attempts'][0]
            saved=store.load_receipt(session.session_id,aid,scope=scope)
    with cls(db_admin_dsn,namespace='test') as reopened:
        reopened.check_ready()
        if kind=='workflows':
            assert Harness(workflow,store=reopened,run_id=state['run_id']).resume()['status']=='completed'
            assert reopened.load_receipt(state['run_id'],aid)==saved
        else:
            assert Conversation(bindings,store=reopened,scope=scope).status(session.session_id).document==result.document
            assert reopened.load_receipt(session.session_id,aid,scope=scope)==saved
    assert calls==[1] and len(requests)==2
