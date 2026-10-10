"""Public admission and interaction views never publish operator checkpoints."""
from dataclasses import FrozenInstanceError
import hashlib
import json

import pytest

from prosaic_harness import Harness, WorkflowAdmissionError
from test_native_execution import bound
from test_workflow_factory import factory, graph


def test_prepare_inputs_is_owned_bounded_and_does_not_reserve(tmp_path, monkeypatch):
    workflow = factory(max_run_input_bytes=100).build(graph())
    def forbidden(*args, **kwargs):
        pytest.fail('input preparation performed an execution or filesystem effect')
    monkeypatch.setattr('pathlib.Path.resolve', forbidden)
    monkeypatch.setattr('prosaic_runtime.ProsaicRuntime.run', forbidden)
    inputs = {'query': ['safe']}
    prepared = workflow.prepare_inputs(inputs)
    inputs['query'].append('mutated')
    assert prepared == {'query': ['safe']}
    with pytest.raises(WorkflowAdmissionError):
        workflow.prepare_inputs({'query': 'x' * 200})
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('case', ['cycle', 'sharing', 'nonfinite', 'mutation'])
def test_prepare_inputs_rejects_unadmitted_data_or_workflow(case):
    workflow = factory(max_run_input_bytes=100).build(graph())
    inputs = []
    if case == 'cycle':
        inputs.append(inputs)
    elif case == 'sharing':
        inputs = [['x' * 20]] * 10
    elif case == 'nonfinite':
        inputs = {'query': float('inf')}
    else:
        workflow.definition['steps']['review']['question'] = 'changed'
    with pytest.raises(WorkflowAdmissionError):
        workflow.prepare_inputs(inputs)


def test_prepare_inputs_preserves_depth_nodes_and_no_binding_callbacks():
    from prosaic_harness import WorkflowFactory, WorkflowCatalog, WorkflowBindings, WorkflowPolicy, Validator
    from test_workflow_factory import config, agent, tools
    def forbidden(*args, **kwargs):
        pytest.fail('input preparation executed a product binding')
    proposal = graph()
    proposal['steps']['review'].update(response_schema='result', validators=['guard'])
    workflow = WorkflowFactory(catalog=WorkflowCatalog(agents={'finder': agent()},
        schemas={'result': {'type': 'object'}}),
        bindings=WorkflowBindings(config=config(), custom_tools=tools(),
            validators={'guard': Validator('v1', forbidden)}),
        policy=WorkflowPolicy(allowed_agents=frozenset({'finder'}),
            allowed_schemas=frozenset({'result'}), allowed_tools=frozenset({'lookup_entity'}),
            allowed_validators=frozenset({'guard'}), allowed_model_tiers=frozenset({'fast'}),
            max_json_depth=8, max_json_nodes=100)).build(proposal)
    assert workflow.prepare_inputs([0, True, None]) == [0, True, None]
    for value in ([0] * 100, [[[[[[[[[0]]]]]]]]]):
        with pytest.raises(WorkflowAdmissionError) as caught:
            workflow.prepare_inputs(value)
        assert caught.value.code == 'limit_exceeded'


def test_interaction_projects_only_selected_content_from_one_load(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch)
    h.run({'private_input': 'PRIVATE INPUT'})
    before = h.status()
    loads = []
    load = h.store.load_run
    def counted(run_id):
        loads.append(run_id)
        return load(run_id)
    monkeypatch.setattr(h.store, 'load_run', counted)
    view = h.interaction()
    assert loads == ['legacy']
    assert view.choices == ('accept', 'reject')
    assert view.revision == before.revision and view.run_id == before.state['run_id']
    assert view.step_id == 'review' and view.question == 'Accept the result?'
    assert view.deadline == before.state['deadline']
    assert view.to_dict() == {'version': 1, 'runId': view.run_id, 'revision': before.revision,
                             'stepId': 'review', 'question': 'Accept the result?',
                             'choices': ['accept', 'reject'], 'deadline': before.state['deadline']}
    selected = h.interaction(review_outputs=('find',))
    assert selected.to_dict()['reviewOutputs'] == {'find': {'found': True}}
    assert 'PRIVATE INPUT' not in json.dumps(selected.to_dict()) and len(calls) == 1
    selected.review_outputs['find']['found'] = False
    selected.to_dict()['reviewOutputs'].clear()
    assert selected.to_dict()['reviewOutputs'] == {'find': {'found': True}}
    with pytest.raises(FrozenInstanceError):
        selected.question = 'changed'


