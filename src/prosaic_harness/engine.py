"""A deterministic controller around one-agent invocations and validated results."""
from dataclasses import asdict
import json
from pathlib import Path
import re
import uuid

from jsonschema import Draft202012Validator
from prosaic_runtime import ProsaicRuntime, RunPolicy
from .store import locked, write_json
from .workflow import digest


class Harness:
    def __init__(self, workflow, run_dir, *, runtime=None, on_event=None):
        self.workflow = workflow
        self.directory = Path(run_dir).resolve()
        self.file = self.directory / 'run.json'
        self.runtime = runtime or ProsaicRuntime(workflow.config)
        self.on_event = on_event

    def _save(self, state):
        write_json(self.file, state)

    def _event(self, state, event_type, **data):
        event = {'event': event_type, 'step': state['current'], **data}
        state['history'].append(event)
        if self.on_event:
            self.on_event(event)

    def _block(self, state, reason):
        state.update(status='blocked', reason=reason)
        self._event(state, 'blocked', reason=reason)
        self._save(state)
        return state

    def run(self, inputs):
        digest(inputs)  # JSON-serializable and finite before creating a run.
        with locked(self.directory):
            if self.file.exists():
                raise ValueError('run already exists; use resume or a new directory')
            state = {'version': 1, 'fingerprint': self.workflow.fingerprint, 'inputs': inputs,
                     'status': 'running', 'reason': None, 'current': self.workflow.definition['start'],
                     'calls': 0, 'visits': {}, 'outputs': {}, 'history': [], 'pending': None,
                     'entered': False, 'attempt': 0, 'feedback': None}
            self._save(state)
            return self._drive(state)

    def resume(self, *, choice=None, retry_interrupted=False):
        with locked(self.directory):
            state = json.loads(self.file.read_text())
            if state.get('version') != 1 or state.get('fingerprint') != self.workflow.fingerprint:
                raise ValueError('workflow, prose, schema, or runtime configuration changed; start a new run')
            if state['status'] in {'completed', 'rejected'}:
                if choice:
                    raise ValueError('completed run has no pending choice')
                return state
            if state['status'] == 'waiting':
                step = self.workflow.definition['steps'][state['current']]
                if choice is None:
                    return state
                if choice not in step['choices']:
                    raise ValueError('choice is not declared by the pending pause')
                self._event(state, 'human_decision', choice=choice)
                self._advance(state, step['choices'][choice])
            elif choice is not None:
                raise ValueError('run has no pending human choice')
            pending = state['pending']
            if pending is not None:
                path = self.directory / 'attempts' / (pending['id'] + '.json')
                if path.exists():
                    receipt = json.loads(path.read_text())
                    if receipt['step'] != state['current'] or receipt['id'] != pending['id'] or receipt['arguments_sha256'] != pending['arguments_sha256']:
                        raise ValueError('receipt does not match pending invocation')
                    self._accept(state, receipt)
                elif not retry_interrupted:
                    return self._block(state, 'interrupted_call')
                else:
                    self._event(state, 'interrupted_retry', abandoned=pending['id'])
                    state['pending'] = None
                    state['attempt'] -= 1  # Unknown attempt remains in calls/history; retry needs another call slot.
                    self._save(state)
            if state['status'] == 'blocked' and state['reason'] != 'interrupted_call':
                return state
            state.update(status='running', reason=None)
            self._save(state)
            return self._drive(state)

    def _advance(self, state, target):
        self._event(state, 'transition', target=target)
        state.update(current=target, entered=False, attempt=0, feedback=None, status='running', reason=None)
        self._save(state)

    def _accept(self, state, receipt):
        state['pending'] = None
        step = self.workflow.definition['steps'][state['current']]
        result = receipt['result']
        error = None
        output = None
        if result['exit_code'] != 0:
            error = 'runtime invocation failed or timed out'
        else:
            try:
                text = result['stdout'].strip()
                match = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', text, re.S)
                if match:
                    text = match[1]
                output = json.loads(text, parse_constant=lambda v: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
                errors = list(Draft202012Validator(self.workflow.schemas[state['current']]).iter_errors(output))
                if errors:
                    error = '; '.join(f'{list(e.path)}: {e.message}' for e in errors[:5])[:2048]
            except (ValueError, TypeError):
                error = 'response must be one JSON value, optionally in a JSON code fence'
        if error is None:
            successful = {event.get('name') for event in receipt['events']
                          if event.get('event') == 'tool_completed' and event.get('status') == 'ok'}
            missing = set(step.get('require_tools', [])) - successful
            if missing:
                error = f'execute required granted tools successfully before returning JSON: {sorted(missing)}'
        if error:
            state['feedback'] = error
            self._event(state, 'validation_failed', attempt_id=receipt['id'], message=error)
            if state['attempt'] >= step.get('max_attempts', 2):
                self._block(state, 'attempt_limit')
            else:
                self._save(state)
        else:
            state['outputs'][state['current']] = output
            self._event(state, 'accepted', attempt_id=receipt['id'], token_usage=result['token_usage'])
            self._advance(state, step['next'])

    def _drive(self, state):
        steps = self.workflow.definition['steps']
        limits = self.workflow.definition['limits']
        while state['status'] == 'running':
            name = state['current']
            step = steps[name]
            if not state['entered']:
                visits = state['visits'].get(name, 0)
                if visits >= step.get('max_visits', limits['max_visits']):
                    return self._block(state, 'visit_limit')
                state['visits'][name] = visits + 1
                state['entered'] = True
                self._event(state, 'step_started', kind=step['kind'], visit=visits + 1)
                self._save(state)
            kind = step['kind']
            if kind == 'finish':
                state.update(status=step.get('outcome', 'completed'), reason=None)
                self._event(state, 'finished', status=state['status'])
                self._save(state)
            elif kind == 'pause':
                state.update(status='waiting', question=step['question'], choices=list(step['choices']))
                self._event(state, 'waiting', question=step['question'], choices=list(step['choices']))
                self._save(state)
            elif kind == 'gate':
                try:
                    value = state['outputs'][step['from']]
                    for field in step['field']:
                        value = value[field]
                except (KeyError, TypeError):
                    return self._block(state, 'gate_input_missing')
                matches = type(value) is type(step['equals']) and value == step['equals']
                self._advance(state, step['pass'] if matches else step['fail'])
            else:
                if state['calls'] >= limits['max_calls']:
                    return self._block(state, 'call_limit')
                if any(ref not in state['outputs'] for ref in step.get('inputs', [])):
                    return self._block(state, 'agent_input_missing')
                refs = step.get('inputs', []) + step.get('optional_inputs', [])
                arguments = json.dumps({'request': state['inputs'], 'artifacts': {ref: state['outputs'][ref] for ref in refs if ref in state['outputs']},
                                        'validation_feedback': state['feedback']})
                attempt_id = uuid.uuid4().hex
                state['calls'] += 1
                state['attempt'] += 1
                state['pending'] = {'id': attempt_id, 'arguments_sha256': digest(arguments)}
                self._event(state, 'invocation', attempt_id=attempt_id, call=state['calls'])
                self._save(state)
                events = []
                def record(event):
                    events.append(event)
                    if self.on_event:
                        self.on_event({**event, 'step': name, 'attempt_id': attempt_id})
                policy = RunPolicy(allowed_tools=frozenset(step.get('tools', [])),
                                   read_roots=tuple(step.get('read_roots', [])),
                                   timeout_s=limits['timeout_s'], max_tool_rounds=self.workflow.config.limits.max_tool_rounds)
                result = self.runtime.run(self.workflow.artifacts[name], arguments,
                                          cwd=self.workflow.path.parent, policy=policy, on_event=record)
                receipt = {'id': attempt_id, 'step': name, 'arguments_sha256': digest(arguments),
                           'arguments': json.loads(arguments), 'result': asdict(result), 'events': events}
                write_json(self.directory / 'attempts' / (attempt_id + '.json'), receipt)
                self._accept(state, receipt)
        return state
