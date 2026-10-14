"""Synthetic host counter registration using only public installed SDK APIs."""
import json
import prosaic_runtime as api


def fixture_context(provider='openai-compatible', *, model='synthetic',
                    mode='fullHistory', capacity=4096, reserve=128, count=None,
                    checks=128, byte_allowance=33_554_432, timeout_ms=2000,
                    identity='synthetic-byte-v1'):
    class Counter:
        def count_tokens(self, request):
            return count(request) if count is not None else len(
                json.dumps(request, allow_nan=False).encode('utf-8'))
    descriptor = api.TokenCounterDescriptor(identity, provider, model,
        {'openai-compatible': 'openai-chat-v1', 'anthropic': 'anthropic-messages-v1'}[provider],
        1_048_576, '1', '0'*64, '1'*64, 'exact', 'Synthetic byte-unit fixture grammar only.')
    registry = api.TokenCounterRegistry({identity: api.TokenCounterRegistration(descriptor, Counter())})
    policy = api.ContextPolicy(mode, capacity, reserve, 0, identity,
                              checks, byte_allowance, timeout_ms)
    return policy, registry
