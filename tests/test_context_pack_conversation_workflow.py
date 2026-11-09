import pytest
from prosaic_harness import (ContextPackBindings,ContextPackSpec,ContextSlot,InputSource,
    ContextAuthorizer,ContextPacker,ConversationError)
from prosaic_harness.context_packs.sources import capture_sources
from support.context_pack_cases import scope_case
from support.conversation_host import conversation_fixture
from test_conversation_workflow import workflow_fixture


def packs_case():
    spec=ContextPackSpec('chat','1',[ContextSlot('task',required=True)],task_source='task')
    bindings=ContextPackBindings(specs={'chat':spec},sources={'task':InputSource('/task')},
        scope=scope_case(),authorizer=ContextAuthorizer('access','1',lambda use:True))
    candidates=ContextPacker().compose(spec,capture_sources(spec,{'request':{'task':'Review'}},{},bindings))
    return bindings,candidates


def test_interpreter_receipt_keeps_v3_wrapper_without_pack_input(workflow_fixture):
    bindings,candidates=packs_case()
    with workflow_fixture(context_packs=bindings) as fx:
        reply=fx.send('the second result',{'choice':'second'})
        assert reply.document['pendingInteraction']['stepId']=='approval'
        state=fx.store.load_session(fx.session_id,scope=fx.scope).state
        aid=state['turns'][0]['attempts'][0]
        packet=fx.store.load_receipt(fx.session_id,aid,scope=fx.scope)
        assert state['version']==packet['version']==3
        assert packet['contextPack'] is None and packet['encodingVersion']=='conversation-turn-v1'


def test_structured_choice_in_pack_namespace_has_complete_sidecars(workflow_fixture):
    bindings,candidates=packs_case()
    with workflow_fixture(context_packs=bindings) as fx:
        current=fx.controller.status(fx.session_id).document
        reply=fx.controller.choose(fx.session_id,message_id='pick',message='the second result',choice='second',
            interaction_ref=current['pendingInteraction']['reference'],expected_revision=current['revision'])
        assert reply.document['pendingInteraction']['stepId']=='approval' and fx.provider_calls==0
        state=fx.store.load_session(fx.session_id,scope=fx.scope).state
        assert state['contextPacks']['turnExposures']=={'1':None}


def test_attached_workflow_rejects_ordinary_pack_before_interpretation(workflow_fixture):
    bindings,candidates=packs_case()
    with workflow_fixture(context_packs=bindings) as fx:
        current=fx.controller.status(fx.session_id).document
        with pytest.raises(ConversationError,match='contextCapabilityMissing'):
            fx.controller.send(fx.session_id,message_id='pick',message='the second result',context_pack=candidates,
                interaction_ref=current['pendingInteraction']['reference'],expected_revision=current['revision'])
        assert fx.provider_calls==0 and fx.controller.status(fx.session_id).document==current
