"""Exercise incident blueprints through Prosaic, real tools and admission."""
import json
import subprocess
import sys
import pytest
import yaml
from prosaic_harness import Harness, Workflow
from prosaic_harness.validation import load_validators
from prosaic_runtime import ProsaicRuntime
from test_transport import endpoint, copy_blueprint, text


def read(*names):
    return {'content': '', 'tool_calls': [{'id': f'r-{i}', 'type': 'function', 'function': {
        'name': 'read_file', 'arguments': json.dumps({'path': f'evidence/incident/{name}.md'})}}
        for i, name in enumerate(names)]}


BRIEF = {'summary': 'A delivery incident; no proven root cause.',
         'facts': ['S103: 84 attempts failed at the client'], 'unknowns': ['S109: No root cause established'],
         'claims': [{'text': '84 client-visible failures', 'source_id': 'S103',
                     'quote': 'Client-visible failures totaled 84 of 2,400 request attempts.'}]}


@pytest.mark.parametrize('staged', [False, True])
@pytest.mark.parametrize('repair', [False, True])
def test_incident_review_repair_and_human_choice(endpoint, tmp_path, staged, repair):
    if staged and 'acquisition_v1' not in ProsaicRuntime.capabilities:
        pytest.skip('development Runtime acquisition_v1 required')
    url, requests, replies = endpoint
    path = copy_blueprint(tmp_path, 'incident-staged-review.yml' if staged else 'incident-preloaded-review.yml', url)
    if staged:
        for name, source, quote in [('timeline', 'S101', 'The observation window ran from 09:00 to 09:30 UTC on one test endpoint.'),
            ('metrics', 'S103', 'Client-visible failures totaled 84 of 2,400 request attempts.'),
            ('notes', 'S109', 'No root cause was established for the client timeouts or explicit errors.')]:
            replies.extend([read(name), text({'summary': name, 'facts': [source + ': Observed'], 'unknowns': ['Cause unknown'],
                'claims': [{'text': quote, 'source_id': source, 'quote': quote}]})])
    for attempt in range(2 if repair else 1):
        replies.append(text(BRIEF))
        replies.append(text({'approved': False, 'issues': ['Keep the root cause unknown.']} if repair and attempt == 0
                            else {'approved': True, 'issues': []}))
    h = Harness(Workflow.load(path), tmp_path / 'run', validators=load_validators(path.parent / 'checks.py'))
    state = h.run({'task': 'Review this fictional incident; do not publish anything.'})
    assert state['status'] == 'waiting' and state['calls'] == (3 if staged else 0) + (4 if repair else 2)
    assert len(requests) == (6 if staged else 0) + (4 if repair else 2)
    if repair:
        assert 'Keep the root cause unknown' in json.dumps(requests[8 if staged else 2]['messages'])
        last_review = [r for r in requests if 'Independently review' in json.dumps(r['messages'])][-1]
        assert 'artifact_bindings' in json.dumps(last_review['messages'])
    before = len(requests)
    assert h.resume(choice='reject')['status'] == 'rejected'
    assert len(requests) == before
    receipts = [json.loads(p.read_text()) for p in (tmp_path / 'run/attempts').glob('*.json')]
    reads = [e for receipt in receipts for e in receipt['events'] if e['event'] == 'tool_completed']
    assert len(reads) == 3 if staged else reads == []


def test_incident_evidence_change_prevents_human_approval(endpoint, tmp_path):
    url, _, replies = endpoint
    path = copy_blueprint(tmp_path, 'incident-preloaded-review.yml', url)
    replies.extend([text(BRIEF), text({'approved': True, 'issues': []})])
    h = Harness(Workflow.load(path), tmp_path / 'run', validators=load_validators(path.parent / 'checks.py'))
    assert h.run({})['status'] == 'waiting'
    (path.parent / 'evidence/incident/notes.md').write_text('changed evidence')
    with pytest.raises(ValueError, match='evidence changed'):
        h.resume(choice='approve')


def test_python_embedding_config_override_preserves_resume_binding(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = copy_blueprint(tmp_path, 'incident-preloaded-review.yml', url)
    replies.extend([text(BRIEF), text({'approved': True, 'issues': []})])
    command = [sys.executable, str(path.parent / 'run_workflow.py'), str(path), '--config', str(path.parent / 'runtime.yml'),
               '--checks', str(path.parent / 'checks.py'), '--run-dir', str(tmp_path / 'run')]
    first = subprocess.run([*command, '--input', str(path.parent / 'read-request.json')], capture_output=True, text=True, timeout=30)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)['status'] == 'waiting'
    resumed = subprocess.run([*command, '--resume', '--choice', 'reject'], capture_output=True, text=True, timeout=30)
    assert resumed.returncode == 1, resumed.stderr  # Explicitly rejected outcome, not an execution error.
    assert json.loads(resumed.stdout)['status'] == 'rejected' and len(requests) == 2
