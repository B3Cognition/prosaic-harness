from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread
import pytest
from prosaic_harness import ConversationPolicy, ConversationError, FileSessionStore
from support.conversation_host import conversation_fixture
from support.conversations import scope, binding_factory


@pytest.mark.parametrize('message',['x'*1000,'\\'*500,'\x00'*200])
def test_failed_user_projection_must_fit_before_admission(conversation_fixture,message):
    with conversation_fixture(policy=replace(ConversationPolicy(),max_turn_bytes=1000)) as fx:
        snapshot=fx.controller.create()
        fx.queue_known_failure()
        with pytest.raises(ConversationError):
            fx.controller.send(snapshot.session_id,message_id='too-large',message=message,
                expected_revision=snapshot.revision)
        assert fx.provider_calls==0 and fx.store.load_session(snapshot.session_id,scope=fx.scope)==snapshot


@pytest.mark.parametrize('changes',[
    {'max_public_bytes':73728},{'max_receipt_bytes':210000}])
def test_policy_accounts_for_canonical_answer_encoding_before_effects(binding_factory,changes):
    with pytest.raises(ConversationError,match='bindingMismatch'):
        binding_factory(policy=replace(ConversationPolicy(),**changes))


@pytest.mark.parametrize('answer',['\\'*60000,'\x00'*20000])
def test_compatible_envelopes_save_and_project_escaped_answers(conversation_fixture,answer):
    with conversation_fixture(policy=replace(ConversationPolicy(),max_receipt_bytes=400000)) as fx:
        snapshot=fx.controller.create()
        fx.queue_text(answer)
        arguments=dict(message_id='one',message='Hello',expected_revision=snapshot.revision)
        reply=fx.controller.send(snapshot.session_id,**arguments)
        assert reply.document['answer']==answer and reply.document['status']=='completed'
        assert fx.controller.status(snapshot.session_id).document==reply.document
        assert fx.controller.send(snapshot.session_id,**arguments).document==reply.document
        assert fx.controller.recover(snapshot.session_id).document==reply.document
        assert fx.provider_calls==1


def test_concurrent_atomic_snapshot_reads_never_report_corruption(tmp_path,scope,binding_factory,monkeypatch):
    import os
    from prosaic_harness.session_contracts import new_session
    store=FileSessionStore(tmp_path/'sessions',namespace=scope.namespace)
    store.initialize()
    sid='a'*32
    with store.lease(sid,scope=scope) as lease:
        state=new_session(sid,scope,binding_factory())
        revision=store.create_session(sid,state,lease,scope=scope)
        opened,replaced=Event(),Event()
        original=os.stat
        def at_boundary(path,*args,**kwargs):
            if path=='session.json' and current_thread().name.startswith('snapshot-reader'):
                opened.set()
                assert replaced.wait(5)
            return original(path,*args,**kwargs)
        monkeypatch.setattr(os,'stat',at_boundary)
        def reader():
            assert store.load_session(sid,scope=scope).state==state
        with ThreadPoolExecutor(max_workers=1,thread_name_prefix='snapshot-reader') as pool:
            task=pool.submit(reader)
            try:
                assert opened.wait(5)
                store.save_session(sid,state,revision,lease,scope=scope)
            finally: replaced.set()
            task.result(timeout=5)
    store.close()