def test_interaction_schema_is_opt_in_owned_and_has_stable_digest(tmp_path, monkeypatch):
    proposal = graph()
    proposal['steps']['review']['response_schema'] = 'result'
    h, calls = bound(tmp_path, monkeypatch, proposal=proposal)
    h.run({})
    schema = {'type': 'object', 'properties': {'found': {'type': 'boolean'}},
              'required': ['found'], 'additionalProperties': False}
    expected = hashlib.sha256(json.dumps(schema, sort_keys=True, allow_nan=False).encode()).hexdigest()
    view = h.interaction()
    assert view.response_schema_digest == expected
    assert 'responseSchema' not in view.to_dict()
    public = h.interaction(include_response_schema=True)
    assert public.response_schema == schema and public.to_dict()['responseSchemaDigest'] == expected
    public.response_schema['required'].append('private')
    assert h.interaction(include_response_schema=True).response_schema == schema
    assert len(calls) == 1


@pytest.mark.parametrize('selection', [('missing',), ('review',), ('done',), 'find', (['find'],)])
def test_interaction_rejects_unknown_or_unavailable_output_selection(tmp_path, monkeypatch, selection):
    h, _ = bound(tmp_path, monkeypatch)
    h.run({})
    with pytest.raises(WorkflowAdmissionError):
        h.interaction(review_outputs=selection)


def test_interaction_rejects_oversized_views_without_truncation(tmp_path, monkeypatch):
    h, _ = bound(tmp_path, monkeypatch)
    h.run({})
    before = h.status()
    with pytest.raises(WorkflowAdmissionError) as caught:
        h.interaction(maximum_bytes=10)
    assert caught.value.code == 'limit_exceeded'
    view = h.interaction(review_outputs=('find',))
    size = len(json.dumps(view.to_dict(), sort_keys=True, allow_nan=False).encode())
    assert h.interaction(review_outputs=('find',), maximum_bytes=size).to_dict() == view.to_dict()
    with pytest.raises(WorkflowAdmissionError):
        h.interaction(review_outputs=('find',), maximum_bytes=size - 1)
    assert h.status().revision == before.revision


def test_interaction_rejects_available_alias_without_an_output(tmp_path, monkeypatch):
    proposal = graph()
    proposal['start'] = 'review'
    proposal['steps']['review'].pop('requires')
    h, calls = bound(tmp_path, monkeypatch, proposal=proposal)
    assert h.run({})['status'] == 'waiting'
    with pytest.raises(WorkflowAdmissionError) as caught:
        h.interaction(review_outputs=('find',))
    assert caught.value.code == 'unknown_reference' and calls == []


def test_public_schema_cannot_bypass_native_state_ceiling(tmp_path, monkeypatch):
    proposal = graph()
    proposal['steps']['review']['response_schema'] = 'result'
    h, _ = bound(tmp_path, monkeypatch, proposal=proposal, max_state_bytes=7000,
                 schemas={'result': {'type': 'object', 'description': 'x' * 7000}})
    h.run({})
    before = h.status()
    assert h.interaction() is not None
    with pytest.raises(WorkflowAdmissionError) as caught:
        h.interaction(include_response_schema=True, maximum_bytes=8_388_608)
    assert caught.value.code == 'limit_exceeded' and h.status() == before


def test_interaction_reconstructs_waiting_and_returns_none_after_finish(tmp_path, monkeypatch):
    h, calls = bound(tmp_path, monkeypatch)
    h.run({})
    fresh = Harness(factory().build(graph()), tmp_path / 'run')
    assert fresh.interaction().to_dict() == h.interaction().to_dict()
    h.resume(choice='accept')
    assert fresh.interaction() is None and len(calls) == 1


def test_interaction_returns_none_for_running_and_blocked_states(tmp_path, monkeypatch):
    h, _ = bound(tmp_path, monkeypatch)
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(h.runtime, 'run', interrupted)
    with pytest.raises(KeyboardInterrupt):
        h.run({})
    assert h.interaction() is None
    assert h.resume()['reason'] == 'interrupted_call'
    assert h.interaction() is None


