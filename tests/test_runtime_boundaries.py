"""Native Runtime controls retain historical disabled identity and durable bounds."""
import json
from dataclasses import replace

import pytest
from prosaic_harness import (Harness, WorkflowBindings, WorkflowBundle, WorkflowCatalog,
                             WorkflowFactory, WorkflowPolicy, WorkflowAdmissionError)
from prosaic_runtime import CustomTool, ProsaicRuntime, Result
from test_workflow_factory import factory, graph, tools, config, agent
from test_native_execution import bound
from test_transport import endpoint


HISTORIC_FINGERPRINT = 'ac9913171a763a653b8de7e23403aa8e68314db7e07bad6a9e0d5578bd54e624'
HISTORIC_DESCRIPTOR = '{"lookup_entity": {"authorization_required": false, "description": "Lookup a synthetic entity", "max_argument_bytes": 16384, "max_result_bytes": 65536, "name": "lookup_entity", "parameters": {"additionalProperties": false, "properties": {"query": {"type": "string"}}, "required": ["query"], "type": "object"}, "version": "v1"}}'


def test_disabled_controls_keep_exact_released_identity():
    for caps in ({}, {'max_provider_requests_per_invocation': None,
                     'max_tool_calls_per_invocation': None}):
        w = factory(**caps).build(graph())
        assert w.fingerprint == HISTORIC_FINGERPRINT
        assert json.dumps(w.tool_descriptors, sort_keys=True) == HISTORIC_DESCRIPTOR
        assert WorkflowBundle('historic-v1', factory(**caps)).identity == '289d2c28dad4966d331f4fe1f08c24d2c3a79d5303eeb1b48cf55da7db8c6182'
        assert 'maxProviderRequestsPerInvocation' not in factory(**caps).describe()['limits']
    bindings = WorkflowBindings(config=config(), custom_tools=tools(),
                                operation_namespace=None, tool_journal=None)
    assert bindings._operation_namespace is None


@pytest.mark.parametrize('field', ['max_provider_requests_per_invocation', 'max_tool_calls_per_invocation'])
@pytest.mark.parametrize('value', [True, -1, 1.5, '1'])
def test_caps_are_exact_nonnegative_integers(field, value):
    with pytest.raises(WorkflowAdmissionError):
        WorkflowPolicy(**{field: value})


@pytest.mark.parametrize('field', ['max_provider_requests_per_invocation', 'max_tool_calls_per_invocation'])
@pytest.mark.parametrize('value', [0, 2])
def test_enabled_host_caps_change_identity_and_discovery(field, value):
    f = factory(**{field: value})
    assert f.build(graph()).fingerprint != HISTORIC_FINGERPRINT
    name = 'maxProviderRequestsPerInvocation' if field.startswith('max_provider') else 'maxToolCallsPerInvocation'
    assert f.describe()['limits'][name] == value
    assert f.describe()['limitUnits'][name] == 'perInvocation'
    assert field not in f.proposal_schema()['properties']['definition']['properties']['limits']['properties']


def test_native_dispatch_receives_remaining_units_and_separate_scope(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch, max_tokens=20,
                     max_provider_requests_per_invocation=2, max_tool_calls_per_invocation=1)
    h.run({})
    options = calls[0][1]
    assert options['policy'].max_reported_tokens == 20
    assert options['policy'].max_provider_requests == 2
    assert options['policy'].max_tool_calls == 1
    scope = options['operation_context']
    assert scope.invocation_id == h.status().state['invocations'][0]['id']
    assert scope.run_id == h.status().state['run_id'] and scope.step_id == 'find'
    assert 'context' not in options and 'accounting' not in options


class Journal:
    identity = 'owned-ledger-v1'
    contract_version = 'tool-journal-v1'

    def claim(self, *args):
        raise AssertionError('pure admission called journal claim')

    def commit(self, *args):
        raise AssertionError('pure admission called journal commit')


def journal_factory(journal=None, namespace='owned-domain-v1', *, contextual=True, journaled=True,
                    cfg=None, handler=None, **caps):
    original = tools()['lookup_entity']
    tool = CustomTool(original.name, original.description, original.parameters,
                      handler or (lambda value, context: {'found': True}), 'v1', with_context=contextual,
                      operation_key=(lambda value, context: 'business-key') if journaled else None)
    return WorkflowFactory(catalog=WorkflowCatalog(agents={'finder': agent()},
        schemas={'result': {'type': 'object', 'properties': {'found': {'type': 'boolean'}},
                           'required': ['found'], 'additionalProperties': False}}),
        bindings=WorkflowBindings(config=cfg or config(), custom_tools={'lookup_entity': tool},
                                  operation_namespace=namespace, tool_journal=journal),
        policy=WorkflowPolicy(allowed_agents={'finder'}, allowed_schemas={'result'},
                              allowed_tools={'lookup_entity'}, allowed_model_tiers={'fast'}, **caps))


