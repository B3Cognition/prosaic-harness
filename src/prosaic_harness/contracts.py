"""Admission for controller-owned checkpoints and invocation receipts."""
import re
from jsonschema import Draft202012Validator
from .store import parse_json
from .workflow import digest

IDENTIFIER = re.compile(r'^[0-9a-f]{32}$')
HASH = re.compile(r'^[0-9a-f]{64}$')


def seal(value):
    value = dict(value)
    value.pop('sha256', None)
    return {**value, 'sha256': digest(value)}


def verify_seal(value):
    if not isinstance(value, dict) or value.get('sha256') != seal(value)['sha256']:
        raise ValueError('checkpoint/receipt digest mismatch')


def output_json(text):
    if not isinstance(text, str) or len(text.encode()) > 100_000:
        raise ValueError('response exceeds JSON size limit')
    text = text.strip()
    match = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', text, re.S)
    return parse_json(match[1] if match else text)


def validate_receipt(receipt, state, pending):
    verify_seal(receipt)
    required = {'version', 'run_id', 'id', 'step', 'arguments_sha256', 'arguments', 'result', 'events', 'sha256'}
    if set(receipt) != required or receipt['version'] != 1:
        raise ValueError('invalid invocation receipt schema')
    if (receipt['run_id'] != state['run_id'] or receipt['id'] != pending['id']
            or receipt['step'] != pending['step'] or receipt['arguments_sha256'] != pending['arguments_sha256']
            or digest(receipt['arguments']) != pending['arguments_sha256']):
        raise ValueError('receipt does not match pending invocation')
    result = receipt['result']
    if (not isinstance(result, dict) or set(result) != {'exit_code', 'stdout', 'stderr', 'token_usage', 'cost_usd', 'timed_out', 'metadata'}
            or type(result['exit_code']) is not int or type(result['timed_out']) is not bool
            or not isinstance(result['stdout'], str) or not isinstance(result['stderr'], str)
            or not isinstance(result['metadata'], dict)
            or (result['token_usage'] is not None and (type(result['token_usage']) is not int or result['token_usage'] < 0))
            or not isinstance(receipt['events'], list) or len(receipt['events']) > 2048
            or any(not isinstance(e, dict) for e in receipt['events'])):
        raise ValueError('invalid invocation result schema')


def validate_state(state, workflow):
    verify_seal(state)
    required = {'version', 'run_id', 'fingerprint', 'validators', 'inputs', 'status', 'reason', 'current',
                'calls', 'visits', 'outputs', 'bindings', 'history', 'pending', 'entered', 'attempt',
                'feedback', 'invocations', 'evidence', 'started_at', 'deadline', 'sha256'}
    if set(state) - (required | {'question', 'choices', 'pause_bindings'}) or required - set(state) or state['version'] != 2:
        raise ValueError('invalid checkpoint schema; start a new run')
    if (not isinstance(state['run_id'], str) or not IDENTIFIER.fullmatch(state['run_id'])
            or state['current'] not in workflow.definition['steps']
            or state['status'] not in {'running', 'waiting', 'blocked', 'completed', 'rejected'}
            or type(state['entered']) is not bool or type(state['attempt']) is not int or state['attempt'] < 0
            or type(state['calls']) is not int or not isinstance(state['invocations'], list)
            or state['calls'] != len(state['invocations']) or not 0 <= state['calls'] <= workflow.definition['limits']['max_calls']
            or not isinstance(state['outputs'], dict) or not isinstance(state['bindings'], dict)
            or set(state['outputs']) != set(state['bindings'])
            or not isinstance(state['visits'], dict) or not isinstance(state['history'], list)):
        raise ValueError('invalid checkpoint invariants')
    for step, visits in state['visits'].items():
        if step not in workflow.definition['steps'] or type(visits) is not int or not 1 <= visits <= workflow.definition['steps'][step].get('max_visits', workflow.definition['limits']['max_visits']):
            raise ValueError('invalid step visit count')
    current = workflow.definition['steps'][state['current']]
    if (state['attempt'] > current.get('max_attempts', 2)
            or (current['kind'] != 'agent' and state['attempt'] != 0)
            or (state['status'] in {'completed', 'rejected'} and
                (current['kind'] != 'finish' or state['status'] != current.get('outcome', 'completed') or state['pending'] is not None))):
        raise ValueError('invalid checkpoint phase/attempt')
    for sequence, event in enumerate(state['history'], 1):
        if (not isinstance(event, dict) or event.get('sequence') != sequence
                or event.get('step') not in workflow.definition['steps'] or not isinstance(event.get('event'), str)
                or type(event.get('time')) not in (int, float)):
            raise ValueError('invalid checkpoint history')
        if event['event'] == 'human_decision':
            step = workflow.definition['steps'][event['step']]
            if step['kind'] != 'pause' or event.get('choice') not in step['choices']:
                raise ValueError('invalid human decision')
            if 'response_schema' in step:
                if 'response' not in event or not Draft202012Validator(workflow.schemas[event['step']]).is_valid(event['response']):
                    raise ValueError('invalid human response')
            elif 'response' in event:
                raise ValueError('unexpected human response')
    ids = set()
    for invocation in state['invocations']:
        if (not isinstance(invocation, dict) or set(invocation) != {'id', 'step', 'arguments_sha256', 'status', 'token_usage', 'receipt_sha256'}
                or not isinstance(invocation['id'], str) or not IDENTIFIER.fullmatch(invocation['id'])
                or invocation['id'] in ids or invocation['step'] not in workflow.artifacts
                or not isinstance(invocation['arguments_sha256'], str) or not HASH.fullmatch(invocation['arguments_sha256'])
                or invocation['status'] not in {'pending', 'complete', 'abandoned'}
                or (invocation['token_usage'] is not None and (type(invocation['token_usage']) is not int or invocation['token_usage'] < 0))):
            raise ValueError('invalid invocation ledger')
        ids.add(invocation['id'])
    pending = state['pending']
    waiting_calls = [i for i in state['invocations'] if i['status'] == 'pending']
    if pending is not None:
        if (not isinstance(pending, dict) or set(pending) != {'id', 'step', 'arguments_sha256', 'arguments'}
                or not waiting_calls or len(waiting_calls) != 1 or pending['id'] != state['invocations'][-1]['id']
                or pending['step'] != state['current'] or digest(pending['arguments']) != pending['arguments_sha256']
                or any(pending[k] != waiting_calls[0][k] for k in ('id', 'step', 'arguments_sha256'))):
            raise ValueError('invalid pending invocation')
    elif waiting_calls:
        raise ValueError('pending invocation missing')
    for name, binding in state['bindings'].items():
        if (name not in workflow.artifacts or not isinstance(binding, dict)
                or set(binding) != {'id', 'sha256', 'dependencies'} or binding['id'] not in ids
                or digest(state['outputs'][name]) != binding['sha256'] or not isinstance(binding['dependencies'], dict)):
            raise ValueError('invalid artifact binding')
    if state['status'] == 'waiting':
        step = workflow.definition['steps'][state['current']]
        if (step['kind'] != 'pause' or pending is not None or state.get('question') != step['question']
                or state.get('choices') != list(step['choices']) or state.get('pause_bindings') != state['bindings']):
            raise ValueError('invalid human pause binding')
