"""Counters are host capability declarations, never model/user authority."""
from dataclasses import replace
import hashlib
import pytest
import prosaic_runtime as api
from prosaic_harness import (ConversationError, Conversation, MemorySessionStore)
from support.conversations import binding_factory, scope
from support.context_counter import fixture_context


def interpreter():
    return api.ProsaicArtifact('interpreter', 'subagent', {'name': 'interpreter',
        'description': 'Synthetic current-choice interpreter', 'model_tier': 'interpret'},
        'ALWAYS interpret only current choices. NEVER authorize effects.')


def test_legacy_binding_bytes_match_pre_feature_golden(binding_factory):
    binding = binding_factory(context_policy=None, interpretation_context_policy=None)
    golden = '6ad440795e778ced1936cbf108ff5b3254eeb068ca227ee12de88a719b14de23'
    assert binding.identity == golden
    assert hashlib.sha256(binding._encoded).hexdigest() == golden
    assert binding.context_enabled is False


def test_interpreter_context_cannot_exist_without_interpreter(binding_factory):
    policy, counters = fixture_context()
    with pytest.raises(ConversationError) as caught:
        binding_factory(interpretation_context_policy=policy, token_counters=counters)
    assert caught.value.code == 'bindingMismatch'


@pytest.mark.parametrize('ordinary,interpreting', [(True, False), (False, True), (True, True)])
def test_context_policies_resolve_distinct_endpoints_without_inheritance(binding_factory, ordinary, interpreting):
    base = binding_factory()
    config = base.config
    config.profiles['interpreter'] = api.EndpointConfig('http://127.0.0.1:9/v1', 'other', provider='anthropic')
    config.routes['interpret'] = 'interpreter'
    chat_policy, chat_counters = fixture_context()
    interpret_policy, interpret_counters = fixture_context('anthropic', model='other', identity='interpret-v1')
    counters = api.TokenCounterRegistry({
        chat_policy.counter_identity: chat_counters.resolve(chat_policy.counter_identity),
        interpret_policy.counter_identity: interpret_counters.resolve(interpret_policy.counter_identity)})
    binding = binding_factory(config=config, interpreter=interpreter(),
        context_policy=chat_policy if ordinary else None,
        interpretation_context_policy=interpret_policy if interpreting else None,
        token_counters=counters)
    material = binding.readmit()
    assert binding.context_enabled is True
    assert (binding.context_policy is not None) == ordinary
    assert (binding.interpretation_context_policy is not None) == interpreting
    assert (material.get('contextPolicy') is not None) == ordinary
    assert (material.get('interpretationContextPolicy') is not None) == interpreting
    assert binding.interpretation_policy.max_tool_calls == 0


def test_binding_does_not_execute_counter_during_configuration_readmission(binding_factory):
    calls = []
    policy, counters = fixture_context(count=lambda request: calls.append(request) or 1)
    binding = binding_factory(context_policy=policy, token_counters=counters)
    binding.readmit()
    binding.runtime()
    assert calls == []
    assert binding.context_policy.counter_identity == policy.counter_identity


def test_descriptor_capacity_and_endpoint_drift_reject(binding_factory):
    policy, counters = fixture_context(model='wrong')
    with pytest.raises(ConversationError):
        binding_factory(context_policy=policy, token_counters=counters)
    policy, counters = fixture_context(capacity=1_048_577)
    with pytest.raises(ConversationError):
        binding_factory(context_policy=policy, token_counters=counters)
    policy, counters = fixture_context()
    binding = binding_factory(context_policy=policy, token_counters=counters)
    registration = counters.resolve(policy.counter_identity)
    object.__setattr__(binding, '_token_counters', api.TokenCounterRegistry({policy.counter_identity:
        api.TokenCounterRegistration(replace(registration.descriptor, tokenizer_assets_digest='2'*64), registration.counter)}))
    with pytest.raises(ConversationError):
        binding.readmit()


def test_missing_runtime_context_capability_is_closed(binding_factory, monkeypatch):
    policy, counters = fixture_context()
    monkeypatch.setattr(api.ProsaicRuntime, 'capabilities', api.ProsaicRuntime.capabilities - {'context_assembly_v1'})
    with pytest.raises(ConversationError) as caught:
        binding_factory(context_policy=policy, token_counters=counters)
    assert caught.value.code == 'capabilityMissing'
    assert binding_factory().context_enabled is False


def test_store_without_context_capability_accepts_only_legacy_binding(binding_factory, scope):
    class LegacyStore(MemorySessionStore):
        capabilities = frozenset()
    store = LegacyStore(namespace=scope.namespace)
    store.initialize()
    assert Conversation(binding_factory(), store=store, scope=scope).create().state['version'] == 1
    policy, counters = fixture_context()
    with pytest.raises(ConversationError) as caught:
        Conversation(binding_factory(context_policy=policy, token_counters=counters), store=store, scope=scope).create()
    assert caught.value.code == 'capabilityMissing'