def test_journal_binding_is_pure_frozen_and_reconstructable():
    journal = Journal()
    f = journal_factory(journal)
    bundle = WorkflowBundle('effects-v1', f)
    prepared = bundle.prepare_json(json.dumps({'definition': graph()}))
    assert prepared.workflow._admission.tool_journal is journal
    assert prepared.workflow.tool_descriptors['lookup_entity']['journaled'] is True
    fresh = WorkflowBundle('effects-v1', journal_factory(Journal()))
    assert fresh.identity == bundle.identity
    assert fresh.reconstruct(prepared.proposal_json, prepared.reference).fingerprint == prepared.workflow.fingerprint
    for changed in (journal_factory(Journal(), 'other-domain'),):
        with pytest.raises(WorkflowAdmissionError):
            WorkflowBundle('effects-v1', changed).reconstruct(prepared.proposal_json, prepared.reference)


def test_dynamic_journal_metadata_rejected_without_evaluation():
    class Dynamic(Journal):
        @property
        def identity(self):
            raise AssertionError('journal property evaluated')
    with pytest.raises(WorkflowAdmissionError):
        journal_factory(Dynamic())


@pytest.mark.parametrize('journal,namespace', [(None, 'owned-domain'), (Journal(), None)])
def test_journaled_tools_require_owned_journal_and_namespace(journal, namespace):
    with pytest.raises(WorkflowAdmissionError):
        journal_factory(journal, namespace).build(graph())


@pytest.mark.parametrize('boundary', ['run', 'status', 'resume'])
def test_live_journal_domain_changes_rejected_before_store_or_dispatch(tmp_path, boundary):
    journal = Journal()
    h = Harness(journal_factory(journal).build(graph()), tmp_path / 'run')
    journal.identity = 'swapped-domain'
    with pytest.raises(WorkflowAdmissionError):
        h.run({}) if boundary == 'run' else getattr(h, boundary)()
    assert not (tmp_path / 'run').exists()


@pytest.mark.parametrize('capability', ['invocation_budgets_v1', 'tool_context_v1', 'tool_journal_v1'])
def test_capability_failure_precedes_storage(tmp_path, capability):
    workflow = journal_factory(Journal()).build(graph())
    runtime = ProsaicRuntime(workflow.config, custom_tools=workflow._admission.tools)
    runtime.capabilities = runtime.capabilities - {capability}
    with pytest.raises(WorkflowAdmissionError):
        Harness(workflow, tmp_path / 'run', runtime=runtime)
    assert not (tmp_path / 'run').exists()


def test_plain_native_scope_also_requires_context_capability(tmp_path):
    workflow = factory().build(graph())
    runtime = ProsaicRuntime(workflow.config, custom_tools=tools())
    runtime.capabilities = runtime.capabilities - {'tool_context_v1'}
    with pytest.raises(WorkflowAdmissionError):
        Harness(workflow, tmp_path / 'run', runtime=runtime)
    assert not (tmp_path / 'run').exists()


def local_config(url):
    cfg = config()
    return replace(cfg, profiles={'local': replace(cfg.profiles['local'], base_url=url)})


def tool_turn(*, usage=3):
    return {'content': '', '_usage': {'total_tokens': usage},
            'tool_calls': [{'id': 'provider-correlation-only', 'type': 'function', 'function': {
                'name': 'lookup_entity', 'arguments': '{"query":"synthetic"}'}}]}