def test_invalid_response_preserves_revision_and_has_safe_code(tmp_path, monkeypatch):
    from prosaic_harness import HumanResponseError
    proposal = graph()
    proposal['steps']['review']['response_schema'] = 'result'
    h, calls = bound(tmp_path, monkeypatch, proposal=proposal)
    h.run({})
    before = h.status()
    with pytest.raises(HumanResponseError) as caught:
        h.resume(choice='accept', response={'found': 'PRIVATE'}, expected_revision=before.revision)
    assert caught.value.code == 'response_schema_invalid'
    assert caught.value.to_dict() == {'code': 'response_schema_invalid',
                                      'issues': [{'code': 'type', 'location': '$.*'}]}
    assert 'PRIVATE' not in str(caught.value) + json.dumps(caught.value.to_dict())
    after = h.status()
    assert after.revision == before.revision and after.state == before.state and len(calls) == 1


def test_response_limit_has_safe_code_and_retains_current_interaction(tmp_path, monkeypatch):
    from prosaic_harness import HumanResponseError
    proposal = graph()
    proposal['steps']['review']['response_schema'] = 'result'
    h, _ = bound(tmp_path, monkeypatch, proposal=proposal, max_human_response_bytes=20)
    h.run({})
    before = h.status()
    with pytest.raises(HumanResponseError) as caught:
        h.resume(choice='accept', response={'found': 'PRIVATE' * 20})
    assert caught.value.code == 'response_limit'
    assert h.status() == before


def test_human_schema_evaluation_failure_blocks_and_deadline_takes_precedence(tmp_path, monkeypatch):
    from prosaic_harness.schema_validation import SchemaEvaluationError
    from prosaic_harness.schema_validation import evaluate_schema
    proposal = graph()
    proposal['steps']['review']['response_schema'] = 'result'
    def failed(*args, **kwargs):
        if kwargs.get('profile', {}).get('maximum_instance_bytes') == 20:
            raise SchemaEvaluationError()
        return evaluate_schema(*args, **kwargs)
    # A distinct human bound identifies only the response evaluation, preserving
    # the independent operator-ledger check performed before response admission.
    h, _ = bound(tmp_path / 'first', monkeypatch, proposal=proposal, max_human_response_bytes=20)
    h.run({})
    monkeypatch.setattr('prosaic_harness.engine.evaluate_schema', failed)
    assert h.resume(choice='accept', response={'found': True})['reason'] == 'schema_error'
    assert not any(event['event'] == 'human_decision' for event in h.status().state['history'])
    second, _ = bound(tmp_path / 'second', monkeypatch, proposal=proposal, max_human_response_bytes=20)
    # Restore real evaluation for the model output, then fail only the human response.
    monkeypatch.setattr('prosaic_harness.engine.evaluate_schema', evaluate_schema)
    second.run({})
    monkeypatch.setattr('prosaic_harness.engine.evaluate_schema', failed)
    second.clock = lambda: 10**15
    assert second.resume(choice='accept', response={'found': True})['reason'] == 'run_deadline'


def test_safe_response_issues_are_bounded_owned_and_structural():
    from prosaic_harness import HumanResponseError
    issues = [{'code': 'PRIVATE', 'location': '$.PRIVATE'}] * 8
    error = HumanResponseError('response_schema_invalid', issues)
    assert error.to_dict() == {'code': 'response_schema_invalid',
                               'issues': [{'code': 'schema', 'location': '$'}] * 5}
    error.to_dict()['issues'][0]['code'] = 'changed'
    issues[0]['location'] = '$.changed'
    assert error.to_dict()['issues'][0] == {'code': 'schema', 'location': '$'}
    with pytest.raises(TypeError):
        error.issues[0]['location'] = '$.changed'
    with pytest.raises(ValueError):
        HumanResponseError('PRIVATE')


def test_running_run_rejects_human_choice_without_decision(tmp_path, monkeypatch):
    from prosaic_harness import HumanResponseError
    h, _ = bound(tmp_path, monkeypatch)
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(h.runtime, 'run', interrupted)
    with pytest.raises(KeyboardInterrupt):
        h.run({})
    before = h.status()
    with pytest.raises(HumanResponseError) as caught:
        h.resume(choice='accept')
    assert caught.value.code == 'no_pending_choice'
    assert h.status() == before
