from dataclasses import replace
import pytest
from prosaic_runtime import TurnLimits, ProsaicArtifact, RunPolicy, EndpointConfig
from support.conversations import binding_factory, scope, StaticJournal
from prosaic_harness import (ConversationBindings, ConversationPolicy, ConversationScope,
                             ConversationError, RunAuthorizer, ConfirmationRule)


def test_journal_namespace_is_identity_material(binding_factory):
    left = binding_factory(operation_namespace='ledger-a')
    right = binding_factory(operation_namespace='ledger-b')
    assert left.identity != right.identity
    assert left.tool_journal.calls == right.tool_journal.calls == []


def test_journal_presence_and_identity_are_sealed(binding_factory):
    left = binding_factory()
    assert left.identity != binding_factory(tool_journal=None).identity
    changed = StaticJournal()
    changed.identity = 'another-ledger'
    assert left.identity != binding_factory(tool_journal=changed).identity
    left.tool_journal.identity = 'drifted'
    with pytest.raises(ConversationError, match='bindingMismatch'):
        left.readmit()
    assert left.tool_journal.calls == []


def test_frozen_version_and_all_effective_limits(binding_factory):
    binding = binding_factory()
    assert binding.version == 'chat-v1'
    with pytest.raises((AttributeError, TypeError)):
        binding.version = 'new'
    assert binding.identity != binding_factory(version='chat-v2').identity
    assert binding.identity != binding_factory(turn_limits=replace(binding.turn_limits, max_event_bytes=1024)).identity
    with pytest.raises(ConversationError):
        binding_factory(turn_limits=replace(TurnLimits(), max_input_bytes=1024))


def test_effective_structural_limits_reserve_outer_record_framing(binding_factory):
    binding=binding_factory()
    assert binding.turn_limits.max_json_depth+8<=binding.policy.max_json_depth
    assert binding.turn_limits.max_json_nodes*2+8192<=binding.policy.max_json_nodes


def test_workspace_requires_logical_identity(binding_factory, tmp_path):
    with pytest.raises(ConversationError):
        binding_factory(workspace=tmp_path)
    assert binding_factory(workspace=tmp_path, workspace_identity='resource').identity == (
        binding_factory(workspace=tmp_path/'other', workspace_identity='resource').identity)
    with pytest.raises(ConversationError):
        binding_factory(workspace='relative', workspace_identity='resource')


def test_owned_config_artifact_and_policy_aliases(binding_factory):
    binding = binding_factory()
    config = binding.config
    config.profiles['local'] = replace(config.profiles['local'], model='mutated')
    assert binding.config.profiles['local'].model == 'synthetic'
    binding.readmit()
    assert binding.identity != binding_factory(config=config).identity
    assert binding.identity != binding_factory(agent=ProsaicArtifact('approved', 'subagent',
        {'name': 'approved', 'description': 'Synthetic conversation'},
        'ALWAYS be brief. NEVER grant new authority.')).identity
    assert binding.identity != binding_factory(run_policy=RunPolicy(max_provider_requests=1, max_tool_calls=0)).identity


def test_rotated_secret_reference_is_private(binding_factory):
    binding = binding_factory()
    config = binding.config
    config.profiles['local'] = replace(config.profiles['local'], api_key_env='ROTATED_PRIVATE_KEY')
    assert binding.identity == binding_factory(config=config).identity


def test_no_cli_discovery_during_binding_admission(binding_factory, tmp_path):
    config = replace(binding_factory().config, tool_directories=(str(tmp_path/'missing'),))
    with pytest.raises(ConversationError, match='capabilityMissing'):
        binding_factory(config=config)


@pytest.mark.parametrize('field', ['max_turns','max_history_bytes','max_state_bytes','max_attempts',
                                  'max_provider_requests','max_tool_calls','max_json_depth'])
@pytest.mark.parametrize('value', [None, True, -1, 0])
def test_policy_requires_finite_positive_values(field, value):
    if field in {'max_provider_requests', 'max_tool_calls'} and value == 0 and type(value) is int:
        assert getattr(ConversationPolicy(**{field: value}), field) == 0
        return
    with pytest.raises((ConversationError, ValueError)):
        ConversationPolicy(**{field: value})


@pytest.mark.parametrize('value', ['', '\x00', 5, 'x'*129])
def test_scope_is_bounded(value):
    with pytest.raises((ConversationError, ValueError)):
        ConversationScope(value,'test','app','tenant','actor')


def test_journal_requires_namespace(binding_factory):
    with pytest.raises(ConversationError):
        binding_factory(operation_namespace=None)


