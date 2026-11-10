from dataclasses import replace
import pytest
import prosaic_harness as api
import prosaic_runtime as runtime_api
from support.conversations import binding_factory
from test_workflow_factory import agent, config, tools, graph


def contract(**changes):
    return api.ToolContracts('host', changes.pop('version', '1'), **(dict(display_authorizer=runtime_api.ToolDisplayAuthorizerV1(
        'viewer', '1', lambda use: pytest.fail('admission called display authorizer'))) | changes))


def factory(contracts=None):
    return api.WorkflowFactory(catalog=api.WorkflowCatalog(agents={'finder': agent()}, schemas={'result': {
        'type': 'object', 'properties': {'found': {'type': 'boolean'}}, 'required': ['found'], 'additionalProperties': False}}),
        bindings=api.WorkflowBindings(config=config(), custom_tools=tools(), tool_contracts=contracts),
        policy=api.WorkflowPolicy(allowed_agents=frozenset({'finder'}), allowed_schemas=frozenset({'result'}),
            allowed_tools=frozenset({'lookup_entity'}), allowed_model_tiers=frozenset({'fast'}),
            max_provider_requests_per_invocation=2, max_tool_calls_per_invocation=2))


def test_absent_contract_preserves_workflow_and_session_identity(binding_factory):
    first = binding_factory()
    assert first.identity == binding_factory(tool_contracts=None).identity
    assert 'toolContractV1' not in first.readmit()
    workflow = factory().build(graph())
    assert 'toolContractV1' not in workflow.definition
    assert workflow.current_fingerprint() == workflow.fingerprint


def test_events_only_admits_legacy_tools(binding_factory):
    registered = contract()
    binding = binding_factory(tool_contracts=registered)
    assert binding.readmit()['toolContractV1']['bindings'] == registered.descriptor()
    workflow = factory(registered).build(graph())
    assert workflow.current_fingerprint() == workflow.fingerprint
    assert workflow.fingerprint != factory().build(graph()).fingerprint


def test_unknown_capability_refuses_before_spend(binding_factory, monkeypatch):
    registered = contract()
    monkeypatch.setattr(runtime_api.ProsaicRuntime, 'capabilities', runtime_api.ProsaicRuntime.capabilities - {'tool_events_v1'})
    with pytest.raises((api.ConversationError, ValueError)): binding_factory(tool_contracts=registered)
    with pytest.raises((api.WorkflowAdmissionError, ValueError)): factory(registered).build(graph())


def test_contract_binding_change_requires_readmission(binding_factory):
    registered = contract()
    original = binding_factory(tool_contracts=registered)
    assert original.identity != binding_factory(tool_contracts=contract(version='2')).identity
    object.__setattr__(registered.display_authorizer, 'version', 'changed')
    with pytest.raises((api.ConversationError, ValueError)): original.readmit()


def test_default_capacity_and_narrower_limits():
    from prosaic_harness.tool_contracts import admit_tool_contracts
    runtime = runtime_api.ProsaicRuntime(config(), custom_tools=tools())
    descriptors = runtime.tool_descriptors
    limits = dict(max_provider_requests=2, max_tool_calls=2, max_receipt_bytes=8_388_608,
        max_state_bytes=8_388_608, max_event_bytes=65536, max_evidence_bytes=4_194_304)
    admitted = admit_tool_contracts(runtime, descriptors, contract(), limits)
    assert 0 < admitted['reservations']['receiptBytes'] < limits['max_receipt_bytes']
    assert admitted['reservations']['eventBytes'] == 4096
    for key, value in [('max_receipt_bytes', 1000), ('max_event_bytes', 128), ('max_evidence_bytes', 1000),
            ('max_provider_requests', None), ('max_tool_calls', None)]:
        with pytest.raises(ValueError): admit_tool_contracts(runtime, descriptors, contract(), {**limits, key: value})


def test_current_runtime_registry_is_verified():
    from prosaic_harness.tool_contracts import admit_tool_contracts
    runtime = runtime_api.ProsaicRuntime(config(), custom_tools=tools())
    descriptors = dict(runtime.tool_descriptors)
    descriptors['lookup_entity'] = {**descriptors['lookup_entity'], 'version': 'forged'}
    with pytest.raises(ValueError): admit_tool_contracts(runtime, descriptors, contract(),
        dict(max_provider_requests=2, max_tool_calls=2))
