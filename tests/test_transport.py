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
            usage = message.pop('_usage', {'total_tokens': 7})
            body = json.dumps({'choices': [{'message': message, 'finish_reason': 'tool_calls' if message.get('tool_calls') else 'stop'}],
                               'usage': usage}).encode()
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
    # This tests successful-tool admission under automatic choice, separately
    # from Runtime's explicit initial-tool selection contract.
    data['steps']['evidence'].pop('require_reads')
    path.write_text(yaml.safe_dump(data))
    fake = {'summary': 'Claimed read', 'facts': ['S1: claimed result'], 'unknowns': ['Cause'],
            'claims': [{'text': 'Claimed', 'source_id': 'S1', 'quote': 'The pilot processed 120 requests on one endpoint.'}]}
    replies.extend([text(fake), text(fake)])
    state = Harness(Workflow.load(path), tmp_path / 'run', validators=load_validators(path.parent / 'checks.py')).run({'task': 'Read evidence/pilot.md'})
    assert state['status'] == 'blocked' and state['reason'] == 'attempt_limit'
    assert 'read_file' in state['feedback']


def staged_blueprint(tmp_path, url):
    path = copy_blueprint(tmp_path, 'read-only.yml', url)
    acquisition = path.parent / '.prosaic/subagents/acquisition.md'
    acquisition.write_text('---\nname: acquisition\ndescription: Acquire scoped evidence\nexecution: agent\ntools: read\n---\nRead evidence/pilot.md with read_file.\n')
    data = yaml.safe_load(path.read_text())
    data['steps']['evidence']['acquisition'] = 'subagents/acquisition.md'
    path.write_text(yaml.safe_dump(data))
    return path


