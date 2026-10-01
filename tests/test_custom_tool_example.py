import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Thread
import pytest
import yaml

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'
RECORD = {'sku': 'SKU-001', 'name': 'Demo Widget', 'price_cents': 1250, 'currency': 'USD'}


@pytest.fixture
def catalog_endpoint():
    requests, replies = [], []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            message = replies.pop(0)
            finish = 'tool_calls' if message.get('tool_calls') else 'stop'
            if request.get('stream'):
                delta = {**message, 'tool_calls': [dict(c, index=i) for i, c in enumerate(message.get('tool_calls', []))]}
                parts = [{'choices': [{'delta': delta, 'finish_reason': finish}]}, {'choices': [], 'usage': {'total_tokens': 7}}]
                body = (''.join('data: ' + json.dumps(p) + '\n\n' for p in parts) + 'data: [DONE]\n\n').encode()
                content_type = 'text/event-stream'
            else:
                body = json.dumps({'choices': [{'message': message, 'finish_reason': finish}], 'usage': {'total_tokens': 7}}).encode()
                content_type = 'application/json'
            self.send_response(200); self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests, replies
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def lookup():
    return {'content': '', 'tool_calls': [{'id': 'lookup', 'type': 'function', 'function': {
        'name': 'lookup_catalog', 'arguments': '{"sku":"SKU-001"}'}}]}


def invoke(url, tmp_path, *args, streaming=False):
    if not shutil.which('prosaic'):
        pytest.skip('install Prosaic CLI for example tests')
    config = tmp_path / 'runtime.yml'
    config.write_text(yaml.safe_dump({'default_profile': 'local', 'routes': {'fast': 'local'},
        'allowed_tools': ['lookup_catalog'], 'profiles': {'local': {
            'base_url': url, 'model': 'test', 'features': {'streaming': streaming}}}}))
    return subprocess.run([sys.executable, str(EXAMPLES / 'run_custom_tool.py'), '--config', str(config),
        '--run-dir', str(tmp_path / 'run'), *args], cwd=tmp_path, capture_output=True, text=True, timeout=20)


@pytest.mark.parametrize('streaming', [False, True])
def test_shipped_program_waits_and_resumes_reject(catalog_endpoint, tmp_path, streaming):
    url, requests, replies = catalog_endpoint
    replies.extend([lookup(), {'content': json.dumps({'found': True, 'item': RECORD})}])
    result = invoke(url, tmp_path, '--live', streaming=streaming)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'waiting'
    receipt = json.loads(next((tmp_path / 'run/attempts').glob('*.json')).read_text())
    assert any(e.get('tool_version', '').startswith('catalog-') and e.get('status') == 'ok' for e in receipt['events'])
    result = invoke(url, tmp_path, '--live', '--resume', '--choice', 'reject', streaming=streaming)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'rejected' and len(requests) == 2


def test_fabricated_record_rejected_boundedly(catalog_endpoint, tmp_path):
    url, requests, replies = catalog_endpoint
    for _ in range(2):
        replies.extend([lookup(), {'content': json.dumps({'found': True, 'item': {**RECORD, 'price_cents': 1}})}])
    result = invoke(url, tmp_path, '--live')
    assert result.returncode == 1, result.stderr
    output = json.loads(result.stdout)
    assert output['status'] == 'blocked' and output['reason'] == 'attempt_limit'
    assert output['outputs'] == {} and len(requests) == 4


def test_no_live_no_requests(catalog_endpoint, tmp_path):
    url, requests, replies = catalog_endpoint
    result = invoke(url, tmp_path)
    assert result.returncode != 0 and '--live is required' in result.stderr
    assert requests == []


def test_self_contained_matching_catalogue_contract():
    spec = importlib.util.spec_from_file_location('harness_catalog', EXAMPLES / 'catalog_tools.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    tool = module.make_tools()['lookup_catalog']
    assert tool.handler({'sku': 'SKU-001'}) == {'found': True, 'item': RECORD}
    assert tool.parameters == {'type': 'object', 'required': ['sku'], 'properties': {
        'sku': {'type': 'string', 'pattern': '^SKU-[0-9]{3}$'}}, 'additionalProperties': False}
    assert tool.descriptor == {'name': 'lookup_catalog', 'description': 'Look up a synthetic catalogue item.',
        'parameters': {'type': 'object', 'required': ['sku'], 'properties': {
            'sku': {'type': 'string', 'pattern': '^SKU-[0-9]{3}$'}}, 'additionalProperties': False},
        'version': 'catalog-03584de4ade271921ab8742822edcffd2d4d99300e24798507aa21dcc0d208f6',
        'max_argument_bytes': 16384, 'max_result_bytes': 65536, 'authorization_required': False}
