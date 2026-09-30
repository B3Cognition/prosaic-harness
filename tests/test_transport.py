"""Real runtime and Prosaic boundary, with deterministic local HTTP replies."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Thread

import pytest
import yaml
from prosaic_harness import Harness, Workflow
from prosaic_runtime import ProsaicRuntime
from prosaic_harness.validation import load_validators

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


@pytest.fixture
def endpoint():
    requests, replies = [], []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            message = replies.pop(0)
            body = json.dumps({'choices': [{'message': message, 'finish_reason': 'tool_calls' if message.get('tool_calls') else 'stop'}],
                               'usage': {'total_tokens': 7}}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}/v1', requests, replies
    server.shutdown()
    server.server_close()
    thread.join()


def copy_blueprint(tmp_path, filename, url):
    if not shutil.which('prosaic'):
        pytest.skip('install the Prosaic CLI for inspection integration tests')
    shutil.copytree(EXAMPLES, tmp_path / 'examples')
    root = tmp_path / 'examples'
    config = yaml.safe_load((root / 'runtime.yml').read_text())
    config['profiles']['local'].update(base_url=url, model='test-model', features={'streaming': False})
    config['profiles']['local'].pop('api_key_env')
    (root / 'runtime.yml').write_text(yaml.safe_dump(config))
    return root / filename


def text(value):
    return {'content': json.dumps(value)}


def test_real_cli_single_from_other_directory(endpoint, tmp_path):
    url, requests, replies = endpoint
    flow = copy_blueprint(tmp_path, 'single.yml', url)
    replies.append(text({'summary': 'Pilot', 'facts': ['S2: 60 timeouts'], 'unknowns': ['Cause'],
                         'claims': [{'text': '60 timeouts', 'source_id': 'S2', 'quote': '60 timed out'}]}))
    result = subprocess.run([sys.executable, '-m', 'prosaic_harness.cli', 'run', str(flow),
        '--input', str(flow.parent / 'request.json'), '--run-dir', str(tmp_path / 'run'), '--events',
        '--checks', str(flow.parent / 'checks.py')],
        cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert rows[-1]['status'] == 'completed'
    assert requests[0]['model'] == 'test-model' and 'tools' not in requests[0]


def test_real_review_repair_inputs_and_pause(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = copy_blueprint(tmp_path, 'review.yml', url)
    config = yaml.safe_load((path.parent / 'tokenproxy.yml').read_text())
    for profile in config['profiles'].values():
        profile.update(base_url=url, features={'streaming': False})
        profile.pop('api_key_env')
    (path.parent / 'runtime.yml').write_text(yaml.safe_dump(config))
    claims = [{'text': '60 timeouts', 'source_id': 'S2', 'quote': '60 timed out'}]
    brief = {'summary': 'Pilot', 'facts': ['S2: 60 timeouts'], 'unknowns': ['Cause'], 'claims': claims}
    draft = {'recommendation': 'restricted_pilot', 'rationale': 'S2 limits confidence', 'conditions': ['Proposed: Confirm support'], 'citations': ['S2'], 'claims': claims, 'calculations': []}
    replies.extend([text(brief), text(draft), text({'approved': False, 'issues': ['Cite S9 support gap']}),
                    text(draft), text({'approved': True, 'issues': []}), text(draft), text({'approved': True, 'issues': []})])
    h = Harness(Workflow.load(path), tmp_path / 'run', validators=load_validators(path.parent / 'checks.py'))
    state = h.run(json.loads((path.parent / 'request.json').read_text()))
    assert state['status'] == 'waiting' and state['calls'] == 7
    # Original request and selected review travel through the real runtime prompt.
    prompt = json.dumps(requests[3]['messages'])
    assert 'Cite S9 support gap' in prompt and 'launch' in prompt
    assert h.resume(choice='reject')['status'] == 'rejected'
    assert len(requests) == 7
    assert [r['model'] for r in requests] == ['ornith-1.5-35b', 'qwen36-35b-a3b',
        'deepseek-v4-flash', 'qwen36-35b-a3b', 'deepseek-v4-flash', 'nemotron-3.5-lightning', 'deepseek-v4-flash']


def test_real_scoped_tool_and_receipt(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = copy_blueprint(tmp_path, 'read-only.yml', url)
    replies.extend([{'content': '', 'tool_calls': [{'id': 'call-1', 'type': 'function', 'function': {
        'name': 'read_file', 'arguments': '{"path":"evidence/pilot.md"}'}}]},
        text({'summary': 'Read pilot', 'facts': ['S1: 120 requests'], 'unknowns': ['S3: Cause'],
              'claims': [{'text': '120 requests', 'source_id': 'S1', 'quote': 'The pilot processed 120 requests on one endpoint.'}]})])
    state = Harness(Workflow.load(path), tmp_path / 'run', validators=load_validators(path.parent / 'checks.py')).run({'task': 'Read evidence/pilot.md'})
    assert state['status'] == 'completed'
    assert [t['function']['name'] for t in requests[0]['tools']] == ['read_file']
    tool_content = [m['content'] for m in requests[1]['messages'] if m['role'] == 'tool']
    assert any('120 requests' in content for content in tool_content)
    receipt = json.loads(next((tmp_path / 'run/attempts').glob('*.json')).read_text())
    assert any(e['event'] == 'tool_completed' and e['status'] == 'ok' for e in receipt['events'])


def test_required_tool_evidence_rejects_fabricated_read(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = copy_blueprint(tmp_path, 'read-only.yml', url)
    data = yaml.safe_load(path.read_text())
    data['steps']['evidence']['require_tools'] = ['read_file']
    path.write_text(yaml.safe_dump(data))
    fake = {'summary': 'Claimed read', 'facts': ['S1: claimed result'], 'unknowns': ['Cause'],
            'claims': [{'text': 'Claimed', 'source_id': 'S1', 'quote': 'The pilot processed 120 requests on one endpoint.'}]}
    replies.extend([text(fake), text(fake)])
    state = Harness(Workflow.load(path), tmp_path / 'run', validators=load_validators(path.parent / 'checks.py')).run({'task': 'Read evidence/pilot.md'})
    assert state['status'] == 'blocked' and state['reason'] == 'attempt_limit'
    assert 'read_file' in state['feedback']
