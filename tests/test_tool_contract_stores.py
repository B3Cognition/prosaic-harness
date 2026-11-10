"""Enabled namespaces are explicit; receipts stay authoritative after reopen."""
import json
import pytest
import prosaic_harness as api
from test_tool_contract_conversation import chat_case
from test_tool_contract_workflow import flow,queue_answer,controller
from test_workflow_rules_execution import rule_endpoint


@pytest.mark.parametrize('kind',['memory','file'])
def test_new_contract_roundtrips_and_reopens(rule_endpoint,tmp_path,kind):
    cfg,requests,replies=rule_endpoint;calls=[]
    original,bindings,_,scope=chat_case(cfg,calls=calls)
    store=(api.MemorySessionStore(namespace='test') if kind=='memory' else api.FileSessionStore(tmp_path/'session',namespace='test'))
    store.initialize(tool_contracts=True)
    chat=api.Conversation(bindings,store=store,scope=scope);created=chat.create();queue_answer(replies)
    result=chat.send(created.session_id,message_id='one',message='Review',expected_revision=created.revision)
    reopened=store if kind=='memory' else api.FileSessionStore(tmp_path/'session',namespace='test')
    assert 'tool_contracts_v1' in reopened.capabilities
    assert api.Conversation(bindings,store=reopened,scope=scope).status(created.session_id).document==result.document
    assert len(requests)==2 and calls==[1]


@pytest.mark.parametrize('kind',['memory','file'])
def test_existing_namespace_needs_explicit_migration(tmp_path,kind):
    store=api.MemorySessionStore(namespace='test') if kind=='memory' else api.FileSessionStore(tmp_path/'session',namespace='test')
    store.initialize()
    assert 'tool_contracts_v1' not in store.capabilities
    with pytest.raises(api.StoreIncompatible):store.initialize(tool_contracts=True)
    store.migrate_tool_contract_storage()
    assert 'tool_contracts_v1' in store.capabilities


def test_workflow_file_receipt_reopens_and_corruption_is_refused(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint;calls=[];workflow=flow(cfg,calls=calls);queue_answer(replies)
    host=controller(workflow,tmp_path);state=host.run({'task':'Review'})
    reopened=api.FileRunStore(tmp_path/'store',namespace='test')
    assert api.Harness(workflow,store=reopened,run_id=state['run_id']).resume()['status']=='completed'
    aid=state['invocations'][0]['id'];packet=reopened.load_receipt(state['run_id'],aid)
    packet['toolContractV1']['citations']['answerSha256']='0'*64
    from prosaic_harness.contracts import seal,validate_receipt
    with pytest.raises(ValueError):validate_receipt(seal(packet),state,dict(id=aid,step='review',arguments_sha256=packet['arguments_sha256'],arguments=packet['arguments']),workflow)
    assert len(requests)==2 and calls==[1]


def test_session_marker_is_distinct_and_legacy_bytes_stay_unchanged(tmp_path):
    old=api.FileSessionStore(tmp_path/'old',namespace='test');old.initialize()
    before=(tmp_path/'old/test/.conversation-store.json').read_bytes()
    old.check_ready()
    assert before==(tmp_path/'old/test/.conversation-store.json').read_bytes()
    new=api.FileSessionStore(tmp_path/'new',namespace='test');new.initialize(tool_contracts=True)
    marker=(tmp_path/'new/test/.conversation-store.json').read_bytes()
    assert marker!=before and json.loads(marker)['storageContract']==4


def test_existing_pack_run_namespace_migrates_without_rewriting_records(tmp_path):
    store=api.FileRunStore(tmp_path/'workflows',namespace='test');store.initialize(context_packs=True)
    assert 'tool_contracts_v1' not in store.capabilities
    with pytest.raises(api.StoreIncompatible):store.initialize(tool_contracts=True)
    store.migrate_tool_contract_storage()
    assert 'tool_contracts_v1' in api.FileRunStore(tmp_path/'workflows',namespace='test').capabilities
