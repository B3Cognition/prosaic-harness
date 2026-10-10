"""Independent native workers reconstruct admission and adopt durable receipts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from test_transport import endpoint


SOURCE = Path(__file__).resolve().parents[1] / 'src'

# This is trusted host code, identical in both fresh processes. Only host process
# arguments/environment supply the storage address and synthetic endpoint; the
# proposal contains logical aliases. -I ignores parent PYTHONPATH and cwd, while
# the explicit source argument selects the candidate Harness under test.
WORKER = r'''
import json, os, shutil, sys
from pathlib import Path

assert sys.flags.isolated == 1
sys.path.insert(0, sys.argv[1])
import prosaic, prosaic_runtime, prosaic_harness
from prosaic_runtime import CustomTool, EndpointConfig, ProsaicArtifact, RuntimeConfig
from prosaic_harness import (FileRunStore, Harness, WorkflowBindings,
                            WorkflowCatalog, WorkflowFactory, WorkflowPolicy)

assert 'site-packages' in Path(prosaic.__file__).resolve().parts
assert 'site-packages' in Path(prosaic_runtime.__file__).resolve().parts
assert Path(prosaic_harness.__file__).resolve().is_relative_to(Path(sys.argv[1]))
assert shutil.which('node') is None and shutil.which('prosaic') is None
phase, storage_root, run_id = sys.argv[2:5]
endpoint_url = os.environ['PROSAIC_TEST_WORKER_ENDPOINT']
tool_calls = []

def lookup(arguments):
    tool_calls.append(arguments)
    return {'entity_id': 'sample-1'}

agent = ProsaicArtifact('subagents/finder.md', 'subagent', {
    'name': 'finder', 'description': 'Find a synthetic entity',
    'tools': ['lookup_item'], 'model_tier': 'fast',
}, 'ALWAYS use lookup_item before returning one JSON object.\n'
   'NEVER invent entity identifiers or include prose outside JSON.')
entity_schema = {
    'type': 'object', 'properties': {'entity_id': {'type': 'string', 'maxLength': 64}},
    'required': ['entity_id'], 'additionalProperties': False,
}
tool = CustomTool('lookup_item', 'Find a synthetic entity', {
    'type': 'object', 'properties': {'query': {'type': 'string'}},
    'required': ['query'], 'additionalProperties': False,
}, lookup, 'v1')
config = RuntimeConfig({'local': EndpointConfig(endpoint_url, 'synthetic-model',
    features={'streaming': False})}, {'fast': 'local'}, 'local',
    allowed_tools=frozenset({'lookup_item'}))
factory = WorkflowFactory(
    catalog=WorkflowCatalog(agents={'finder': agent}, schemas={
        'entity': entity_schema, 'confirmation': entity_schema,
    }),
    bindings=WorkflowBindings(config=config, custom_tools={'lookup_item': tool}),
    policy=WorkflowPolicy(allowed_agents=frozenset({'finder'}),
        allowed_schemas=frozenset({'entity', 'confirmation'}),
        allowed_tools=frozenset({'lookup_item'}), allowed_model_tiers=frozenset({'fast'}),
        max_calls=2, max_tokens=128, max_run_s=60),
)
definition = {'version': 1, 'name': 'worker-selection', 'start': 'find', 'steps': {
    'find': {'kind': 'agent', 'agent': 'finder', 'schema': 'entity',
        'tools': ['lookup_item'], 'require_tools': ['lookup_item'], 'next': 'review'},
    'review': {'kind': 'pause', 'question': 'Confirm the displayed entity?',
        'choices': {'accept': 'done', 'reject': 'rejected'}, 'requires': ['find'],
        'response_schema': 'confirmation'},
    'done': {'kind': 'finish', 'requires': ['find']},
    'rejected': {'kind': 'finish', 'outcome': 'rejected'},
}}
serialized_definition = json.dumps(definition)
assert endpoint_url not in serialized_definition and storage_root not in serialized_definition
assert sys.argv[1] not in serialized_definition
workflow = (factory.build(definition) if phase == 'run' else
            factory.build_json(json.dumps({'definition': definition})))
assert workflow.path is None
store = FileRunStore(Path(storage_root), namespace='workers')
harness = Harness(workflow, store=store, run_id=run_id)
assert type(harness.runtime) is prosaic_runtime.ProsaicRuntime
revision_required = invalid_response_rejected = False
if phase == 'run':
    state = harness.run({'query': 'sample'})
    assert state['status'] == 'waiting'
else:
    before = harness.status()
    assert before.state['status'] == 'waiting'
    assert harness.status().revision == before.revision
    try:
        harness.resume(choice='accept', response={'entity_id': 'sample-1'})
    except ValueError as error:
        assert 'expected_revision' in str(error)
        revision_required = True
    else:
        raise AssertionError('store-backed human choice did not require a revision')
    try:
        harness.resume(choice='accept', response={'entity_id': 7}, expected_revision=before.revision)
    except ValueError:
        invalid_response_rejected = True
    else:
        raise AssertionError('response schema accepted a numeric entity identifier')
    assert harness.status().revision == before.revision
    state = harness.resume(choice='accept', response={'entity_id': 'sample-1'},
                           expected_revision=before.revision)
    assert state['status'] == 'completed'
    assert harness.resume()['status'] == 'completed'
snapshot = harness.status()
assert snapshot.state == state
assert state['calls'] == 1 and state['pending'] is None
assert state['outputs'] == {'find': {'entity_id': 'sample-1'}}
invocation = state['invocations'][0]
assert invocation['status'] == 'complete' and invocation['token_usage'] == 14
receipt = store.load_receipt(run_id, invocation['id'])
assert receipt['version'] == 1 and state['version'] == 2
assert receipt['sha256'] == invocation['receipt_sha256']
assert 'prosaic-workflow-' not in json.dumps([state, receipt])
print(json.dumps({'pid': os.getpid(), 'status': state['status'],
    'fingerprint': workflow.fingerprint, 'state_fingerprint': state['fingerprint'],
    'revision': snapshot.revision, 'invocation_id': invocation['id'],
    'receipt_sha256': receipt['sha256'], 'checkpoint_version': state['version'],
    'receipt_version': receipt['version'], 'tool_calls': tool_calls,
    'revision_required': revision_required, 'invalid_response_rejected': invalid_response_rejected}))
store.close()
'''


def worker(phase, url, storage, run_id, cwd):
    environment = {**os.environ, 'PATH': '', 'PROSAIC_TEST_WORKER_ENDPOINT': url,
                   'PYTHONPATH': str(cwd / 'ignored-pythonpath')}
    process = subprocess.run([sys.executable, '-I', '-c', WORKER, str(SOURCE),
                              phase, str(storage), run_id],
                             cwd=cwd, env=environment, capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, (phase, process.stdout, process.stderr)
    return json.loads(process.stdout)


def test_fresh_native_worker_reconstructs_pause_and_resumes_without_inference(endpoint, tmp_path):
    url, requests, replies = endpoint
    replies.extend([
        {'content': '', 'tool_calls': [{'id': 'lookup-1', 'type': 'function', 'function': {
            'name': 'lookup_item', 'arguments': '{"query":"sample"}'}}]},
        {'content': '{"entity_id":"sample-1"}'},
    ])
    consumer = tmp_path / 'consumer'
    consumer.mkdir()
    storage, run_id = tmp_path / 'storage', uuid.uuid4().hex
    first = worker('run', url, storage, run_id, consumer)
    assert first['status'] == 'waiting' and first['tool_calls'] == [{'query': 'sample'}]
    assert len(requests) == 2 and replies == []
    assert requests[0]['model'] == 'synthetic-model'
    assert [tool['function']['name'] for tool in requests[0]['tools']] == ['lookup_item']
    assert 'sample-1' in json.dumps(requests[1]['messages'])
    directory = storage / 'workers' / run_id
    checkpoint = json.loads((directory / 'run.json').read_text())
    assert checkpoint['status'] == 'waiting' and checkpoint['version'] == 2
    assert not any(event['event'] == 'human_decision' for event in checkpoint['history'])
    receipt_path = directory / 'attempts' / (first['invocation_id'] + '.json')
    receipt_bytes = receipt_path.read_bytes()

    second = worker('resume', url, storage, run_id, consumer)
    assert second['pid'] != first['pid'] and first['pid'] != os.getpid()
    assert second['status'] == 'completed' and second['tool_calls'] == []
    assert second['revision_required'] and second['invalid_response_rejected']
    assert first['fingerprint'] == second['fingerprint'] == second['state_fingerprint']
    assert first['state_fingerprint'] == first['fingerprint']
    assert first['invocation_id'] == second['invocation_id']
    assert first['receipt_sha256'] == second['receipt_sha256']
    assert second['checkpoint_version'] == 2 and second['receipt_version'] == 1
    assert second['revision'] != first['revision']
    assert receipt_path.read_bytes() == receipt_bytes
    assert len(requests) == 2 and replies == [], 'fresh resume made another provider request'
    final = json.loads((directory / 'run.json').read_text())
    decisions = [event for event in final['history'] if event['event'] == 'human_decision']
    assert [(event['choice'], event['response']) for event in decisions] == [
        ('accept', {'entity_id': 'sample-1'})]
