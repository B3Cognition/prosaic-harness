"""Host recovery policy and durable evidence on the normal Harness paths."""
import json

import pytest

from prosaic_harness import Harness, WorkflowAdmissionError
from prosaic_runtime import ProsaicRuntime, Verdict

from support.conversation_host import conversation_fixture  # noqa: F401
from test_workflow_rules_admission import definition, factory, guard, load, yaml_project
from test_workflow_rules_execution import rule_endpoint  # noqa: F401


def test_defaults_preserve_workflow_and_bundle_identity():
    ordinary = factory()
    explicit = factory(binding_options={
        'rule_retries': 1, 'correct_malformed_tool_calls': False,
    })
    assert ordinary.build(definition()).fingerprint == explicit.build(definition()).fingerprint
    assert ordinary._bundle_material() == explicit._bundle_material()


def test_yaml_seals_nondefault_host_options(tmp_path):
    path = yaml_project(tmp_path)
    original = load(path, guards=[guard()])
    configured = load(path, guards=[guard()], rule_retries=2, correct_malformed_tool_calls=True)
    assert configured.fingerprint == configured.current_fingerprint()
    assert configured.fingerprint != original.fingerprint


@pytest.mark.parametrize('options', [{'rule_retries': True}, {'rule_retries': 4},
    {'correct_malformed_tool_calls': 1}])
def test_invalid_recovery_options_fail_admission(options):
    with pytest.raises(ValueError):
        factory(binding_options=options)


def test_injected_runtime_must_match_bound_recovery_options(tmp_path):
    registered = [guard()]
    configured = factory(registered=registered, binding_options={'rule_retries': 2}).build(definition())
    with pytest.raises((ValueError, WorkflowAdmissionError)):
        Harness(configured, tmp_path / 'wrong', runtime=ProsaicRuntime(configured.config, guards=registered))
    Harness(configured, tmp_path / 'right',
            runtime=ProsaicRuntime(configured.config, guards=registered, rule_retries=2))


def test_guarded_step_retries_twice_and_records_only_outcomes(rule_endpoint, tmp_path):
    cfg, requests, replies = rule_endpoint
    def review(stage, ctx):
        return Verdict(json.loads(ctx.draft)['ok'])
    registered = [guard(check=review, fixes=True)]
    options = dict(cfg=cfg, registered=registered, policy_options={'max_provider_requests_per_invocation': 3},
        body='ALWAYS review. <!-- enforce: review_scope(stage=final, on_violation=fix) -->')
    enabled = factory(**options, binding_options={'rule_retries': 2}).build(definition())
    default = factory(**options).build(definition())
    assert enabled.fingerprint != default.fingerprint
    replies.extend(['{"ok":false}', '{"ok":false}', '{"ok":true}'])
    h = Harness(enabled, tmp_path / 'run')
    state = h.run({})
    assert state['status'] == 'completed' and state['calls'] == 1 and len(requests) == 3
    receipt = h.store.load_receipt('legacy', state['invocations'][0]['id'])
    meta = receipt['result']['metadata']
    ids = meta['workflow_rules_v1']['rules']['violated']
    assert ids
    assert meta['guarded_recovery_v1'] == {'version': 1, 'ruleRetriesUsed': 2,
        'rulesDeclined': ids, 'rulesRetried': ids, 'toolRequestCorrections': []}
    assert Harness(enabled, tmp_path / 'run').resume()['status'] == 'completed'
    with pytest.raises(ValueError):
        Harness(default, tmp_path / 'run').resume()
    assert len(requests) == 3


def test_conversation_persists_retry_and_refuses_changed_binding(conversation_fixture):
    from dataclasses import replace
    from prosaic_harness import ConversationBindings, ConversationError
    from test_workflow_rules_admission import artifact
    from test_workflow_rules_execution import strict

    with conversation_fixture('file') as fx:
        def binding(retries):
            return ConversationBindings(artifact(), version='recovery-v1', config=fx.bindings.config,
                policy=fx.bindings.policy, run_policy=replace(fx.bindings.run_policy, max_provider_requests=3),
                guards=[guard(check=strict)], rule_retries=retries)

        fx.bindings = binding(2)
        controller = fx.fresh_controller()
        initial = controller.create()
        for answer in ('{"ok":false}', '{"ok":false}', '{"ok":true}'):
            fx.queue_text(answer)
        arguments = dict(message_id='review', message='Answer', expected_revision=initial.revision)
        result = controller.send(initial.session_id, **arguments).document
        assert result['status'] == 'completed'
        saved = fx.store.load_session(initial.session_id, scope=fx.scope).state
        receipt = fx.store.load_receipt(initial.session_id, saved['turns'][-1]['attempts'][-1], scope=fx.scope)
        assert receipt['guardedRecoveryV1'] == {'version': 1, 'ruleRetriesUsed': 2, 'rulesDeclined': [],
            'rulesRetried': receipt['rules']['violated'], 'toolRequestCorrections': []}
        assert fx.fresh_controller().send(initial.session_id, **arguments).document == result
        changed = binding(1)
        fx.bindings = changed
        with pytest.raises(ConversationError, match='bindingMismatch'):
            fx.fresh_controller().recover(initial.session_id)
        assert fx.provider_calls == 3


def test_required_tool_correction_is_forwarded_and_receipted(rule_endpoint, tmp_path):
    from dataclasses import replace
    from prosaic_harness import WorkflowBindings, WorkflowCatalog, WorkflowFactory, WorkflowPolicy
    from prosaic_runtime import CustomTool, ProsaicArtifact
    from test_workflow_rules_admission import SCHEMA, artifact
    from test_workflow_rules_execution import strict

    config, requests, replies = rule_endpoint
    config = replace(config, allowed_tools=frozenset({'lookup'}))
    agent = artifact()
    agent = ProsaicArtifact.from_inspection({
        'id': agent.id, 'type': 'subagent', 'body': agent.body,
        'frontmatter': {**agent.frontmatter, 'tools': ['lookup']},
    })
    reads = []
    lookup = CustomTool('lookup', 'Read synthetic data', {'type': 'object', 'additionalProperties': False},
                        lambda value: reads.append(value) or {'ok': True}, '1')
    graph = definition()
    graph['steps']['review'].update(tools=['lookup'], initial_tool='lookup')
    factory = WorkflowFactory(catalog=WorkflowCatalog(agents={'reviewer': agent}, schemas={'result': SCHEMA}),
        bindings=WorkflowBindings(config=config, guards=[guard(check=strict)], custom_tools={'lookup': lookup},
                                  correct_malformed_tool_calls=True),
        policy=WorkflowPolicy(allowed_agents={'reviewer'}, allowed_schemas={'result'}, allowed_tools={'lookup'},
                              allowed_guards={'review_scope'}, max_provider_requests_per_invocation=3,
                              max_tool_calls_per_invocation=1))
    replies.extend([{'name': 'lookup', 'input': {'bad': True}}, {'name': 'lookup', 'input': {}}, '{"ok":true}'])
    harness = Harness(factory.build(graph), tmp_path / 'correction')
    state = harness.run({})
    assert state['status'] == 'completed' and reads == [{}] and len(requests) == 3
    assert requests[0]['tool_choice'] == requests[1]['tool_choice']
    receipt = harness.store.load_receipt('legacy', state['invocations'][0]['id'])
    assert receipt['result']['metadata']['guarded_recovery_v1']['toolRequestCorrections'] == ['argumentsSchema']