@pytest.mark.skipif('acquisition_v1' not in ProsaicRuntime.capabilities, reason='staged integration requires development Runtime acquisition_v1')
def test_staged_step_discloses_final_contract_only_after_receipted_read(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = staged_blueprint(tmp_path, url)
    replies.extend([{'content': '', 'tool_calls': [{'id': 'r', 'type': 'function', 'function': {
        'name': 'read_file', 'arguments': '{"path":"evidence/pilot.md"}'}}]},
        text({'summary': 'Read pilot', 'facts': ['S1: 120 requests'], 'unknowns': ['S3: Cause'],
              'claims': [{'text': '120 requests', 'source_id': 'S1', 'quote': 'The pilot processed 120 requests on one endpoint.'}]})])
    state = Harness(Workflow.load(path), tmp_path / 'run', validators=load_validators(path.parent / 'checks.py')).run({'task': 'FINAL REQUEST'})
    assert state['status'] == 'completed' and state['calls'] == 1
    assert 'FINAL REQUEST' not in json.dumps(requests[0]) and 'claims' not in json.dumps(requests[0]['messages'])
    assert 'FINAL REQUEST' in requests[1]['messages'][-1]['content']
    receipt = json.loads(next((tmp_path / 'run/attempts').glob('*.json')).read_text())
    assert receipt['result']['metadata']['acquisition_sha256']
    assert any(e['event'] == 'acquisition_completed' for e in receipt['events'])


@pytest.mark.skipif('acquisition_v1' not in ProsaicRuntime.capabilities, reason='staged integration requires development Runtime acquisition_v1')
def test_failed_staged_read_is_durable_block_without_repair(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = staged_blueprint(tmp_path, url)
    replies.append({'content': '', 'tool_calls': [{'id': 'r', 'type': 'function', 'function': {
        'name': 'read_file', 'arguments': '{"path":"outside.md"}'}}]})
    h = Harness(Workflow.load(path), tmp_path / 'run', validators=load_validators(path.parent / 'checks.py'))
    state = h.run({'task': 'Read pilot'})
    assert state['status'] == 'blocked' and state['reason'] == 'acquisition_failed'
    assert state['calls'] == 1 and state['outputs'] == {} and len(requests) == 1
    assert h.resume()['reason'] == 'acquisition_failed' and len(requests) == 1


def test_acquisition_is_part_of_workflow_fingerprint(endpoint, tmp_path):
    from dataclasses import replace
    url, _, _ = endpoint
    flow = Workflow.load(staged_blueprint(tmp_path, url))
    flow.acquisitions['evidence'] = replace(flow.acquisitions['evidence'], body='Different acquisition')
    assert flow.current_fingerprint() != flow.fingerprint


def test_acquisition_requires_capable_runtime_before_run(endpoint, tmp_path):
    url, requests, _ = endpoint
    flow = Workflow.load(staged_blueprint(tmp_path, url))
    class LegacyRuntime:
        capabilities = {'read_receipts_v1', 'initial_tool_v1'}
    with pytest.raises(ValueError, match='acquisition_v1'):
        Harness(flow, tmp_path / 'run', runtime=LegacyRuntime(), validators=load_validators(flow.path.parent / 'checks.py'))
    assert requests == [] and not (tmp_path / 'run').exists()


def test_acquisition_needs_required_reads_at_workflow_load(endpoint, tmp_path):
    url, _, _ = endpoint
    path = staged_blueprint(tmp_path, url)
    data = yaml.safe_load(path.read_text())
    data['steps']['evidence'].pop('require_reads')
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match='acquisition.*require_reads'):
        Workflow.load(path)


@pytest.mark.parametrize('filename,staged', [('staged-read.yml', True), ('preloaded-evidence.yml', False)])
def test_evidence_blueprints_use_declared_acquisition_path(endpoint, tmp_path, filename, staged):
    if staged and 'acquisition_v1' not in ProsaicRuntime.capabilities:
        pytest.skip('staged integration requires development Runtime acquisition_v1')
    url, requests, replies = endpoint
    path = copy_blueprint(tmp_path, filename, url)
    if staged:
        replies.append({'content': '', 'tool_calls': [{'id': 'r', 'type': 'function', 'function': {
            'name': 'read_file', 'arguments': '{"path":"evidence/pilot.md"}'}}]})
    replies.append(text({'summary': 'Pilot', 'facts': ['S1: 120 requests'], 'unknowns': ['S3: Cause'],
                         'claims': [{'text': '120 requests', 'source_id': 'S1', 'quote': 'The pilot processed 120 requests on one endpoint.'}]}))
    state = Harness(Workflow.load(path), tmp_path / 'run', validators=load_validators(path.parent / 'checks.py')).run({'task': 'Summarize evidence'})
    assert state['status'] == 'completed'
    receipt = json.loads(next((tmp_path / 'run/attempts').glob('*.json')).read_text())
    if staged:
        assert len(requests) == 2 and 'The pilot processed 120' not in json.dumps(requests[0])
        assert any(e['event'] == 'tool_completed' for e in receipt['events'])
    else:
        assert len(requests) == 1 and 'tools' not in requests[0]
        assert 'The pilot processed 120' in requests[0]['messages'][0]['content']
        assert not any(e['event'] == 'tool_completed' for e in receipt['events'])
        assert receipt['arguments']['sources']['evidence/pilot.md']['text'].startswith('# Fictional pilot evidence')


@pytest.mark.skipif('acquisition_v1' not in ProsaicRuntime.capabilities, reason='staged integration requires development Runtime acquisition_v1')
def test_evidence_matrix_runs_both_paths_through_real_runtime(endpoint, tmp_path):
    url, requests, replies = endpoint
    flow = copy_blueprint(tmp_path, 'staged-read.yml', url)
    brief = {'summary': 'Pilot', 'facts': ['S1: 120 requests'], 'unknowns': ['S3: Cause'],
             'claims': [{'text': '120 requests', 'source_id': 'S1', 'quote': 'The pilot processed 120 requests on one endpoint.'}]}
    replies.extend([{'content': '', 'tool_calls': [{'id': 'r', 'type': 'function', 'function': {
        'name': 'read_file', 'arguments': '{"path":"evidence/pilot.md"}'}}]}, text(brief), text(brief)])
    # One profile, one stream setting; the script tests staged then preloaded.
    result = subprocess.run([sys.executable, str(flow.parent / 'evaluate_evidence.py'), '--live',
        '--config', str(flow.parent / 'runtime.yml'), '--streaming', 'off', '--run-dir', str(tmp_path / 'matrix')],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == 2 and all(row['status'] == 'completed' for row in rows)
    assert [row['mode'] for row in rows] == ['staged', 'preloaded'] and len(requests) == 3


def test_evidence_matrix_preflights_capability_before_any_model_request(endpoint, tmp_path, monkeypatch):
    import importlib.util
    url, requests, replies = endpoint
    flow = copy_blueprint(tmp_path, 'staged-read.yml', url)
    replies.append(text({'summary': 'unused'}))
    spec = importlib.util.spec_from_file_location('evidence_matrix', flow.parent / 'evaluate_evidence.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(ProsaicRuntime, 'capabilities', frozenset({'read_receipts_v1'}))
    monkeypatch.setattr(sys, 'argv', ['evaluate_evidence.py', '--live', '--config', str(flow.parent / 'runtime.yml'),
                                    '--run-dir', str(tmp_path / 'matrix')])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2 and requests == []


@pytest.mark.skipif('acquisition_v1' not in ProsaicRuntime.capabilities, reason='usage integrity test requires development Runtime')
def test_real_unknown_usage_blocks_finite_token_budget(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = copy_blueprint(tmp_path, 'preloaded-evidence.yml', url)
    data = yaml.safe_load(path.read_text())
    data['limits']['max_tokens'] = 100
    path.write_text(yaml.safe_dump(data))
    replies.append({**text({'summary': 'Pilot', 'facts': ['S1: 120 requests'], 'unknowns': ['S3: Cause'],
        'claims': [{'text': '120 requests', 'source_id': 'S1', 'quote': 'The pilot processed 120 requests on one endpoint.'}]}), '_usage': None})
    h = Harness(Workflow.load(path), tmp_path / 'run', validators=load_validators(path.parent / 'checks.py'))
    state = h.run({'task': 'Summarize'})
    assert state['status'] == 'blocked' and state['reason'] == 'usage_unknown'
    assert state['outputs'] == {} and len(requests) == 1
    assert h.resume()['reason'] == 'usage_unknown' and len(requests) == 1


def test_real_runtime_accounting_context_and_receipt(endpoint, tmp_path):
    from prosaic_runtime.accounting import ExecutionContext, MemoryRecorder
    url, requests, replies = endpoint
    path = copy_blueprint(tmp_path, 'single.yml', url)
    replies.append(text({'summary': 'Pilot', 'facts': ['S2: 60 timeouts'], 'unknowns': ['Cause'],
                         'claims': [{'text': '60 timeouts', 'source_id': 'S2', 'quote': '60 timed out'}]}))
    recorder = MemoryRecorder(defaults=ExecutionContext(tenant_id='trusted-tenant'))
    h = Harness(Workflow.load(path), tmp_path / 'run', accounting=recorder,
                validators=load_validators(path.parent / 'checks.py'))
    state = h.run(json.loads((path.parent / 'request.json').read_text()))
    assert state['status'] == 'completed'
    assert len(recorder.intents) == len(recorder.observations) == len(requests) == 1
    assert 'trusted-tenant' not in json.dumps(requests)
    receipt = json.loads(next((tmp_path / 'run/attempts').glob('*.json')).read_text())
    context = receipt['result']['metadata']['accounting_v1']['context']
    assert context['tenant_id'] == 'trusted-tenant'
    assert context['invocation_id'] == state['invocations'][0]['id']
    assert h.resume()['status'] == 'completed'
    assert len(requests) == 1


def test_cli_optional_context_flags(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = copy_blueprint(tmp_path, 'single.yml', url)
    replies.append(text({'summary': 'Pilot', 'facts': ['S2: 60 timeouts'], 'unknowns': ['Cause'],
                         'claims': [{'text': '60 timeouts', 'source_id': 'S2', 'quote': '60 timed out'}]}))
    result = subprocess.run([sys.executable, '-m', 'prosaic_harness.cli', 'run', str(path),
        '--input', str(path.parent / 'request.json'), '--run-dir', str(tmp_path / 'run'), '--events',
        '--tenant-id', 'cli-tenant', '--checks', str(path.parent / 'checks.py')],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    state = json.loads((tmp_path / 'run/run.json').read_text())
    assert state['accounting_context']['tenant_id'] == 'cli-tenant'
    assert 'cli-tenant' not in json.dumps(requests)
