import hashlib
import json
import pytest
from prosaic_harness import Harness, Workflow
from test_harness import setup, FakeRuntime
from test_validation import edit_flow


def test_required_read_must_be_requested_by_prose(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    (tmp_path / 'source.md').write_text('evidence')
    config = tmp_path / 'runtime.yml'
    config.write_text(config.read_text() + 'allowed_tools: [read_file]\n')
    path = edit_flow(tmp_path, lambda d: (
        d.update(evidence=['source.md']),
        d['steps']['author'].update(tools=['read_file'], read_roots=['.'], require_reads=['source.md'])))
    with pytest.raises(ValueError, match='prose'):
        Workflow.load(path)


def test_missing_runtime_provenance_capability_fails_before_dispatch(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    from prosaic_runtime import ProsaicArtifact
    monkeypatch.setattr('prosaic_harness.workflow.inspect_artifact', lambda *a, **k:
        ProsaicArtifact('author', 'subagent', {'name': 'author', 'description': 'Synthetic author', 'model_tier': 'fast', 'tools': 'read'}, 'Return JSON'))
    (tmp_path / 'source.md').write_text('evidence')
    config = tmp_path / 'runtime.yml'
    config.write_text(config.read_text() + 'allowed_tools: [read_file]\n')
    flow = Workflow.load(edit_flow(tmp_path, lambda d: (
        d.update(evidence=['source.md']),
        d['steps']['author'].update(tools=['read_file'], read_roots=['.'], require_reads=['source.md']))))
    with pytest.raises(ValueError, match='read_receipts_v1'):
        Harness(flow, tmp_path / 'run', runtime=FakeRuntime([]))
    assert not (tmp_path / 'run/run.json').exists()


@pytest.mark.parametrize('path,content,offset,lines', [
    ('other.md', b'first\nsecond\n', 0, 2),
    ('source.md', b'old content', 0, 2),
    ('source.md', b'first\nsecond\n', 1, 1),
])
def test_wrong_file_changed_content_and_partial_read_do_not_count(tmp_path, monkeypatch, path, content, offset, lines):
    setup(tmp_path, monkeypatch)
    (tmp_path / 'source.md').write_bytes(b'first\nsecond\n')
    config = tmp_path / 'runtime.yml'
    config.write_text(config.read_text() + 'allowed_tools: [read_file]\n')
    def change(d):
        d['evidence'] = ['source.md']
        d['steps']['author'].update(tools=['read_file'], read_roots=['.'], require_reads=['source.md'])
    from prosaic_runtime import ProsaicArtifact
    monkeypatch.setattr('prosaic_harness.workflow.inspect_artifact', lambda *a, **k:
        ProsaicArtifact('author', 'subagent', {'name': 'author', 'description': 'Synthetic author', 'model_tier': 'fast', 'tools': 'read'}, 'Return JSON'))
    class Reading(FakeRuntime):
        capabilities = {'read_receipts_v1'}
        def run(self, *a, **kw):
            kw['on_event']({'event': 'tool_completed', 'name': 'read_file', 'status': 'ok',
                'read_receipts': [{'path': path, 'sha256': hashlib.sha256(content).hexdigest(),
                                   'offset': offset, 'lines_read': lines, 'line_count': 2}]})
            return super().run(*a, **kw)
    state = Harness(Workflow.load(edit_flow(tmp_path, change)), tmp_path / 'run',
                    runtime=Reading(['{"approved":true}'] * 2)).run({})
    assert state['reason'] == 'attempt_limit' and not state['outputs']