@pytest.mark.parametrize('caps,reason,provider_count,tool_count', [
    ({'max_provider_requests_per_invocation': 0}, 'provider_request_limit', 0, 0),
    ({'max_provider_requests_per_invocation': 1}, 'provider_request_limit', 1, 1),
    ({'max_tool_calls_per_invocation': 0}, 'tool_call_limit', 1, 0),
])
def test_real_runtime_counts_provider_and_tool_units(endpoint, tmp_path, caps, reason, provider_count, tool_count):
    url, requests, replies = endpoint
    applied = []
    original = tools()['lookup_entity']
    tool = CustomTool(original.name, original.description, original.parameters,
                      lambda value: applied.append(value) or {'found': True}, 'v1')
    h = Harness(factory(cfg=local_config(url), registry={tool.name: tool}, **caps).build(graph()), tmp_path / 'run')
    replies.extend([tool_turn(), {'content': '{"found":true}', '_usage': {'total_tokens': 4}}])
    state = h.run({})
    assert state['status'] == 'blocked' and state['pending'] is None and state['calls'] == 1
    assert state['invocations'][0]['status'] == 'complete'
    receipt = h.store.load_receipt('legacy', state['invocations'][0]['id'])
    assert receipt['result']['metadata']['failure_reason'] == reason
    budget = receipt['result']['metadata']['invocation_budgets_v1']
    assert budget['provider_requests'] == provider_count and budget['tool_calls'] == tool_count
    assert len(requests) == provider_count and len(applied) == tool_count
    assert h.resume(retry_interrupted=True)['status'] == 'blocked'
    assert len(requests) == provider_count and len(applied) == tool_count


def composition_graph():
    proposal = graph()
    proposal['steps']['find']['next'] = 'second'
    proposal['steps']['second'] = {**proposal['steps']['find'], 'next': 'review', 'inputs': ['find']}
    return proposal


def test_second_native_invocation_receives_remaining_tokens(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch, proposal=composition_graph(),
                     allow_agent_composition=True, max_tokens=20)
    state = h.run({})
    assert state['status'] == 'waiting' and state['calls'] == 2
    assert [call[1]['policy'].max_reported_tokens for call in calls] == [20, 17]
    assert calls[0][1]['operation_context'].invocation_id != calls[1][1]['operation_context'].invocation_id


@pytest.mark.parametrize('usage,reason', [(None, 'usage_unknown'), (21, 'token_limit'), (20, None)])
def test_terminal_usage_retains_complete_ledger_and_exact_cap_success(endpoint, tmp_path, usage, reason):
    url, requests, replies = endpoint
    proposal = graph()
    proposal['steps']['find'].pop('require_tools')
    h = Harness(factory(cfg=local_config(url), max_tokens=20).build(proposal), tmp_path / 'run')
    replies.append({'content': '{"found":true}', '_usage': {} if usage is None else {'total_tokens': usage}})
    state = h.run({})
    assert state['pending'] is None and state['invocations'][0]['status'] == 'complete'
    assert state['invocations'][0]['token_usage'] == usage
    assert state['reason'] == reason and state['status'] == ('blocked' if reason else 'waiting')
    receipt = h.store.load_receipt('legacy', state['invocations'][0]['id'])
    assert receipt['result']['token_usage'] == usage
    assert receipt['result']['metadata']['invocation_budgets_v1']['usage_complete'] == (usage is not None)
    assert len(requests) == 1
    if reason:
        assert h.resume(retry_interrupted=True)['reason'] == reason and len(requests) == 1


def test_resume_keeps_original_deadline_and_passes_remaining_time(tmp_path, monkeypatch):
    now = [100.0]
    proposal = graph()
    proposal['steps']['review']['choices']['accept'] = 'second'
    proposal['steps']['second'] = {**proposal['steps']['find'], 'next': 'done'}
    h, calls = bound(tmp_path, monkeypatch, proposal=proposal, allow_agent_composition=True,
                     max_run_s=60, timeout_s=50, harness_options={'clock': lambda: now[0]})
    state = h.run({})
    assert state['deadline'] == 160
    now[0] = 140
    final = h.resume(choice='accept')
    assert final['status'] == 'completed' and final['deadline'] == 160
    assert [call[1]['policy'].timeout_s for call in calls] == [50, 20]


class MemoryJournal(Journal):
    """Test-only public protocol fixture; RunStore never contains effect records."""
    def __init__(self):
        self.records = {}
        self.claims = []

    def claim(self, namespace, key, signature):
        from prosaic_runtime import ToolClaim
        self.claims.append((namespace, key))
        record = self.records.get((namespace, key))
        if record is None:
            self.records[(namespace, key)] = (signature, None)
            return ToolClaim('new', signature, claim_token='fence-v1')
        signature, outcome = record
        return ToolClaim('uncertain', signature) if outcome is None else ToolClaim('replay', signature, outcome=outcome)

    def commit(self, namespace, key, token, outcome):
        assert token == 'fence-v1'
        signature, _ = self.records[(namespace, key)]
        self.records[(namespace, key)] = (signature, outcome)


