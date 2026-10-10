import json

import pytest
from prosaic_runtime.accounting import ExecutionContext, MemoryRecorder
from prosaic_runtime import Result, ProsaicRuntime
from prosaic_harness import Harness
from prosaic_harness.contracts import seal, validate_state, validate_receipt
from test_harness import setup, FakeRuntime


class AccountingRuntime(FakeRuntime):
    capabilities = {'accounting_v1'}

    def __init__(self, replies, *, accounting=None):
        super().__init__(replies)
        self.accounting = accounting
        self.contexts = []

    def run(self, artifact, arguments, **kwargs):
        self.contexts.append(kwargs['context'])
        return super().run(artifact, arguments, **kwargs)


def test_context_frozen_defaults_and_separate_from_prompt(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch, pause=True)
    recorder = MemoryRecorder(defaults=ExecutionContext(tenant_id='original'))
    runtime = AccountingRuntime(['{"approved":true}'])
    state = Harness(flow, tmp_path / 'run', runtime=runtime, accounting=recorder).run({'task': 'draft'})
    context = state['accounting_context']
    assert context['tenant_id'] == 'original'
    assert runtime.contexts[0].run_id == state['run_id']
    assert runtime.contexts[0].invocation_id == state['invocations'][0]['id']
    assert runtime.contexts[0].step_id == 'author'
    assert 'original' not in json.dumps(runtime.calls[0][1])
    recorder.defaults = ExecutionContext(tenant_id='changed')
    resumed = Harness(flow, tmp_path / 'run', runtime=runtime, accounting=recorder).resume(choice='approve')
    assert resumed['accounting_context'] == context
    assert len(runtime.calls) == 1


@pytest.mark.parametrize('field', ['application_id', 'tenant_id', 'billing_account_id', 'actor_id', 'project_id'])
def test_resume_cannot_rebind_explicit_context(tmp_path, monkeypatch, field):
    flow = setup(tmp_path, monkeypatch, pause=True)
    context = ExecutionContext(**{field: 'original'})
    runtime = AccountingRuntime(['{"approved":true}'])
    Harness(flow, tmp_path / 'run', runtime=runtime, context=context).run({})
    with pytest.raises(ValueError, match='context'):
        Harness(flow, tmp_path / 'run', runtime=runtime, context=ExecutionContext(**{field: 'other'})).resume()
    assert len(runtime.calls) == 1


@pytest.mark.parametrize('interrupted', [False, True])
def test_upgrade_legacy_checkpoint_durable_without_dispatch(tmp_path, monkeypatch, interrupted):
    flow = setup(tmp_path, monkeypatch)
    old = Harness(flow, tmp_path / 'run', runtime=FakeRuntime([KeyboardInterrupt() if interrupted else '{"approved":true}']))
    if interrupted:
        with pytest.raises(KeyboardInterrupt):
            old.run({})
    else:
        assert old.run({})['status'] == 'completed'
    runtime = AccountingRuntime([])
    recorder = MemoryRecorder(defaults=ExecutionContext(tenant_id='first'))
    new = Harness(flow, tmp_path / 'run', runtime=runtime, accounting=recorder)
    state = new.resume()
    assert state['accounting_context']['tenant_id'] == 'first'
    assert state['accounting_migration']['source'] == 'legacy_checkpoint'
    assert not runtime.calls
    recorder.defaults = ExecutionContext(tenant_id='later')
    assert new.resume()['accounting_context'] == state['accounting_context']
    assert json.loads((tmp_path / 'run/run.json').read_text())['accounting_context'] == state['accounting_context']


