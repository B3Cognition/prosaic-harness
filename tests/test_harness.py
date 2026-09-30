import json
from pathlib import Path

import pytest
import yaml
from prosaic_runtime import ProsaicArtifact, Result
from prosaic_harness import Harness, Workflow


def setup(tmp_path, monkeypatch, *, pause=False, repair=False, max_calls=10):
    (tmp_path / '.prosaic').mkdir()
    (tmp_path / 'result.json').write_text(json.dumps({"type": "object", "required": ["approved"],
        "properties": {"approved": {"type": "boolean"}}, "additionalProperties": False}))
    (tmp_path / 'runtime.yml').write_text('default_profile: local\nroutes: {fast: local}\nprofiles:\n  local:\n    base_url: http://localhost:9/v1\n    model: fake\n')
    steps = {"author": {"kind": "agent", "agent": "subagents/author.md", "schema": "result.json",
                        "next": "review", "max_attempts": 2, "max_visits": 2},
             "review": {"kind": "gate", "from": "author", "field": ["approved"],
                        "equals": True, "pass": "approval" if pause else "done",
                        "fail": "author" if repair else "rejected"},
             "done": {"kind": "finish"}, "rejected": {"kind": "finish", "outcome": "rejected"}}
    if pause:
        steps['approval'] = {"kind": "pause", "question": "Publish the note?", "choices": {"approve": "done", "reject": "rejected"}}
    path = tmp_path / 'flow.yml'
    path.write_text(yaml.safe_dump({"version": 1, "start": "author", "runtime": "runtime.yml",
        "source": ".prosaic", "limits": {"max_calls": max_calls, "timeout_s": 10}, "steps": steps}))
    monkeypatch.setattr('prosaic_harness.workflow.inspect_artifact', lambda *a, **k:
        ProsaicArtifact('author', 'subagent', {"model_tier": "fast"}, 'Return JSON for {{args}}'))
    return Workflow.load(path)


class FakeRuntime:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def run(self, artifact, arguments, **kwargs):
        self.calls.append((artifact, json.loads(arguments), kwargs['policy']))
        value = next(self.replies)
        if isinstance(value, BaseException):
            raise value
        return Result(0, value, '', token_usage=5, metadata={"model": "fake"})


def test_valid_result_checkpoint_and_resume_no_duplicate_call(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    runtime = FakeRuntime(['{"approved":true}'])
    h = Harness(flow, tmp_path / 'run', runtime=runtime)
    state = h.run({'task': 'draft'})
    assert state['status'] == 'completed' and state['outputs']['author'] == {'approved': True}
    assert state['calls'] == 1
    assert h.resume()['status'] == 'completed' and len(runtime.calls) == 1
    assert runtime.calls[0][2].allowed_tools == frozenset()


def test_schema_failure_feedback_and_bounded_retry(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    runtime = FakeRuntime(['{"approved":"yes"}', '{"approved":true}'])
    state = Harness(flow, tmp_path / 'run', runtime=runtime).run({'task': 'draft'})
    assert state['status'] == 'completed' and len(runtime.calls) == 2
    assert runtime.calls[1][1]['validation_feedback']
    assert len(list((tmp_path / 'run/attempts').glob('*.json'))) == 2


def test_review_loop_bounded_by_visits(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch, repair=True)
    state = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":false}'] * 3)).run({})
    assert state['status'] == 'blocked' and state['reason'] == 'visit_limit'
    assert state['calls'] == 2


def test_pause_requires_declared_choice(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch, pause=True)
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']))
    assert h.run({})['status'] == 'waiting'
    with pytest.raises(ValueError, match='choice'):
        h.resume(choice='maybe')
    assert h.resume(choice='approve')['status'] == 'completed'


def test_interrupted_request_needs_explicit_retry(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime([KeyboardInterrupt()]))
    with pytest.raises(KeyboardInterrupt):
        h.run({})
    h.runtime = FakeRuntime(['{"approved":true}'])
    assert h.resume()['reason'] == 'interrupted_call'
    assert not h.runtime.calls
    state = h.resume(retry_interrupted=True)
    assert state['status'] == 'completed' and state['calls'] == 2


def test_saved_receipt_is_adopted_after_state_write_failure(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch)
    runtime = FakeRuntime(['{"approved":true}'])
    h = Harness(flow, tmp_path / 'run', runtime=runtime)
    real = h._accept
    monkeypatch.setattr(h, '_accept', lambda *a: (_ for _ in ()).throw(OSError('simulated crash')))
    with pytest.raises(OSError):
        h.run({})
    monkeypatch.setattr(h, '_accept', real)
    assert h.resume()['status'] == 'completed' and len(runtime.calls) == 1


def test_whole_run_limit_blocks_retry(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch, max_calls=1)
    runtime = FakeRuntime(['not JSON'])
    state = Harness(flow, tmp_path / 'run', runtime=runtime).run({})
    assert state['reason'] == 'call_limit' and len(runtime.calls) == 1


def test_changed_definition_cannot_resume(tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch, pause=True)
    h = Harness(flow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']))
    h.run({})
    (tmp_path / 'result.json').write_text('{"type":"object"}')
    with pytest.raises(ValueError, match='changed'):
        Harness(Workflow.load(tmp_path / 'flow.yml'), tmp_path / 'run').resume()
