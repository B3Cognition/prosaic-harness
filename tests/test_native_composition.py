"""Offline native composition, provenance, host checks and bounded revisits."""
import json

import pytest
from prosaic_runtime import EndpointConfig, ProsaicArtifact, ProsaicRuntime, Result, RuntimeConfig
from prosaic_harness import (Harness, Validator, WorkflowAdmissionError, WorkflowBindings,
                             WorkflowCatalog, WorkflowFactory, WorkflowPolicy)


def composition(checks, *, allow_composition=True, max_calls=2):
    def approved(value, context):
        checks.append(('approved', context.step))
        assert context.request == {'query': 'sample'}
        assert value['entity_id'] == context.artifacts['find']['entity_id']
        assert context.bindings['review']['dependencies']['find'] == context.bindings['find']
        return [] if value['approved'] else ['Approval is required']

    def confirmation(value, context):
        checks.append(('confirmation', context.step))
        assert context.bindings['review']['dependencies']['find'] == context.bindings['find']
        return ([] if value['response']['entity_id'] == context.artifacts['review']['entity_id']
                else ['Confirm the reviewed entity'])

    factory = WorkflowFactory(
        catalog=WorkflowCatalog(agents={
            'finder': ProsaicArtifact('commands/finder.md', 'command', {}, 'Find the requested entity.'),
            'reviewer': ProsaicArtifact('subagents/reviewer.md', 'subagent',
                {'name': 'reviewer', 'description': 'Review the supplied entity'},
                'Review the supplied find artifact.'),
        }, schemas={
            'found': {'type': 'object', 'properties': {'entity_id': {'type': 'string'},
                      'revision': {'type': 'integer'}}, 'required': ['entity_id', 'revision'],
                      'additionalProperties': False},
            'reviewed': {'type': 'object', 'properties': {'entity_id': {'type': 'string'},
                         'approved': {'type': 'boolean'}}, 'required': ['entity_id', 'approved'],
                         'additionalProperties': False},
            'confirmation': {'type': 'object', 'properties': {'entity_id': {'type': 'string'}},
                             'required': ['entity_id'], 'additionalProperties': False},
        }),
        bindings=WorkflowBindings(config=RuntimeConfig(
            {'local': EndpointConfig('http://localhost:9/v1', 'synthetic')}, {}, 'local'),
            validators={'approved': Validator('v1', approved),
                        'confirmation': Validator('v1', confirmation)}),
        policy=WorkflowPolicy(allowed_agents={'finder', 'reviewer'},
            allowed_schemas={'found', 'reviewed', 'confirmation'},
            allowed_validators={'approved', 'confirmation'},
            allow_agent_composition=allow_composition, max_calls=max_calls),
    )
    definition = {'version': 1, 'start': 'find', 'steps': {
        'find': {'kind': 'agent', 'agent': 'finder', 'schema': 'found', 'next': 'fresh_route'},
        'fresh_route': {'kind': 'gate', 'from': 'find', 'field': ['revision'], 'equals': 1,
                        'pass': 'review', 'fail': 'done'},
        'review': {'kind': 'agent', 'agent': 'reviewer', 'schema': 'reviewed',
                   'inputs': ['find'], 'next': 'check_review'},
        'check_review': {'kind': 'check', 'from': 'review', 'validators': ['approved'],
                         'pass': 'confirm', 'fail': 'rejected'},
        'confirm': {'kind': 'pause', 'question': 'Accept the reviewed entity?',
                    'choices': {'accept': 'done', 'refresh': 'find'},
                    'requires': ['find', 'review'], 'response_schema': 'confirmation',
                    'validators': ['confirmation']},
        'done': {'kind': 'finish', 'requires': ['find', 'review']},
        'rejected': {'kind': 'finish', 'outcome': 'rejected'},
    }}
    return factory, definition


