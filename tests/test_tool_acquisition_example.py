"""Runnable problem/resolution pair: fail closed or acquire before analysis."""
import hashlib
import json

from prosaic_harness import Harness, Workflow
from prosaic_harness.validation import load_validators
from test_transport import endpoint, copy_blueprint, text


def test_direct_answer_without_native_read_is_blocked(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = copy_blueprint(tmp_path, 'read-only.yml', url)
    replies.append(text({'summary': 'The file has not been read', 'facts': [],
                         'unknowns': ['File contents'], 'claims': []}))
    run = tmp_path / 'run'
    state = Harness(Workflow.load(path), run,
                    validators=load_validators(path.parent / 'checks.py')).run({'task': 'Read the pilot'})
    assert state['status'] == 'blocked'
    assert state['reason'] == 'tool_choice_not_honored'
    assert state['outputs'] == {} and state['calls'] == 1
    assert len(requests) == 1
    assert requests[0]['tool_choice']['function']['name'] == 'read_file'
    receipt = json.loads(next((run / 'attempts').glob('*.json')).read_text())
    assert not any(event['event'] == 'tool_completed' for event in receipt['events'])


def test_staged_read_withholds_contract_then_verifies_full_receipt(endpoint, tmp_path):
    url, requests, replies = endpoint
    path = copy_blueprint(tmp_path, 'staged-read.yml', url)
    replies.extend([{'content': '', 'tool_calls': [{'id': 'read-1', 'type': 'function',
        'function': {'name': 'read_file', 'arguments': '{"path":"evidence/pilot.md"}'}}]},
        text({'summary': 'Read pilot', 'facts': ['120 requests'], 'unknowns': ['Cause'],
              'claims': [{'text': '120 requests', 'source_id': 'S1',
                          'quote': 'The pilot processed 120 requests on one endpoint.'}]})])
    run = tmp_path / 'run'
    state = Harness(Workflow.load(path), run,
        validators=load_validators(path.parent / 'checks.py')).run({'task': 'UNIQUE_FINAL_REQUEST'})
    assert state['status'] == 'completed' and state['calls'] == 1
    assert len(requests) == 2
    first = json.dumps(requests[0]['messages'])
    assert 'UNIQUE_FINAL_REQUEST' not in first and 'Also return claims' not in first
    assert 'Call read_file' in first
    messages = requests[1]['messages']
    tool_index = next(i for i, message in enumerate(messages) if message['role'] == 'tool')
    final_index = next(i for i, message in enumerate(messages)
                       if 'UNIQUE_FINAL_REQUEST' in (message.get('content') or ''))
    assert tool_index < final_index
    assert 'Also return claims' in messages[final_index]['content']
    receipt = json.loads(next((run / 'attempts').glob('*.json')).read_text())
    events = receipt['events']
    read_index = next(i for i, event in enumerate(events)
                      if event['event'] == 'tool_completed' and event['status'] == 'ok')
    acquired_index = next(i for i, event in enumerate(events) if event['event'] == 'acquisition_completed')
    assert read_index < acquired_index
    evidence = (path.parent / 'evidence/pilot.md').read_bytes()
    read = events[read_index]['read_receipts'][0]
    assert read['path'] == 'evidence/pilot.md'
    assert read['sha256'] == hashlib.sha256(evidence).hexdigest()
    assert read['offset'] == 0
    assert read['lines_read'] == read['line_count'] == len(evidence.decode().splitlines())