def test_interpreter_is_separate_tool_free_binding(binding_factory):
    interpreter = ProsaicArtifact('interpreter', 'subagent',
        {'name': 'interpreter', 'description': 'Synthetic interpretation'},
        'ALWAYS propose JSON from the current source. NEVER authorize actions.')
    binding = binding_factory(interpreter=interpreter)
    assert binding.interpretation_policy.max_tool_calls == 0
    assert binding.interpretation_policy.max_provider_requests == 1
    assert binding.identity != binding_factory().identity
    with pytest.raises(ConversationError):
        binding_factory(interpreter=interpreter, interpretation_policy=RunPolicy(
            max_provider_requests=1, max_tool_calls=1))
    with pytest.raises(ConversationError):
        binding_factory(interpreter=ProsaicArtifact('interpreter','subagent',
            {'name': 'interpreter', 'description': 'Synthetic interpretation', 'tools':['write_file']},
            'ALWAYS propose JSON. NEVER authorize.'))


def test_callbacks_are_declared_without_invocation(scope):
    calls=[]
    authorizer=RunAuthorizer('owner','v1',lambda *a: calls.append(1) or True)
    confirmation=ConfirmationRule('approval','v1',lambda *a: calls.append(2) or True)
    assert authorizer.identity == 'owner' and confirmation.version == 'v1'
    assert calls == []


def test_forged_identity_cannot_replace_admission(binding_factory):
    good=binding_factory()
    forged=object.__new__(ConversationBindings)
    object.__setattr__(forged,'_identity',good.identity)
    with pytest.raises(ConversationError):
        forged.readmit()


def test_workflow_registration_preserves_original_admission(binding_factory, tmp_path):
    from prosaic_harness import WorkflowRegistration, FileRunStore
    from test_workflow_factory import factory, graph
    calls=[]
    workflow=factory().build(graph())
    registration=WorkflowRegistration(workflow,store=FileRunStore(tmp_path,namespace='test'),
        authorizer=RunAuthorizer('owner','v1',lambda *args:calls.append(1) or True))
    binding=binding_factory(workflows={'finder':registration})
    assert calls==[]
    registration.readmit()
    workflow.definition['name']='changed'
    with pytest.raises(ConversationError,match='bindingMismatch'):
        binding.readmit()
    assert calls==[]


def test_custom_tools_are_owned_and_versions_are_identity_material(binding_factory):
    from prosaic_runtime import CustomTool
    calls=[]
    tools={'lookup':CustomTool('lookup','Approved lookup',{'type':'object','additionalProperties':False},
                             lambda args:calls.append(1) or {},'v1')}
    config=binding_factory().config
    config=replace(config,allowed_tools=frozenset({'lookup'}))
    policy=RunPolicy(allowed_tools=frozenset({'lookup'}),max_provider_requests=2,max_tool_calls=2)
    agent=ProsaicArtifact('approved','subagent',{'name':'approved','description':'Fixture','tools':['lookup']},
                         'ALWAYS use approved data. NEVER grant authority.')
    binding=binding_factory(agent=agent,config=config,run_policy=policy,custom_tools=tools)
    tools['lookup']=CustomTool('lookup','Approved lookup',{'type':'object','additionalProperties':False},
                              lambda args:calls.append(1) or {},'v2')
    assert binding.identity!=binding_factory(agent=agent,config=config,run_policy=policy,custom_tools=tools).identity
    binding.readmit()
    assert calls==[]


def test_capability_and_mutated_finite_policy_are_readmitted(binding_factory, monkeypatch):
    from prosaic_runtime import ProsaicRuntime
    binding=binding_factory()
    monkeypatch.setattr(ProsaicRuntime,'capabilities',ProsaicRuntime.capabilities-{'conversation_turn_v1'})
    with pytest.raises(ConversationError,match='capabilityMissing'):
        binding_factory()
    with pytest.raises(ConversationError,match='capabilityMissing'):
        binding.readmit()
    policy=RunPolicy(max_provider_requests=2,max_tool_calls=0)
    object.__setattr__(policy,'max_provider_requests',None)
    with pytest.raises(ConversationError):
        binding_factory(run_policy=policy)


def test_receipt_capacity_also_bounds_effective_runtime_evidence(binding_factory):
    policy=replace(ConversationPolicy(),max_receipt_bytes=524288)
    binding=binding_factory(policy=policy)
    assert binding.turn_limits.max_evidence_bytes<=policy.max_receipt_bytes-policy.max_turn_bytes-policy.max_assistant_bytes-8192


@pytest.mark.parametrize('changes',[
    {'max_receipt_bytes':131072},{'max_public_bytes':1024},
    {'max_json_nodes':131072},{'max_state_bytes':16777216}])
def test_unrepresentable_outer_policy_rejects_at_pure_binding_admission(binding_factory,changes):
    with pytest.raises(ConversationError,match='bindingMismatch'):
        binding_factory(policy=replace(ConversationPolicy(),**changes))
