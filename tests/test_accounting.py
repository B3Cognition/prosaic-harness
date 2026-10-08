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
