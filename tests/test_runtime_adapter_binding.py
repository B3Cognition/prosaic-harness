"""Native adapter declarations remain sealed and cannot replace Runtime authority."""
from dataclasses import replace
import pytest
from prosaic_runtime import ProsaicRuntime, RuntimeAdapter, Result
from prosaic_harness import WorkflowBindings, WorkflowCatalog, WorkflowFactory, WorkflowPolicy, Harness, WorkflowAdmissionError
from test_workflow_factory import config, agent


def build(adapter):
    return WorkflowFactory(catalog=WorkflowCatalog(agents={'agent': agent(tools=())}, schemas={'result': {'type':'object'}}),
        bindings=WorkflowBindings(config=adapter.config, runtime_adapter=adapter),
        policy=WorkflowPolicy(allowed_agents=frozenset({'agent'}), allowed_schemas=frozenset({'result'}), allowed_model_tiers=frozenset({'fast'}))).build(
            {'version':1,'start':'answer','steps':{'answer':{'kind':'agent','agent':'agent','schema':'result','next':'done'},'done':{'kind':'finish'}}})


def test_native_adapter_is_admitted_and_its_version_is_sealed(tmp_path, monkeypatch):
    calls=[]
    def run(self, agent, arguments, **kwargs):
        calls.append(arguments)
        return Result(0,'{}','',token_usage=2)
    monkeypatch.setattr(ProsaicRuntime,'run',run)
    def invoke(agent, arguments, *, execute, **options):
        return execute('projected',allowed_tools=frozenset())
    adapter=RuntimeAdapter(ProsaicRuntime(config()),version='host-v1',invoke=invoke)
    workflow=build(adapter)
    state=Harness(workflow,tmp_path/'run').run({})
    assert state['status']=='completed' and calls==['projected']
    assert build(replace(adapter,version='host-v2')).fingerprint != workflow.fingerprint
    with pytest.raises(WorkflowAdmissionError,match='binding_mismatch'):
        Harness(workflow,tmp_path/'changed',runtime=replace(adapter,version='host-v2'))
    assert calls==['projected']


def test_native_adapter_cannot_replace_an_undeclared_runtime(tmp_path):
    adapter=RuntimeAdapter(ProsaicRuntime(config()),version='host-v1',invoke=lambda *a,**k: None)
    workflow=WorkflowFactory(catalog=WorkflowCatalog(), bindings=WorkflowBindings(config=config()),policy=WorkflowPolicy()).build(
        {'version':1,'start':'done','steps':{'done':{'kind':'finish'}}})
    with pytest.raises(WorkflowAdmissionError,match='binding_mismatch'):
        Harness(workflow,tmp_path/'run',runtime=adapter)
