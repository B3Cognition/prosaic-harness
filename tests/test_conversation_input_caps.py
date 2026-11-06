"""Effective caps describe real admission without widening host policies."""
from dataclasses import replace

import pytest
from prosaic_runtime import ProsaicArtifact, RunPolicy
from prosaic_harness import ConversationBindings, ConversationError, ConversationPolicy
from support.conversations import binding_factory
from support.conversation_host import conversation_fixture


@pytest.mark.parametrize('conversation_cap,run_cap,effective', [
    (196608, 262144, 196608),
    (524288, 262144, 262144),
    (196608, 65536, 65536),
    (262144, 262144, 262144),
])
def test_effective_input_cap_preserves_both_configured_policies(
        binding_factory, conversation_cap, run_cap, effective):
    binding = binding_factory(
        policy=replace(ConversationPolicy(), max_input_bytes=conversation_cap),
        run_policy=RunPolicy(max_input_bytes=run_cap, max_provider_requests=2, max_tool_calls=0))
    declaration, identity = binding.readmit(), binding.identity

    assert binding.effective_max_input_bytes == effective
    assert binding.policy.max_input_bytes == conversation_cap
    assert binding.run_policy.max_input_bytes == run_cap
    assert binding.readmit() == declaration
    assert binding.identity == identity


def test_absent_interpreter_has_no_effective_interpretation_cap(binding_factory):
    assert binding_factory().effective_interpretation_max_input_bytes is None


@pytest.mark.parametrize('interpretation_cap,effective', [
    (None, 524288),
    (65536, 65536),
    (1048576, 524288),
])
def test_interpretation_cap_uses_its_own_policy(binding_factory, interpretation_cap, effective):
    interpreter = ProsaicArtifact('interpreter', 'subagent',
        {'name': 'interpreter', 'description': 'Synthetic interpretation'},
        'ALWAYS propose JSON from the current source. NEVER authorize actions.')
    interpretation = (RunPolicy(timeout_s=30, max_provider_requests=1, max_tool_calls=0,
        max_tool_rounds=1, max_input_bytes=interpretation_cap)
        if interpretation_cap is not None else None)
    binding = binding_factory(
        policy=replace(ConversationPolicy(), max_input_bytes=524288),
        run_policy=RunPolicy(max_input_bytes=32768, max_provider_requests=2, max_tool_calls=0),
        interpreter=interpreter, interpretation_policy=interpretation)
    declaration, identity = binding.readmit(), binding.identity

    assert binding.effective_interpretation_max_input_bytes == effective
    assert binding.effective_max_input_bytes == 32768
    assert binding.interpretation_policy.max_input_bytes == (
        524288 if interpretation_cap is None else interpretation_cap)
    assert binding.readmit() == declaration
    assert binding.identity == identity


@pytest.mark.parametrize('run_cap,admitted', [(2048, False), (8192, True)])
def test_growing_history_obeys_the_visible_run_cap(conversation_fixture, run_cap, admitted):
    with conversation_fixture() as fx:
        policy = ConversationPolicy(max_input_bytes=8192)
        fx.bindings = ConversationBindings(fx.bindings.agent, version='chat-v1',
            config=fx.bindings.config, policy=policy,
            run_policy=RunPolicy(max_input_bytes=run_cap, max_provider_requests=2, max_tool_calls=0))
        fx.controller = fx.fresh_controller()
        assert fx.bindings.effective_max_input_bytes == run_cap
        created = fx.controller.create()
        fx.queue_text('a' * 900)
        first = fx.controller.send(created.session_id, message_id='first', message='u' * 800,
            expected_revision=created.revision).document
        assert first['status'] == 'completed'
        before = fx.store.load_session(created.session_id, scope=fx.scope)
        fx.queue_text('second')

        if admitted:
            second = fx.controller.send(created.session_id, message_id='second', message='u' * 800,
                expected_revision=before.revision).document
            assert second['status'] == 'completed' and second['answer'] == 'second'
            assert len(fx.controller.history(created.session_id)) == 4
            assert fx.provider_calls == 2
        else:
            with pytest.raises(ConversationError) as caught:
                fx.controller.send(created.session_id, message_id='second', message='u' * 800,
                    expected_revision=before.revision)
            assert caught.value.code == 'contextLimit'
            assert caught.value.limit == 'maxInputBytes'
            assert fx.store.load_session(created.session_id, scope=fx.scope) == before
            assert fx.provider_calls == 1