def test_legacy_runtime_receives_no_new_keywords(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    class StrictRuntime:
        def run(self, artifact, arguments, *, cwd, policy, on_event, cancelled):
            return Result(0, '{"approved":true}', '', token_usage=5)
    state = Harness(flow, tmp_path / 'run', runtime=StrictRuntime()).run({})
    assert 'accounting_context' not in state
    assert 'accounting_migration' not in state


def test_opt_in_requires_capability(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='accounting_v1'):
        Harness(flow, tmp_path / 'run', runtime=FakeRuntime([]), context=ExecutionContext())
    assert 'accounting_v1' in ProsaicRuntime(flow.config).capabilities


def test_malformed_checkpoint_context_rejected(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    state = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}'])).run({})
    with pytest.raises(ValueError):
        validate_state(seal(state | {'accounting_context': {'tenant_id': 'x'}}), flow)


def test_receipt_context_mismatch_rejected(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    runtime = AccountingRuntime(['{"approved":true}'])
    state = Harness(flow, tmp_path / 'run', runtime=runtime, context=ExecutionContext(tenant_id='tenant')).run({})
    receipt = json.loads(next((tmp_path / 'run/attempts').glob('*.json')).read_text())
    expected = runtime.contexts[0].to_dict()
    receipt['result']['metadata']['accounting_v1'] = {'context': expected}
    validate_receipt(seal(receipt), state, state['invocations'][0])
    expected['tenant_id'] = 'other'
    with pytest.raises(ValueError, match='accounting context mismatch'):
        validate_receipt(seal(receipt), state, state['invocations'][0])


def test_runtime_configured_defaults_also_persist(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    runtime = AccountingRuntime(['{"approved":true}'])
    runtime.context_defaults = ExecutionContext(tenant_id='configured')
    state = Harness(flow, tmp_path / 'run', runtime=runtime).run({})
    assert state['accounting_context']['tenant_id'] == 'configured'


@pytest.mark.parametrize('field', ['namespace', 'environment'])
def test_resume_rejects_changed_recorder_scope(tmp_path, monkeypatch, field):
    flow = setup(tmp_path, monkeypatch, pause=True)
    runtime = AccountingRuntime(['{"approved":true}'])
    original = MemoryRecorder(namespace='deployment', environment='test')
    state = Harness(flow, tmp_path / 'run', runtime=runtime, accounting=original).run({})
    changed = MemoryRecorder(**(state['accounting_scope'] | {field: 'other'}))
    with pytest.raises(ValueError, match='scope'):
        Harness(flow, tmp_path / 'run', runtime=runtime, accounting=changed).resume()
    assert len(runtime.calls) == 1


def test_missing_recorder_cannot_silently_dispatch_unmeasured(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    runtime = AccountingRuntime(['not json', KeyboardInterrupt()])
    h = Harness(flow, tmp_path / 'run', runtime=runtime, accounting=MemoryRecorder())
    with pytest.raises(KeyboardInterrupt):
        h.run({})
    # Explicit retry with lost recorder must stop before a replacement pending call is created.
    resumed = Harness(flow, tmp_path / 'run', runtime=AccountingRuntime([]))
    assert resumed.resume()['reason'] == 'interrupted_call'
    with pytest.raises(ValueError, match='configured recorder'):
        resumed.resume(retry_interrupted=True)
    state = json.loads((tmp_path / 'run/run.json').read_text())
    assert state['pending'] is None
    assert len(state['invocations']) == 2


def test_upgrade_legacy_saved_receipt_does_not_dispatch(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    old = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']))
    monkeypatch.setattr(old, '_accept', lambda *args: (_ for _ in ()).throw(OSError('receipt saved before crash')))
    with pytest.raises(OSError):
        old.run({})
    runtime = AccountingRuntime([])
    upgraded = Harness(flow, tmp_path / 'run', runtime=runtime, accounting=MemoryRecorder())
    state = upgraded.resume()
    assert state['status'] == 'completed'
    assert not runtime.calls
    assert state['accounting_migration']['source'] == 'legacy_checkpoint'
    assert len(state['invocations']) == 1


@pytest.mark.parametrize('context_exists', [False, True])
@pytest.mark.parametrize('action,code,checked', [
    ({'choice': 'private'}, 'invalid_choice', []),
    ({'choice': 'accept', 'response': {'found': 'private'}}, 'response_schema_invalid', []),
    ({'choice': 'accept', 'response': {'found': False}}, 'response_validation_failed', [False]),
    ({'response': {'found': True}}, 'response_requires_choice', []),
    ({'choice': 'accept', 'response': {'found': 'x' * 100}}, 'response_limit', []),
])
def test_accounting_upgrade_does_not_commit_rejected_human_response(
        tmp_path, monkeypatch, context_exists, action, code, checked):
    from prosaic_harness import (WorkflowCatalog, WorkflowBindings, WorkflowPolicy,
                                 WorkflowFactory, HumanResponseError, Validator)
    from test_native_execution import bound
    from test_workflow_factory import agent, config, graph, tools
    proposal = graph()
    proposal['steps']['review'].update(response_schema='result', validators=['guard'])
    responses = []
    def check(value, context):
        responses.append(value['response']['found'])
        return [] if value['response']['found'] else ['private product validation detail']
    workflow = WorkflowFactory(
        catalog=WorkflowCatalog(agents={'finder': agent()}, schemas={'result': {
            'type': 'object', 'properties': {'found': {'type': 'boolean'}},
            'required': ['found'], 'additionalProperties': False}}),
        bindings=WorkflowBindings(config=config(), custom_tools=tools(),
                                 validators={'guard': Validator('v1', check)}),
        policy=WorkflowPolicy(allowed_agents=frozenset({'finder'}),
            allowed_schemas=frozenset({'result'}), allowed_tools=frozenset({'lookup_entity'}),
            allowed_validators=frozenset({'guard'}), allowed_model_tiers=frozenset({'fast'}),
            max_human_response_bytes=50)).build(proposal)
    template, calls = bound(tmp_path, monkeypatch)
    old = Harness(workflow, tmp_path / 'run', runtime=template.runtime,
                  context=ExecutionContext(tenant_id='original') if context_exists else None)
    old.run({})
    recorder = MemoryRecorder(defaults=ExecutionContext(tenant_id='upgraded'))
    upgraded = Harness(workflow, tmp_path / 'run', runtime=template.runtime, accounting=recorder)
    before = upgraded.status()
    content = upgraded.file.read_bytes()
    receipt = next((tmp_path / 'run/attempts').glob('*.json'))
    receipt_content = receipt.read_bytes()
    from prosaic_harness import RevisionConflict
    with pytest.raises(RevisionConflict):
        upgraded.resume(choice='accept', response={'found': True}, expected_revision='stale')
    assert upgraded.status() == before and responses == []
    with pytest.raises(HumanResponseError) as caught:
        upgraded.resume(**action, expected_revision=before.revision)
    assert caught.value.code == code
    assert upgraded.status() == before and upgraded.file.read_bytes() == content
    assert responses == checked and len(calls) == 1
    # The same interaction revision still authorizes a corrected actual response.
    state = upgraded.resume(choice='accept', response={'found': True},
                            expected_revision=before.revision)
    assert state['status'] == 'completed' and len(calls) == 1
    assert responses == checked + [True]
    assert state['accounting_scope'] == {'namespace': recorder.namespace, 'environment': recorder.environment}
    assert state['accounting_context']['tenant_id'] == ('original' if context_exists else 'upgraded')
    assert ('accounting_migration' in state) is (not context_exists)
    assert upgraded.status().state == state
    assert receipt.read_bytes() == receipt_content


def test_accepted_response_cannot_advance_after_accounting_migration_hits_state_limit(tmp_path, monkeypatch):
    from test_native_execution import bound
    old, calls = bound(tmp_path, monkeypatch, max_state_bytes=7000)
    assert old.run({})['status'] == 'waiting'
    events = []
    upgraded = Harness(old.workflow, tmp_path / 'run', runtime=old.runtime,
                       accounting=MemoryRecorder(), on_event=events.append)
    state = upgraded.resume(choice='accept', expected_revision=upgraded.status().revision)
    assert state['status'] == 'blocked' and state['reason'] == 'state_limit'
    assert not any(event['event'] == 'human_decision' for event in state['history'])
    assert not any(event['event'] == 'human_decision' for event in events)
    assert upgraded.status().state == state and len(calls) == 1


@pytest.mark.parametrize('expires,reason', [(False, 'schema_error'), (True, 'run_deadline')])
def test_accounting_upgrade_preserves_human_schema_error_and_deadline_precedence(
        tmp_path, monkeypatch, expires, reason):
    from test_native_execution import bound
    from test_workflow_factory import graph
    from prosaic_harness.schema_validation import evaluate_schema, SchemaEvaluationError
    proposal = graph()
    proposal['steps']['review']['response_schema'] = 'result'
    old, calls = bound(tmp_path, monkeypatch, proposal=proposal, max_human_response_bytes=50)
    old.run({})
    upgraded = Harness(old.workflow, tmp_path / 'run', runtime=old.runtime,
                       accounting=MemoryRecorder())
    def fail_response(schema, value, **kwargs):
        if kwargs['profile']['maximum_instance_bytes'] == 50:
            if expires:
                upgraded.clock = lambda: 10**15
            raise SchemaEvaluationError()
        return evaluate_schema(schema, value, **kwargs)
    monkeypatch.setattr('prosaic_harness.engine.evaluate_schema', fail_response)
    state = upgraded.resume(choice='accept', response={'found': True},
                            expected_revision=upgraded.status().revision)
    assert state['status'] == 'blocked' and state['reason'] == reason
    assert 'accounting_migration' in state
    assert not any(event['event'] == 'human_decision' for event in state['history'])
    assert upgraded.status().state == state and len(calls) == 1
