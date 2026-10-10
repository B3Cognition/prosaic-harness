"""Native admission reconstruction and recovery through the real SQL facade."""
import uuid
import json

import pytest
from prosaic_harness import (Harness, WorkflowCatalog, WorkflowBindings, WorkflowPolicy,
                             WorkflowFactory, RevisionConflict)
from prosaic_harness import WorkflowBundle, WorkflowReference, Validator
from prosaic_runtime import EndpointConfig, ProsaicArtifact, RuntimeConfig, Result
from test_store import pg_store


def factory(url, **caps):
    artifact = ProsaicArtifact.from_inspection({'id': 'subagents/synthetic.md', 'type': 'subagent',
        'frontmatter': {'name': 'synthetic', 'description': 'Synthetic admission fixture'},
        'body': 'Return structured JSON for {{args}}.'})
    config = RuntimeConfig({'local': EndpointConfig(url, 'synthetic', features={'streaming': False})}, {}, 'local')
    return WorkflowFactory(catalog=WorkflowCatalog(agents={'synthetic': artifact},
        schemas={'result': {'type': 'object', 'required': ['approved'],
            'properties': {'approved': {'type': 'boolean'}}, 'additionalProperties': False}}),
        bindings=WorkflowBindings(config=config, validators={
            'confirmation': Validator('confirmation-v1', lambda value, context: [])}),
        policy=WorkflowPolicy(allowed_agents={'synthetic'}, allowed_schemas={'result'},
            allowed_validators={'confirmation'}, **caps))


def graph():
    return {'version': 1, 'start': 'work', 'steps': {
        'work': {'kind': 'agent', 'agent': 'synthetic', 'schema': 'result', 'next': 'selection'},
        'selection': {'kind': 'pause', 'question': 'Accept synthetic output?',
            'choices': {'accept': 'done'}, 'requires': ['work'], 'response_schema': 'result'},
        'done': {'kind': 'finish', 'requires': ['work']}}}


def test_native_sql_fresh_factory_resume_and_revision(pg_store, model_server):
    run_id = uuid.uuid4().hex
    first = Harness(factory(model_server.url).build(graph()), store=pg_store, run_id=run_id)
    assert first.run({'query': 'synthetic'})['status'] == 'waiting'
    revision = first.status().revision
    second = Harness(factory(model_server.url).build(graph()), store=pg_store, run_id=run_id)
    with pytest.raises(ValueError, match='expected_revision'):
        second.resume(choice='accept', response={'approved': True})
    with pytest.raises(RevisionConflict):
        second.resume(choice='accept', response={'approved': True}, expected_revision='stale')
    state = second.resume(choice='accept', response={'approved': True}, expected_revision=revision)
    assert state['status'] == 'completed' and state['calls'] == 1
    assert second.status().state['status'] == 'completed' and model_server.request_count == 1


@pytest.mark.parametrize('oversized', [False, True])
def test_native_sql_receipt_adoption_without_redispatch(pg_store, model_server, monkeypatch, oversized):
    run_id = uuid.uuid4().hex
    caps = {'max_output_bytes': 1000} if oversized else {}
    h = Harness(factory(model_server.url, **caps).build(graph()), store=pg_store, run_id=run_id)
    if oversized:
        monkeypatch.setattr(h.runtime, 'run', lambda *a, **k: Result(0, 'x' * 2000, '', token_usage=3))
    monkeypatch.setattr(h, '_accept', lambda *a: (_ for _ in ()).throw(OSError('crash after receipt')))
    with pytest.raises(OSError):
        h.run({})
    second = Harness(factory(model_server.url, **caps).build(graph()), store=pg_store, run_id=run_id)
    state = second.resume()
    assert state['pending'] is None and state['invocations'][0]['status'] == 'complete'
    assert state['reason'] == 'output_limit' if oversized else state['status'] == 'waiting'
    assert model_server.request_count == (0 if oversized else 1)
    assert second.status().state['calls'] == 1


@pytest.mark.parametrize('bounded_failure', [False, True])
def test_native_sql_bundle_budget_receipt_reconstruction(pg_store, model_server, monkeypatch, bounded_failure):
    run_id = uuid.uuid4().hex
    caps = {'max_provider_requests_per_invocation': 2, 'max_tool_calls_per_invocation': 0}
    if bounded_failure:
        caps['max_tokens'] = 1
    definition = graph()
    definition['steps']['selection']['validators'] = ['confirmation']
    bundle = WorkflowBundle('sql-controls-v1', factory(model_server.url, **caps))
    prepared = bundle.prepare_json(json.dumps({'definition': definition}))
    h = Harness(prepared.workflow, store=pg_store, run_id=run_id)
    monkeypatch.setattr(h, '_accept', lambda *a: (_ for _ in ()).throw(OSError('crash after receipt')))
    with pytest.raises(OSError, match='crash after receipt'):
        h.run(prepared.workflow.prepare_inputs({'query': 'synthetic'}))
    pending = h.status()
    assert pending.state['pending'] is not None
    invocation_id = pending.state['invocations'][0]['id']
    receipt = pg_store.load_receipt(run_id, invocation_id)
    assert receipt['result']['token_usage'] == 2
    assert receipt['result']['metadata']['invocation_budgets_v1']['provider_requests'] == 1
    fresh_bundle = WorkflowBundle('sql-controls-v1', factory(model_server.url, **caps))
    workflow = fresh_bundle.reconstruct(prepared.proposal_json,
        WorkflowReference.from_dict(prepared.reference.to_dict()))
    second = Harness(workflow, store=pg_store, run_id=run_id)
    state = second.resume()
    assert state['pending'] is None and state['invocations'][0]['status'] == 'complete'
    assert state['invocations'][0]['token_usage'] == 2
    assert state['validators'] == {'confirmation': 'confirmation-v1'}
    assert model_server.request_count == 1
    snapshot = second.status()
    assert pg_store.load_receipt(run_id, invocation_id) == receipt
    if bounded_failure:
        assert state['status'] == 'blocked' and state['reason'] == 'token_limit'
        assert second.interaction(include_response_schema=True) is None
        assert second.resume(retry_interrupted=True, expected_revision=snapshot.revision)['reason'] == 'token_limit'
    else:
        assert state['status'] == 'waiting'
        assert second.interaction(include_response_schema=True).revision == snapshot.revision
        for kwargs, error in (({'choice': 'other', 'response': {'approved': True}}, ValueError),
                              ({'choice': 'accept', 'response': {'approved': 'yes'}}, ValueError),
                              ({'choice': 'accept', 'response': {'approved': True}, 'expected_revision': 'stale'}, RevisionConflict)):
            with pytest.raises(error):
                second.resume(**({'expected_revision': snapshot.revision} | kwargs))
            assert second.status().state == snapshot.state and second.status().revision == snapshot.revision
        assert second.resume(choice='accept', response={'approved': True},
                             expected_revision=snapshot.revision)['status'] == 'completed'
    assert model_server.request_count == 1