@pytest.mark.parametrize('phase', ['before', 'after_effect', 'after_commit'])
def test_cancellation_and_uncertain_effect_are_terminal_without_model_retry(endpoint, tmp_path, phase):
    url, requests, replies = endpoint
    journal, applied, scopes, stopped = MemoryJournal(), [], [], [phase == 'before']
    def handler(value, context):
        applied.append(value)
        scopes.append(context.scope)
        stopped[0] = True
        if phase == 'after_effect':
            raise RuntimeError('applied but outcome unavailable')
        return {'found': True}
    f = journal_factory(journal, cfg=local_config(url), handler=handler)
    h = Harness(f.build(graph()), tmp_path / 'run', cancelled=lambda: stopped[0])
    replies.append(tool_turn())
    state = h.run({})
    assert state['status'] == 'blocked' and state['pending'] is None
    assert len(requests) == (0 if phase == 'before' else 1)
    assert len(applied) == (0 if phase == 'before' else 1)
    if phase != 'before':
        invocation = state['invocations'][0]
        assert invocation['status'] == 'complete'
        assert scopes[0].invocation_id == invocation['id'] and scopes[0].operation_namespace == 'owned-domain-v1'
        receipt = h.store.load_receipt('legacy', invocation['id'])
        assert receipt['result']['metadata']['failure_reason'] == ('tool_effect_uncertain' if phase == 'after_effect' else 'cancelled')
        outcome = journal.records[('owned-domain-v1', 'business-key')][1]
        assert outcome is None if phase == 'after_effect' else outcome == {'status': 'ok', 'result': {'found': True}}
        assert 'business-key' not in json.dumps([state, receipt])
    stopped[0] = False
    assert h.resume(retry_interrupted=True)['status'] == 'blocked'
    assert len(applied) == (0 if phase == 'before' else 1)


def test_existing_uncertain_claim_does_not_execute_handler(endpoint, tmp_path):
    url, requests, replies = endpoint
    from prosaic_runtime import ToolClaim
    class Uncertain(Journal):
        def claim(self, namespace, key, signature):
            return ToolClaim('uncertain', signature)
    applied = []
    h = Harness(journal_factory(Uncertain(), cfg=local_config(url),
        handler=lambda value, context: applied.append(value) or {'found': True}).build(graph()), tmp_path / 'run')
    replies.append(tool_turn())
    state = h.run({})
    assert state['status'] == 'blocked' and state['invocations'][0]['status'] == 'complete'
    assert state['pending'] is None and state['calls'] == 1 and applied == [] and len(requests) == 1
    receipt = h.store.load_receipt('legacy', state['invocations'][0]['id'])
    assert receipt['result']['metadata']['failure_reason'] == 'tool_effect_uncertain'
    assert h.resume(retry_interrupted=True)['status'] == 'blocked'
    assert applied == [] and len(requests) == 1


def test_ordinary_fake_adapter_keeps_released_keywords_with_controls_disabled(tmp_path, monkeypatch):
    from test_harness import setup
    workflow = setup(tmp_path, monkeypatch)
    calls = []
    class StrictAdapter:
        def run(self, artifact, arguments, *, cwd, policy, on_event, cancelled):
            calls.append(policy)
            assert policy.max_provider_requests is None and policy.max_tool_calls is None
            assert policy.max_reported_tokens is None
            return Result(0, '{"approved":true}', '', token_usage=5)
    h = Harness(workflow, tmp_path / 'run', runtime=StrictAdapter())
    assert h.run({})['status'] == 'completed' and len(calls) == 1


def test_interrupted_retry_consent_cannot_dispatch_an_uncertain_effect(endpoint, tmp_path):
    url, requests, replies = endpoint
    journal, applied = MemoryJournal(), []
    def interrupted(value, context):
        applied.append(value)
        raise KeyboardInterrupt()
    h = Harness(journal_factory(journal, cfg=local_config(url), handler=interrupted).build(graph()), tmp_path / 'run')
    replies.append(tool_turn())
    with pytest.raises(KeyboardInterrupt):
        h.run({})
    assert h.status().state['pending'] is not None
    state = h.resume(retry_interrupted=True)
    assert state['status'] == 'blocked' and state['reason'] == 'usage_unknown'
    assert state['pending'] is None and state['invocations'][0]['status'] == 'abandoned'
    assert journal.records[('owned-domain-v1', 'business-key')][1] is None
    assert len(applied) == 1 and len(requests) == 1
