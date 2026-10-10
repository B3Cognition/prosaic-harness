"""Native admission reconstruction and recovery through the real SQL facade."""
import uuid

import pytest
from prosaic_harness import (Harness, WorkflowCatalog, WorkflowBindings, WorkflowPolicy,
                             WorkflowFactory, RevisionConflict)
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
        bindings=WorkflowBindings(config=config),
        policy=WorkflowPolicy(allowed_agents={'synthetic'}, allowed_schemas={'result'}, **caps))


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
