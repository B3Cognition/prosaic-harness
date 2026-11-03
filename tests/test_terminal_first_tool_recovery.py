"""ALWAYS prove zero dispatch before repair. NEVER replay terminal work."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from prosaic_runtime import (CustomTool, EndpointConfig, ProsaicArtifact,
    ProsaicRuntime, RuntimeConfig, TerminalCompletion)
from prosaic_harness import (Harness, Validator, WorkflowBindings,
    WorkflowCatalog, WorkflowFactory, WorkflowPolicy)
from test_transport import endpoint


def call(name):
    return {'content': '', 'tool_calls': [{'id': name + '-1', 'type': 'function',
        'function': {'name': name, 'arguments': '{}'}}]}


def workflow(url, effects, *, attempts=2, recovery=True, limits=None,
             rejection=None, **policy):
    def discover(arguments):
        effects.append('discover')
        return {'fields': ['id']}

    def finish(arguments):
        effects.append('finish')
        if rejection == 'artifact':
            return TerminalCompletion({'complete': True}, artifact=object())
        return TerminalCompletion({'complete': rejection != 'schema'},
                                  artifact={'records': [7]})

    tools = {'discover': CustomTool('discover', 'Discover the admitted schema',
        {'type': 'object', 'additionalProperties': False}, discover, 'schema-v1'),
        'finish': CustomTool('finish', 'Complete a synthetic lookup',
        {'type': 'object', 'additionalProperties': False}, finish, 'terminal-v1', terminal=True)}
    agent = ProsaicArtifact('approved', 'subagent', {'name': 'finder',
        'description': 'Find an admitted record', 'tools': ['discover', 'finish']},
        'ALWAYS discover the schema before lookup. NEVER invent records.')
    config = RuntimeConfig({'local': EndpointConfig(url, 'fixture',
        features={'streaming': False})}, {}, 'local', frozenset(tools))
    validators = {'verified': Validator('v1', lambda output, context:
        ['not admitted'] if rejection == 'semantic' else
        [] if context.terminal_completion['artifact'] == {'records': [7]} else ['wrong artifact'])}
    factory = WorkflowFactory(catalog=WorkflowCatalog(agents={'finder': agent}, schemas={'ack': {
        'type': 'object', 'properties': {'complete': {'const': True}},
        'required': ['complete'], 'additionalProperties': False}}),
        bindings=WorkflowBindings(config=config, custom_tools=tools, validators=validators),
        policy=WorkflowPolicy(allowed_agents={'finder'}, allowed_schemas={'ack'},
            allowed_tools=set(tools), allowed_terminal_tools={'finish'},
            allowed_validators={'verified'}, bounded_tool_recovery=recovery,
            max_attempts=max(2, attempts), **policy))
    return factory.build({'version': 1, 'start': 'find', 'limits': limits or {}, 'steps': {
        'find': {'kind': 'agent', 'agent': 'finder', 'schema': 'ack',
            'tools': list(tools), 'require_tools': list(tools), 'initial_tool': 'discover',
            'validators': ['verified'], 'max_attempts': attempts, 'next': 'done'},
        'done': {'kind': 'finish', 'requires': ['find']}}})


def success(replies):
    replies.extend([call('discover'), call('finish'), {'content': 'Unneeded acknowledgement'}])


@pytest.mark.parametrize('refusal,first_usage', [({'content': '{"complete":true}'}, 7),
    (call('finish'), 7), ({'content': 'No native call', '_usage': {'total_tokens': 0}}, 0)],
    ids=['no_native_call', 'wrong_first_tool', 'reported_zero_usage'])
def test_proven_first_tool_refusal_consumes_only_granted_repair(endpoint, tmp_path, refusal, first_usage):
    url, requests, replies = endpoint
    effects = []
    w = workflow(url, effects)
    replies.append(deepcopy(refusal)); success(replies)
    h = Harness(w, tmp_path / 'run')
    state = h.run({'query': 'synthetic'})
    assert state['status'] == 'completed'
    assert effects == ['discover', 'finish'] and len(requests) == 3 and len(replies) == 1
    assert requests[0]['tool_choice'] == requests[1]['tool_choice'] == {
        'type': 'function', 'function': {'name': 'discover'}}
    assert 'validation_feedback' in requests[1]['messages'][-1]['content']
    receipts = h.recovery_evidence()['receipts']
    assert len(receipts) == 2 and [r['result']['exit_code'] for r in receipts] == [1, 0]
    assert [i['token_usage'] for i in state['invocations']] == [first_usage, 14]
    assert not any(e['event'].startswith(('tool_', 'acquisition_')) for e in receipts[0]['events'])
    assert state['bindings']['find']['id'] == receipts[1]['id'] != receipts[0]['id']
    assert receipts[1]['result']['metadata']['terminalCompletion']['artifact'] == {'records': [7]}
    before = deepcopy(receipts)
    fresh = Harness(w, tmp_path / 'run')
    assert fresh.resume()['status'] == 'completed'
    assert fresh.recovery_evidence()['receipts'] == before
    assert effects == ['discover', 'finish'] and len(requests) == 3


@pytest.mark.parametrize('enabled,attempts,count,reason', [
    (False, 2, 1, 'tool_choice_not_honored'), (True, 1, 1, 'attempt_limit'),
    (True, 2, 2, 'attempt_limit'), (True, 3, 3, 'attempt_limit')])
def test_terminal_first_tool_repair_is_opt_in_and_bounded(endpoint, tmp_path, enabled, attempts, count, reason):
    url, requests, replies = endpoint
    effects = []
    replies.extend([{'content': 'No native call'} for _ in range(attempts)])
    h = Harness(workflow(url, effects, attempts=attempts, recovery=enabled), tmp_path / 'run')
    state = h.run({})
    assert state['status'] == 'blocked' and state['reason'] == reason
    assert len(requests) == count and state['calls'] == count and effects == []
    assert len(h.recovery_evidence()['receipts']) == count
    assert h.resume()['status'] == 'blocked' and len(requests) == count


@pytest.mark.parametrize('limit,reason', [({'max_calls': 1}, 'call_limit'),
                                       ({'max_tokens': 7}, 'token_limit')])
def test_pre_dispatch_repair_respects_aggregate_resource_limits(endpoint, tmp_path, limit, reason):
    url, requests, replies = endpoint
    effects = []
    replies.append({'content': 'No native call'}); success(replies)
    state = Harness(workflow(url, effects, limits=limit), tmp_path / 'run').run({})
    assert state['status'] == 'blocked' and state['reason'] == reason
    assert state['calls'] == 1 and len(requests) == 1 and effects == []


@pytest.mark.parametrize('stop', ['cancelled', 'deadline'])
def test_stop_after_first_tool_refusal_never_dispatches_repair(endpoint, tmp_path, stop):
    url, requests, replies = endpoint
    effects, ended = [], []
    replies.append({'content': 'No native call'}); success(replies)
    def observe(event):
        if event['event'] == 'completed': ended.append(True)
    h = Harness(workflow(url, effects), tmp_path / 'run', on_event=observe,
        cancelled=lambda: bool(ended) and stop == 'cancelled',
        clock=lambda: 10_000 if ended and stop == 'deadline' else 0)
    state = h.run({})
    assert state['status'] == 'blocked'
    assert state['reason'] == ('cancelled' if stop == 'cancelled' else 'run_deadline')
    assert state['calls'] == 1 and len(requests) == 1 and effects == []


@pytest.mark.parametrize('change', [
    'timeout', 'cancelled', 'unknown_usage', 'wrong_expected', 'missing_count',
    'boolean_count', 'dispatched_count', 'rounds', 'wrong_reason', 'wrong_provider_code',
    'tool_event', 'acquisition_event', 'terminal_event', 'terminal_metadata', 'stdout',
    'missing_observed_count', 'boolean_observed_count', 'negative_observed_count',
    'missing_budgets', 'bad_budget_shape', 'incomplete_usage', 'boolean_usage',
    'different_usage', 'budget_tool_calls', 'no_provider_request', 'extra_provider_request',
    'boolean_provider_request', 'unknown_usage_status', 'different_reported_usage'])
def test_terminal_repair_rejects_unproven_or_contradictory_receipt(endpoint, tmp_path, monkeypatch, change):
    url, requests, replies = endpoint
    effects = []
    w = workflow(url, effects)
    runtime = ProsaicRuntime(w.config, custom_tools=w.custom_tools)
    original = runtime.run
    def altered(*args, **options):
        result = original(*args, **options)
        metadata = result.metadata
        if metadata.get('failure_reason') != 'tool_choice_not_honored':
            return result
        budget = metadata['invocation_budgets_v1']
        if change == 'timeout': result.timed_out = True
        elif change == 'cancelled': result.exit_code = 130
        elif change == 'unknown_usage': result.token_usage = None
        elif change == 'wrong_expected': metadata['expected_tool'] = 'finish'
        elif change == 'missing_count': metadata.pop('tool_call_count')
        elif change == 'boolean_count': metadata['tool_call_count'] = False
        elif change == 'dispatched_count': metadata['tool_call_count'] = 1
        elif change == 'rounds': metadata['tool_rounds'] = 1
        elif change == 'wrong_reason': metadata['failure_reason'] = 'runtime_failure'
        elif change == 'wrong_provider_code': metadata['provider_error_code'] = 'timeout'
        elif change == 'tool_event': options['on_event']({'event': 'tool_started', 'name': 'discover'})
        elif change == 'acquisition_event': options['on_event']({'event': 'acquisition_completed'})
        elif change == 'terminal_event': options['on_event']({'event': 'completed', 'terminalCompletion': {}})
        elif change == 'terminal_metadata': metadata['terminalCompletion'] = {'artifactIncluded': False}
        elif change == 'stdout': result.stdout = '{"complete":true}'
        elif change == 'missing_observed_count': metadata.pop('observed_tool_call_count')
        elif change == 'boolean_observed_count': metadata['observed_tool_call_count'] = False
        elif change == 'negative_observed_count': metadata['observed_tool_call_count'] = -1
        elif change == 'missing_budgets': metadata.pop('invocation_budgets_v1')
        elif change == 'bad_budget_shape': budget['extra'] = 0
        elif change == 'incomplete_usage': budget['usage_complete'] = False
        elif change == 'boolean_usage': budget['reported_tokens'] = True
        elif change == 'different_usage': budget['reported_tokens'] = 8
        elif change == 'budget_tool_calls': budget['tool_calls'] = 1
        elif change == 'no_provider_request': budget['provider_requests'] = 0
        elif change == 'extra_provider_request': budget['provider_requests'] = 2
        elif change == 'boolean_provider_request': budget['provider_requests'] = True
        elif change == 'unknown_usage_status': metadata['token_usage_status'] = 'unknown'
        elif change == 'different_reported_usage': metadata['reported_token_usage'] = 8
        return result
    monkeypatch.setattr(runtime, 'run', altered)
    replies.append({'content': 'No native call'}); success(replies)
    h = Harness(w, tmp_path / 'run', runtime=runtime)
    state = h.run({})
    assert state['status'] == 'blocked' and state['outputs'] == {}
    assert state['calls'] == 1 and len(requests) == 1 and effects == []
    assert len(h.recovery_evidence()['receipts']) == 1
    assert h.resume()['status'] == 'blocked' and len(requests) == 1


@pytest.mark.parametrize('rejection', ['missing_terminal', 'artifact', 'schema', 'semantic'])
def test_terminal_rejection_after_dispatch_cannot_enter_pre_dispatch_repair(endpoint, tmp_path, rejection):
    url, requests, replies = endpoint
    effects = []
    replies.append(call('discover'))
    replies.append({'content': '{"complete":true}'} if rejection == 'missing_terminal' else call('finish'))
    h = Harness(workflow(url, effects, attempts=3, rejection=rejection), tmp_path / 'run')
    state = h.run({})
    assert state['status'] == 'blocked' and state['outputs'] == {}
    assert state['calls'] == 1 and len(requests) == 2
    assert effects == (['discover'] if rejection == 'missing_terminal' else ['discover', 'finish'])
    assert h.resume()['status'] == 'blocked' and len(requests) == 2


@pytest.mark.parametrize('crash_after', [1, 2])
def test_fresh_worker_adopts_each_saved_receipt_without_replaying_dispatch(endpoint, tmp_path, monkeypatch, crash_after):
    url, requests, replies = endpoint
    effects, saved = [], []
    w = workflow(url, effects)
    replies.append({'content': 'No native call'}); success(replies)
    h = Harness(w, tmp_path / 'run')
    original = h.store.save_receipt
    def crash(*args):
        original(*args)
        saved.append(deepcopy(args[2]))
        if len(saved) == crash_after: raise OSError('crash after immutable receipt save')
    monkeypatch.setattr(h.store, 'save_receipt', crash)
    with pytest.raises(OSError, match='crash after immutable receipt save'): h.run({})
    before = deepcopy(saved)
    # Reconstruct trusted bindings in an isolated interpreter, with no parent
    # callbacks or admission objects available to the recovering worker.
    worker = '''
import json, os, sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from test_terminal_first_tool_recovery import workflow
from prosaic_harness import Harness
effects = []
h = Harness(workflow(sys.argv[3], effects), sys.argv[4])
state = h.resume()
print(json.dumps({'pid': os.getpid(), 'effects': effects, 'status': state['status'],
    'receipts': h.recovery_evidence()['receipts'],
    'usage': [i['token_usage'] for i in state['invocations']]}))
'''
    process = subprocess.run([sys.executable, '-I', '-c', worker,
        str(Path(__file__).resolve().parents[1] / 'src'), str(Path(__file__).resolve().parent),
        url, str(tmp_path / 'run')], cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stdout + process.stderr
    recovered = json.loads(process.stdout)
    assert recovered['status'] == 'completed'
    assert effects + recovered['effects'] == ['discover', 'finish'] and len(requests) == 3
    assert recovered['receipts'][:crash_after] == before
    assert len(recovered['receipts']) == 2 and recovered['usage'] == [7, 14]
    fresh = Harness(w, tmp_path / 'run')
    assert fresh.resume()['status'] == 'completed' and len(requests) == 3
    assert fresh.recovery_evidence()['receipts'] == recovered['receipts']
