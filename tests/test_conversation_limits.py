from dataclasses import replace
import pytest
from prosaic_harness import ConversationPolicy, ConversationError
from support.conversation_host import conversation_fixture


@pytest.mark.parametrize('field,value,message',[('max_user_bytes',4,'ééé'),('max_input_bytes',600,'x'*500)])
def test_rejected_input_has_no_history_attempt_or_provider_call(conversation_fixture,field,value,message):
    with conversation_fixture(policy=replace(ConversationPolicy(),**{field:value})) as fx:
        snapshot=fx.controller.create()
        with pytest.raises(ConversationError):
            fx.controller.send(snapshot.session_id,message_id='rejected',message=message,expected_revision=snapshot.revision)
        current=fx.store.load_session(snapshot.session_id,scope=fx.scope)
        assert current==snapshot and fx.provider_calls==0


def test_zero_provider_allowance_blocks_admission(conversation_fixture):
    with conversation_fixture(policy=replace(ConversationPolicy(),max_provider_requests=0)) as fx:
        snapshot=fx.controller.create()
        with pytest.raises(ConversationError,match='sessionLimit'):
            fx.controller.send(snapshot.session_id,message_id='rejected',message='Hello',expected_revision=snapshot.revision)
        assert not fx.controller.history(snapshot.session_id) and fx.provider_calls==0
