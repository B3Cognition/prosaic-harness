import json
import pytest
from prosaic_harness import ContextPackReader,ConversationError
from test_context_pack_conversation import pack_chat
from test_workflow_rules_execution import rule_endpoint


def test_revoked_reader_history_blocks_send_without_new_pack(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint;denied=[False];uses=[]
    def authorize(use):
        uses.append(use)
        return not (denied[0] and use.purpose=='historyReuse' and any(e['sourceAlias']=='facts' for e in use.source_refs))
    reader=ContextPackReader()
    chat,candidates,store,scope=pack_chat(cfg,tmp_path,authorize=authorize,reader=reader)
    session=chat.create();pack=candidates(facts='READER-FACT-719')
    citation=pack.variants[0]['index'][0]['citationId']
    replies.extend([{'name':'read_context_item','input':{'citationId':citation}},'Answer from reader'])
    reply=chat.send(session.session_id,message_id='first',message='Question',expected_revision=session.revision,context_pack=pack)
    assert 'READER-FACT-719' in json.dumps(requests[1]) and reader.active_count==0
    assert next(use for use in uses if use.purpose=='deferredRead').session_id==session.session_id
    before=store.load_session(session.session_id,scope=scope);denied[0]=True
    exposures=before.state['contextPacks']['turnExposures']['1']['entries']
    assert any(e['sourceAlias']=='facts' and e['disclosure']=='read' for e in exposures)
    from prosaic_harness.session_contracts import seal,verify_session
    from prosaic_harness import StoreCorrupt
    from copy import deepcopy
    forged=deepcopy(before.state)
    forged['contextPacks']['turnExposures']['1']['entries']=[e for e in exposures if e['disclosure']!='read']
    with pytest.raises(StoreCorrupt): verify_session(seal(forged))
    assert chat.history(session.session_id)
    assert chat.send(session.session_id,message_id='first',message='Question',expected_revision=session.revision,
        context_pack=pack).document==reply.document
    with pytest.raises(ConversationError,match='contextUseDenied'):
        chat.send(session.session_id,message_id='second',message='Follow-up',expected_revision=reply.document['revision'])
    assert len(requests)==2 and store.load_session(session.session_id,scope=scope)==before


def test_plain_turn_inherits_provenance_without_copying_inline_pack_bodies(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint;replies.extend(['First answer','Follow-up answer']);denied=[False]
    def authorize(use): return not (denied[0] and use.purpose=='historyReuse' and use.source_refs)
    chat,candidates,store,scope=pack_chat(cfg,tmp_path,authorize=authorize);session=chat.create()
    first=chat.send(session.session_id,message_id='first',message='Question',expected_revision=session.revision,
        context_pack=candidates(task='SELECTED-TASK-719'))
    second=chat.send(session.session_id,message_id='second',message='Follow-up',expected_revision=first.document['revision'])
    assert second.document['status']=='completed' and 'SELECTED-TASK-719' not in json.dumps(requests[1])
    saved=store.load_session(session.session_id,scope=scope).state
    assert saved['contextPacks']['turnExposures']['2']==saved['contextPacks']['turnExposures']['1']
    aid=saved['turns'][1]['attempts'][0];packet=store.load_receipt(session.session_id,aid,scope=scope)
    assert packet['version']==3 and packet['contextPack'] is None
    denied[0]=True
    with pytest.raises(ConversationError,match='contextUseDenied'):
        chat.send(session.session_id,message_id='third',message='Another',expected_revision=second.document['revision'])
    assert len(requests)==2
