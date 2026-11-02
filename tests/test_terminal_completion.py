"""A durable host artifact, not model acknowledgement, admits completion."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest
from prosaic_runtime import CustomTool, EndpointConfig, ProsaicArtifact, ProsaicRuntime, RuntimeConfig, RunLimits, TerminalCompletion
from prosaic_harness import (Harness, WorkflowBindings, WorkflowCatalog, WorkflowFactory,
    WorkflowPolicy, WorkflowAdmissionError, Validator)
from test_transport import endpoint


def factory(url, *, handler=None, validators=None, terminal=True, limits=None, parameters=None, **caps):
    tool = CustomTool('finish', 'Complete a synthetic search',
        parameters or {'type': 'object', 'additionalProperties': False},
        handler or (lambda a: TerminalCompletion({'complete': True}, artifact={'rows': [7], 'season': '2024/2025'})),
        'v2', terminal=terminal)
    agent = ProsaicArtifact('approved', 'subagent', {'name': 'search',
        'description': 'Search approved synthetic records', 'tools': ['finish']},
        'ALWAYS execute finish. NEVER invent search results.')
    config = RuntimeConfig({'local': EndpointConfig(url, 'fixture', features={'streaming': False})},
        {}, 'local', frozenset({'finish'}), limits=limits or RunLimits())
    return WorkflowFactory(catalog=WorkflowCatalog(agents={'search': agent}, schemas={'ack': {
        'type': 'object', 'properties': {'complete': {'const': True}},
        'required': ['complete'], 'additionalProperties': False}}),
        bindings=WorkflowBindings(config=config, custom_tools={'finish': tool}, validators=validators),
        policy=WorkflowPolicy(allowed_agents={'search'}, allowed_schemas={'ack'},
            allowed_tools={'finish'}, allowed_validators=set(validators or {}),
            allowed_terminal_tools={'finish'} if terminal else set(), **caps))


def graph(*, validators=()):
    return {'version': 1, 'name': 'host-completion', 'start': 'search', 'steps': {
        'search': {'kind': 'agent', 'agent': 'search', 'schema': 'ack', 'tools': ['finish'],
            'require_tools': ['finish'], 'validators': list(validators), 'next': 'done'},
        'done': {'kind': 'finish', 'requires': ['search']}}}


def queue(replies):
    replies.append({'content': '', 'tool_calls': [{'id': 'finished-1', 'type': 'function',
        'function': {'name': 'finish', 'arguments': '{}'}}]})
    replies.append({'content': 'Malformed prose followed by {"complete":true}'})


def terminal_receipt(harness, state):
    accepted_id = state['bindings']['search']['id']
    return next(r for r in harness.recovery_evidence()['receipts'] if r['id'] == accepted_id)


def test_actual_artifact_is_durable_and_available_to_semantic_validator(endpoint, tmp_path):
    url, requests, replies = endpoint
    observed = []
    def check(output, context):
        observed.append((output, deepcopy(context.terminal_completion)))
        assert context.terminal_completion['artifact'] == {'rows': [7], 'season': '2024/2025'}
        return []
    f = factory(url, validators={'verified': Validator('v1', check)})
    w = f.build(graph(validators=['verified'])); queue(replies)
    h = Harness(w, tmp_path / 'run')
    state = h.run({'season': '2024/2025'})
    assert state['status'] == 'completed' and len(requests) == 1 and len(replies) == 1
    receipt = terminal_receipt(h, state)
    evidence = receipt['result']['metadata']['terminalCompletion']
    assert evidence['artifact'] == {'rows': [7], 'season': '2024/2025'}
    assert evidence['invocationId'] == receipt['id'] and observed[0][0] == {'complete': True}
    fresh = Harness(f.build(graph(validators=['verified'])), tmp_path / 'run')
    assert fresh.status().state['bindings'] == state['bindings']
    assert terminal_receipt(fresh, state)['sha256'] == receipt['sha256'] and len(requests) == 1


@pytest.mark.parametrize('rejection', ['schema', 'semantic', 'missing_terminal'])
def test_rejected_terminal_artifact_never_replays_successful_tools(endpoint, tmp_path, rejection):
    url, requests, replies = endpoint
    seen = []
    def handler(a):
        seen.append(1)
        return TerminalCompletion({'complete': rejection != 'schema'}, artifact={'rows': [7]})
    validators = {'reject': Validator('v1', lambda output, context: ['not admitted'])} if rejection == 'semantic' else {}
    w = factory(url, handler=handler, validators=validators, max_attempts=3).build(graph(validators=validators))
    if rejection == 'missing_terminal': replies.append({'content': '{"complete":true}'})
    else: queue(replies)
    h = Harness(w, tmp_path / 'run'); state = h.run({})
    assert state['status'] == 'blocked' and state['outputs'] == {} and len(requests) == 1
    assert state['calls'] == 1 and state['pending'] is None
    assert len(h.recovery_evidence()['receipts']) == 1
    assert h.resume()['status'] == 'blocked' and len(requests) == 1
    assert seen == ([] if rejection == 'missing_terminal' else [1])


def test_restart_after_receipt_does_not_repeat_tools(endpoint, tmp_path, monkeypatch):
    url, requests, replies = endpoint
    queue(replies); f = factory(url); w = f.build(graph())
    h = Harness(w, tmp_path / 'run')
    monkeypatch.setattr(h, '_accept', lambda *a: (_ for _ in ()).throw(OSError('crash after receipt')))
    with pytest.raises(OSError): h.run({})
    before = h.recovery_evidence()['receipts'][0]
    fresh = Harness(f.build(graph()), tmp_path / 'run')
    state = fresh.resume()
    assert state['status'] == 'completed' and len(requests) == 1
    assert terminal_receipt(fresh, state)['sha256'] == before['sha256']
    assert state['invocations'][0]['token_usage'] == 7


def test_crash_before_receipt_is_uncertain_and_not_automatically_replayed(endpoint, tmp_path, monkeypatch):
    url, requests, replies = endpoint
    queue(replies); f = factory(url); h = Harness(f.build(graph()), tmp_path / 'run')
    original = h.store.save_receipt
    monkeypatch.setattr(h.store, 'save_receipt', lambda *a: (_ for _ in ()).throw(OSError('storage unavailable')))
    with pytest.raises(OSError): h.run({})
    monkeypatch.setattr(h.store, 'save_receipt', original)
    fresh = Harness(f.build(graph()), tmp_path / 'run'); state = fresh.resume()
    assert state['reason'] == 'interrupted_call' and len(requests) == 1
    assert fresh.recovery_evidence()['receipts'] == [] and state['outputs'] == {}


def test_terminal_validator_context_is_owned_per_callback(endpoint, tmp_path):
    url, requests, replies = endpoint
    def mutate(output, ctx):
        ctx.terminal_completion['artifact']['rows'].append(99)
        return []
    def verify(output, ctx):
        return [] if ctx.terminal_completion['artifact']['rows'] == [7] else ['mutated evidence']
    checks = {'mutate': Validator('v1', mutate), 'verify': Validator('v1', verify)}
    w = factory(url, validators=checks).build(graph(validators=checks)); queue(replies)
    h = Harness(w, tmp_path / 'run'); state = h.run({})
    assert state['status'] == 'completed'
    assert terminal_receipt(h, state)['result']['metadata']['terminalCompletion']['artifact']['rows'] == [7]


@pytest.mark.parametrize('field', ['artifact', 'outputSha256', 'invocationId', 'toolVersion'])
def test_conflicting_terminal_metadata_is_rejected_without_retry(endpoint, tmp_path, monkeypatch, field):
    url, requests, replies = endpoint
    queue(replies); f = factory(url); w = f.build(graph())
    runtime = ProsaicRuntime(w.config, custom_tools=w.custom_tools); original = runtime.run
    def tampered(*args, **kwargs):
        result = original(*args, **kwargs)
        result.metadata['terminalCompletion'][field] = {'rows': [99]} if field == 'artifact' else 'conflicting'
        return result
    monkeypatch.setattr(runtime, 'run', tampered)
    h = Harness(w, tmp_path / 'run', runtime=runtime); state = h.run({})
    assert state['status'] == 'blocked' and state['outputs'] == {} and len(requests) == 1
    assert h.status().state['status'] == 'blocked'


def test_terminal_artifact_limit_retains_counters_and_explicit_breadcrumb(endpoint, tmp_path):
    url, requests, replies = endpoint
    w = factory(url, handler=lambda a: TerminalCompletion({'complete': True}, artifact={'data': 'x' * 2000}),
        max_metadata_bytes=1400).build(graph()); queue(replies)
    h = Harness(w, tmp_path / 'run'); state = h.run({})
    assert state['reason'] == 'metadata_limit' and state['outputs'] == {} and len(requests) == 1
    result = h.recovery_evidence()['receipts'][0]['result']
    assert result['metadata']['invocation_budgets_v1']['provider_requests'] == 1
    assert result['metadata']['invocation_budgets_v1']['tool_calls'] == 1
    assert result['metadata']['terminalCompletion']['artifactIncluded'] is False
    assert 'artifact' not in result['metadata']['terminalCompletion'] and result['token_usage'] == 7


def test_terminal_grants_are_host_only_and_part_of_identity(endpoint):
    url, _, _ = endpoint
    enabled = factory(url)
    ordinary = factory(url, terminal=False)
    assert enabled.build(graph()).fingerprint != ordinary.build(graph()).fingerprint
    malicious = graph(); malicious['steps']['search']['allowed_terminal_tools'] = ['finish']
    with pytest.raises(WorkflowAdmissionError): enabled.build(malicious)
    assert 'allowed_terminal_tools' not in enabled.proposal_schema()['properties']['definition']['properties']['steps']['additionalProperties']


def test_explicit_effort_overrides_remain_bound_to_workflow_identity():
    from test_workflow_factory import factory as ordinary_factory, graph as ordinary_graph, config
    original = config()
    changed = replace(original, profiles={name: replace(endpoint, supported_efforts=('low',))
        for name, endpoint in original.profiles.items()})
    assert ordinary_factory(cfg=original).build(ordinary_graph()).fingerprint != ordinary_factory(
        cfg=changed).build(ordinary_graph()).fingerprint


def large_accounting():
    from prosaic_runtime.accounting import ExecutionContext, MemoryRecorder
    context = ExecutionContext(application_id='a' * 128, tenant_id='t' * 128,
        billing_account_id='b' * 128, actor_id='c' * 128, project_id='p' * 128,
        request_id='r' * 128, invocation_id='i' * 128)
    return context, MemoryRecorder(namespace='n' * 128, environment='e' * 128)


def test_terminal_limit_retains_full_accounting_lineage_when_receipt_has_room(endpoint, tmp_path):
    url, requests, replies = endpoint
    context, recorder = large_accounting()
    parameters = {'type': 'object', 'properties': {'page': {'type': 'integer'}},
        'required': ['page'], 'additionalProperties': False}
    handler = lambda a: TerminalCompletion({'complete': True}, artifact={'rows': [7]}) if a['page'] == 11 else {'page': a['page']}
    w = factory(url, handler=handler, parameters=parameters, limits=RunLimits(max_tool_rounds=16),
        max_metadata_bytes=2000).build(graph())
    for i in range(12):
        replies.append({'content': '', 'tool_calls': [{'id': f'call-{i}', 'type': 'function',
            'function': {'name': 'finish', 'arguments': json.dumps({'page': i})}}]})
    h = Harness(w, tmp_path / 'run', context=context, accounting=recorder); state = h.run({})
    assert state['reason'] == 'metadata_limit' and len(requests) == 12
    result = h.recovery_evidence()['receipts'][0]['result']
    lineage = result['metadata']['accounting_v1']
    assert lineage['namespace'] == recorder.namespace and lineage['environment'] == recorder.environment
    assert set(lineage['provider_call_ids']) == set(recorder.intents) and len(lineage['provider_call_ids']) == 12
    assert lineage['context']['invocation_id'] == state['invocations'][0]['id']
    assert result['metadata']['invocation_budgets_v1']['provider_requests'] == 12


def test_terminal_admission_reserves_accounting_failure_headroom(endpoint, tmp_path):
    url, requests, replies = endpoint
    context, recorder = large_accounting(); seen = []
    w = factory(url, handler=lambda a: seen.append(1) or TerminalCompletion({}, artifact={}),
        max_receipt_bytes=5000).build(graph()); queue(replies)
    h = Harness(w, tmp_path / 'run', context=context, accounting=recorder); state = h.run({})
    assert state['reason'] == 'receipt_limit' and state['calls'] == 0
    assert requests == [] and seen == [] and recorder.intents == {}