def offline_runtime(workflow, monkeypatch, calls):
    runtime = ProsaicRuntime(workflow.config)
    def run(artifact, arguments, **kwargs):
        arguments = json.loads(arguments)
        calls.append((artifact.id, arguments))
        if artifact.type == 'command':
            assert arguments['artifacts'] == {} and arguments['artifact_bindings'] == {}
            revision = sum(name == artifact.id for name, _ in calls)
            output = {'entity_id': 'sample-1', 'revision': revision}
        else:
            assert arguments['artifacts'] == {'find': {'entity_id': 'sample-1', 'revision': 1}}
            assert set(arguments['artifact_bindings']) == {'find'}
            assert arguments['artifact_bindings']['find']['dependencies'] == {}
            output = {'entity_id': arguments['artifacts']['find']['entity_id'], 'approved': True}
        return Result(0, json.dumps(output), '', token_usage=1)
    monkeypatch.setattr(runtime, 'run', run)
    return runtime


def test_composition_routes_checks_and_confirms_with_owned_input_bindings(tmp_path, monkeypatch):
    checks, calls = [], []
    factory, definition = composition(checks)
    workflow = factory.build(definition)
    assert checks == []
    harness = Harness(workflow, tmp_path / 'run', runtime=offline_runtime(workflow, monkeypatch, calls))
    assert checks == []  # Default host validators are bound without execution.
    waiting = harness.run({'query': 'sample'})
    assert waiting['status'] == 'waiting' and waiting['calls'] == 2
    assert checks == [('approved', 'review')]
    assert [name for name, _ in calls] == ['commands/finder.md', 'subagents/reviewer.md']
    assert calls[1][1]['artifact_bindings']['find'] == waiting['bindings']['find']
    assert waiting['bindings']['review']['dependencies'] == {'find': waiting['bindings']['find']}
    assert waiting['visits'] == {'find': 1, 'fresh_route': 1, 'review': 1,
                                  'check_review': 1, 'confirm': 1}
    assert harness.status().state['status'] == 'waiting' and len(checks) == 1

    # Another worker reconstructs the same admission and uses its default checks.
    rebuilt = factory.build(definition)
    resumed = Harness(rebuilt, tmp_path / 'run', runtime=offline_runtime(rebuilt, monkeypatch, calls))
    assert checks == [('approved', 'review')]
    completed = resumed.resume(choice='accept', response={'entity_id': 'sample-1'})
    assert completed['status'] == 'completed' and completed['calls'] == 2
    assert checks == [('approved', 'review'), ('confirmation', 'confirm')]
    assert len(calls) == 2 and resumed.resume()['status'] == 'completed'
    assert len(calls) == 2 and len(checks) == 2


def test_composition_revisit_cannot_finish_with_a_stale_dependent_review(tmp_path, monkeypatch):
    checks, calls = [], []
    factory, definition = composition(checks, max_calls=3)
    workflow = factory.build(definition)
    harness = Harness(workflow, tmp_path / 'run', runtime=offline_runtime(workflow, monkeypatch, calls))
    waiting = harness.run({'query': 'sample'})
    original = waiting['bindings']['find']['id']
    blocked = harness.resume(choice='refresh', response={'entity_id': 'sample-1'})
    assert blocked['status'] == 'blocked' and blocked['reason'] == 'stale_artifact'
    assert blocked['calls'] == 3 and len(calls) == 3
    assert blocked['bindings']['find']['id'] != original
    assert blocked['bindings']['review']['dependencies']['find']['id'] == original
    assert harness.resume()['reason'] == 'stale_artifact' and len(calls) == 3


def test_composition_call_budget_stops_before_the_second_agent(tmp_path, monkeypatch):
    checks, calls = [], []
    factory, definition = composition(checks, max_calls=1)
    workflow = factory.build(definition)
    harness = Harness(workflow, tmp_path / 'run', runtime=offline_runtime(workflow, monkeypatch, calls))
    blocked = harness.run({'query': 'sample'})
    assert blocked['reason'] == 'call_limit' and blocked['calls'] == 1
    assert set(blocked['outputs']) == {'find'} and checks == []
    assert harness.resume()['reason'] == 'call_limit' and len(calls) == 1


def test_composition_requires_the_separate_host_permission():
    checks = []
    factory, definition = composition(checks, allow_composition=False)
    with pytest.raises(WorkflowAdmissionError) as caught:
        factory.build(definition)
    assert caught.value.code == 'policy_denied' and checks == []
