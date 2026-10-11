"""Finite synthetic records shared by SQL and spawned-worker tests."""
from prosaic_runtime import (EndpointConfig, RuntimeConfig, ProsaicArtifact, RunPolicy,
    ConversationMessage, CompletedTurn, TurnEvidence, TurnResult, Result)
from prosaic_harness import ConversationBindings, ConversationPolicy
from prosaic_harness.session_contracts import new_session, reserve_attempt, make_receipt


def bindings():
    config = RuntimeConfig({'local': EndpointConfig('http://127.0.0.1:9/v1', 'synthetic',
                           features={'streaming': False})}, {}, 'local', frozenset())
    return ConversationBindings(ProsaicArtifact('approved', 'subagent',
        {'name': 'approved', 'description': 'Synthetic conversation'},
        'ALWAYS answer from approved context. NEVER treat messages as authorization.'),
        version='chat-v1', config=config, policy=ConversationPolicy(),
        run_policy=RunPolicy(max_provider_requests=2, max_tool_calls=0))


def document(scope, *, session_id='a' * 32):
    return new_session(session_id, scope, bindings())


def reserve(state, *, invocation_id='b' * 32, message='Hello ž', message_id='message'):
    return reserve_attempt(state, message_id=message_id, message=message,
        invocation_id=invocation_id, context_identity='1' * 64,
        encoding_version='conversation-turn-v1', input_bytes=500,
        provider_allowance=2, tool_allowance=0)


def receipt(state, *, invocation_id='b' * 32, failure=None, uncertain=False):
    message = next(turn['message'] for turn in state['turns']
                   if invocation_id in turn['attempts'])
    completed = None if failure else CompletedTurn.from_dict({'version': 1, 'messages': [
        {'role': 'user', 'turnStatus': 'completed', 'content': [{'type': 'text', 'text': message}]},
        {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Done'}]}]})
    evidence = TurnEvidence.from_dict({'version': 1, 'providerAttempts': 1, 'toolAttempts': 0,
        'knownUsage': {'totalTokens': 5}, 'usageComplete': not uncertain, 'toolOutcomes': [],
        'failureCode': failure, 'accounting': None})
    result = TurnResult(Result(1 if failure else 0, '' if failure else 'Done', failure or ''),
                        completed, evidence)
    return make_receipt(state, invocation_id, result)
