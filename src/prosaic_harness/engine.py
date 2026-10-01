"""A deterministic controller around one-agent invocations and validated results."""
from dataclasses import asdict
from copy import deepcopy
import json
from pathlib import Path
import uuid
import time

from jsonschema import Draft202012Validator
from prosaic_runtime import ProsaicRuntime, RunPolicy
from .store import locked, write_json, read_json
from .workflow import digest
from .contracts import seal, validate_state, validate_receipt, output_json
from .validation import Validator, CheckContext


class Harness:
    def __init__(self, workflow, run_dir, *, runtime=None, on_event=None, validators=None, cancelled=None, clock=time.time):
        self.workflow = workflow
        self.directory = Path(run_dir).absolute()
        self.file = self.directory / 'run.json'
        self.runtime = runtime or (ProsaicRuntime(workflow.config, custom_tools=workflow.custom_tools)
                                   if workflow.custom_tools else ProsaicRuntime(workflow.config))
        self.on_event = on_event
        self.validators = dict(validators or {})
        self.cancelled = cancelled or (lambda: False)
        self.clock = clock
        needed = {v for step in workflow.definition['steps'].values() for v in step.get('validators', [])}
        if any(name not in self.validators or not isinstance(self.validators[name], Validator) for name in needed):
            raise ValueError('missing trusted validators; supply validators= or --checks')
        self.validator_versions = {name: self.validators[name].version for name in sorted(needed)}
        if any(step.get('require_reads') for step in workflow.definition['steps'].values()) and 'read_receipts_v1' not in getattr(self.runtime, 'capabilities', ()):
            raise ValueError('require_reads needs a Prosaic Runtime with read_receipts_v1 support')
        if workflow.acquisitions and 'acquisition_v1' not in getattr(self.runtime, 'capabilities', ()):
            raise ValueError('acquisition needs a Prosaic Runtime with acquisition_v1 support')
        self._check_custom_tools()

    def _check_custom_tools(self):
        expected = self.workflow.tool_descriptors
        if expected:
            if 'custom_tools_v1' not in getattr(self.runtime, 'capabilities', ()):
                raise ValueError('custom tools require custom_tools_v1 support')
            actual = getattr(self.runtime, 'tool_descriptors', {})
            if any(actual.get(name) != descriptor for name, descriptor in expected.items()):
                raise ValueError('custom tool adapter descriptors do not match workflow')

    def _save(self, state):
        state.update(seal(state))
        write_json(self.file, state)

    def _event(self, state, event_type, **data):
        event = {'event': event_type, 'step': state['current'], 'sequence': len(state['history']) + 1, 'time': self.clock(), **data}
        state['history'].append(event)
        if self.on_event:
            self.on_event(event)

    def _block(self, state, reason):
        state.update(status='blocked', reason=reason)
        self._event(state, 'blocked', reason=reason)
        self._save(state)
        return state

    def run(self, inputs):
        self._check_custom_tools()
        digest(inputs)  # JSON-serializable and finite before creating a run.
        with locked(self.directory):
            if self.file.exists():
                raise ValueError('run already exists; use resume or a new directory')
            now = self.clock()
            state = {'version': 2, 'run_id': uuid.uuid4().hex, 'fingerprint': self.workflow.fingerprint,
                     'validators': self.validator_versions, 'inputs': inputs,
                     'status': 'running', 'reason': None, 'current': self.workflow.definition['start'],
                     'calls': 0, 'visits': {}, 'outputs': {}, 'history': [], 'pending': None,
                     'entered': False, 'attempt': 0, 'feedback': None, 'bindings': {}, 'invocations': [],
                     'evidence': self.workflow.snapshot(), 'started_at': now,
                     'deadline': now + self.workflow.definition['limits']['max_run_s'] if 'max_run_s' in self.workflow.definition['limits'] else None}
            self._save(state)
            return self._drive(state)

    def resume(self, *, choice=None, retry_interrupted=False):
        self._check_custom_tools()
        with locked(self.directory):
            state = read_json(self.file)
            validate_state(state, self.workflow)
            if state['fingerprint'] != self.workflow.fingerprint or state['validators'] != self.validator_versions:
                raise ValueError('workflow, prose, schema, or runtime configuration changed; start a new run')
            self._evidence_unchanged(state)
            self._verify_ledger(state)
            if state['status'] in {'completed', 'rejected'}:
                if choice:
                    raise ValueError('completed run has no pending choice')
                return state
            if state['status'] == 'blocked' and state['reason'] != 'interrupted_call':
                return state
            reason = self._resource_reason(state)
            if reason and state['pending'] is None:
                return self._block(state, reason)
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
                if path.exists() or path.is_symlink():
                    receipt = read_json(path)
                    validate_receipt(receipt, state, pending)
                    self._accept(state, receipt)
                elif not retry_interrupted:
                    return self._block(state, 'interrupted_call')
                else:
                    self._event(state, 'interrupted_retry', abandoned=pending['id'])
                    state['pending'] = None
                    state['invocations'][-1]['status'] = 'abandoned'
                    state['attempt'] -= 1  # Unknown attempt remains in calls/history; retry needs another call slot.
                    self._save(state)
            if state['status'] == 'blocked' and state['reason'] != 'interrupted_call':
                return state
            state.update(status='running', reason=None)
            self._save(state)
            return self._drive(state)

    def _evidence_unchanged(self, state):
        if self.workflow.current_fingerprint() != state['fingerprint']:
            raise ValueError('loaded workflow changed; start a new run')
        if self.workflow.snapshot() != state['evidence']:
            raise ValueError('declared evidence changed; start a new run')

    def _verify_ledger(self, state):
        for invocation in state['invocations']:
            if invocation['status'] == 'complete':
                receipt = read_json(self.directory / 'attempts' / (invocation['id'] + '.json'))
                validate_receipt(receipt, state, invocation)
                if receipt['sha256'] != invocation['receipt_sha256'] or receipt['result']['token_usage'] != invocation['token_usage']:
                    raise ValueError('invocation ledger receipt mismatch')
                for name, binding in state['bindings'].items():
                    if binding['id'] == invocation['id']:
                        refs = self.workflow.definition['steps'][name].get('inputs', [])
                        dependencies = {ref: receipt['arguments']['artifact_bindings'][ref] for ref in refs}
                        if (name != invocation['step'] or output_json(receipt['result']['stdout']) != state['outputs'][name]
                                or binding['dependencies'] != dependencies):
                            raise ValueError('accepted output/binding differs from receipt')

    def _fresh(self, state, name, seen=None):
        seen = set() if seen is None else seen
        if name in seen or name not in state['bindings']:
            return False
        seen = seen | {name}
        return all(state['bindings'].get(ref, {}).get('id') == binding['id'] and self._fresh(state, ref, seen)
                   for ref, binding in state['bindings'][name]['dependencies'].items())

    def _resource_reason(self, state, *, before_call=False):
        if self.cancelled():
            return 'cancelled'
        if state['deadline'] is not None and self.clock() >= state['deadline']:
            return 'run_deadline'
        budget = self.workflow.definition['limits'].get('max_tokens')
        if budget is not None:
            usage = [i['token_usage'] for i in state['invocations'] if i['status'] != 'pending']
            if any(value is None for value in usage):
                return 'usage_unknown'
            total = sum(usage)
            if total > budget or (before_call and total >= budget):
                return 'token_limit'

    def _checks(self, state, name, output, names):
        context = CheckContext(name, deepcopy(state['inputs']), deepcopy(state['outputs']),
                               deepcopy(state['evidence']), deepcopy(state['bindings']))
        issues = []
        for validator in names:
            try:
                result = self.validators[validator].check(deepcopy(output), context)
                if not isinstance(result, list) or any(not isinstance(i, str) or not i for i in result):
                    raise ValueError('validators must return a list of nonempty issue strings')
            except Exception as exc:
                raise ValueError(f'trusted validator {validator} failed ({type(exc).__name__})') from exc
            issues.extend(result[:8])
        return '; '.join(issues)[:2048] or None

    def _advance(self, state, target, *, feedback=None):
        self._event(state, 'transition', target=target)
        state.update(current=target, entered=False, attempt=0, feedback=feedback, status='running', reason=None)
        self._save(state)

    def _accept(self, state, receipt):
        validate_receipt(receipt, state, state['pending'])
        self._evidence_unchanged(state)
        state['invocations'][-1].update(status='complete', token_usage=receipt['result']['token_usage'], receipt_sha256=receipt['sha256'])
        state['pending'] = None
        reason = self._resource_reason(state)
        if reason:
            return self._block(state, reason)
        step = self.workflow.definition['steps'][state['current']]
        result = receipt['result']
        error = None
        output = None
        if result['exit_code'] != 0:
            reason = ('cancelled' if result['exit_code'] == 130 else
                      'runtime_timeout' if result['timed_out'] else
                      'tool_choice_not_honored' if result['metadata'].get('failure_reason') == 'tool_choice_not_honored' else
                      'acquisition_failed' if result['metadata'].get('failure_reason') == 'acquisition_failed' else
                      'runtime_failure')
            return self._block(state, self._resource_reason(state) or reason)
        else:
            try:
                output = output_json(result['stdout'])
                errors = list(Draft202012Validator(self.workflow.schemas[state['current']]).iter_errors(output))
                if errors:
                    error = '; '.join(f'{list(e.path)}: {e.message}' for e in errors[:5])[:2048]
            except (ValueError, TypeError):
                error = 'response must be one JSON value, optionally in a JSON code fence'
        if error is None:
            successful = {event.get('name') for event in receipt['events']
                          if event.get('event') == 'tool_completed' and event.get('status') == 'ok'
                          and (event.get('name') not in self.workflow.tool_descriptors or
                               event.get('tool_version') == self.workflow.tool_descriptors[event['name']]['version'])}
            missing = set(step.get('require_tools', [])) - successful
            if missing:
                error = f'execute required granted tools successfully before returning JSON: {sorted(missing)}'
        if error is None:
            for path in step.get('require_reads', []):
                expected = state['evidence'][path]
                reads = [read for event in receipt['events'] if event.get('event') == 'tool_completed'
                         and event.get('name') == 'read_file' and event.get('status') == 'ok'
                         for read in event.get('read_receipts', []) if read.get('path') == path and read.get('sha256') == expected['sha256']]
                line_count = len(expected['text'].splitlines())
                covered = {line for read in reads if read.get('line_count') == line_count
                           and type(read.get('offset')) is int and type(read.get('lines_read')) is int
                           and 0 <= read['offset'] <= line_count and 0 <= read['lines_read'] <= line_count - read['offset']
                           for line in range(read['offset'], read['offset'] + read['lines_read'])}
                if not reads or len(covered) != line_count:
                    error = f'read all of declared evidence {path} successfully before returning JSON'
                    break
        if error is None:
            try:
                error = self._checks(state, state['current'], output, step.get('validators', []))
            except ValueError:
                return self._block(state, 'validator_error')
        if error is None and any(not self._fresh(state, ref) for ref in step.get('inputs', [])):
            return self._block(state, 'stale_artifact')
        if error:
            state['feedback'] = error
            self._event(state, 'validation_failed', attempt_id=receipt['id'], message=error)
            if state['attempt'] >= step.get('max_attempts', 2):
                self._block(state, 'attempt_limit')
            else:
                self._save(state)
        else:
            state['outputs'][state['current']] = output
            state['bindings'][state['current']] = {'id': receipt['id'], 'sha256': digest(output),
                'dependencies': {ref: deepcopy(state['bindings'][ref]) for ref in step.get('inputs', [])}}
            self._event(state, 'accepted', attempt_id=receipt['id'], token_usage=result['token_usage'])
            self._advance(state, step['next'])

    def _drive(self, state):
        steps = self.workflow.definition['steps']
        limits = self.workflow.definition['limits']
        while state['status'] == 'running':
            self._evidence_unchanged(state)
            reason = self._resource_reason(state)
            if reason:
                return self._block(state, reason)
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
            if any(not self._fresh(state, ref) for ref in step.get('requires', [])):
                return self._block(state, 'stale_artifact')
            if kind == 'finish':
                state.update(status=step.get('outcome', 'completed'), reason=None)
                self._event(state, 'finished', status=state['status'])
                self._save(state)
            elif kind == 'pause':
                state.update(status='waiting', question=step['question'], choices=list(step['choices']), pause_bindings=deepcopy(state['bindings']))
                self._event(state, 'waiting', question=step['question'], choices=list(step['choices']))
                self._save(state)
            elif kind in {'gate', 'check'}:
                if not self._fresh(state, step['from']):
                    return self._block(state, 'stale_artifact' if step['from'] in state['outputs'] else 'gate_input_missing')
                if kind == 'check':
                    try:
                        error = self._checks(state, step['from'], state['outputs'][step['from']], step['validators'])
                    except ValueError:
                        return self._block(state, 'validator_error')
                    state['feedback'] = error
                    self._event(state, 'check_failed' if error else 'check_passed', artifact_id=state['bindings'][step['from']]['id'], message=error)
                    target = step['fail'] if error else step['pass']
                    self._advance(state, target, feedback=error)
                    continue
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
                if any(not self._fresh(state, ref) for ref in step.get('inputs', [])):
                    return self._block(state, 'stale_artifact')
                reason = self._resource_reason(state, before_call=True)
                if reason:
                    return self._block(state, reason)
                refs = step.get('inputs', []) + step.get('optional_inputs', [])
                arguments = {'request': state['inputs'], 'artifacts': {ref: state['outputs'][ref] for ref in refs if ref in state['outputs']},
                             'artifact_bindings': {ref: state['bindings'][ref] for ref in refs if ref in state['outputs']},
                             'sources': {path: {'sha256': item['sha256']} if path in step.get('require_reads', []) else item
                                         for path, item in state['evidence'].items()}, 'validation_feedback': state['feedback']}
                attempt_id = uuid.uuid4().hex
                state['calls'] += 1
                state['attempt'] += 1
                state['pending'] = {'id': attempt_id, 'step': name, 'arguments_sha256': digest(arguments), 'arguments': arguments}
                state['invocations'].append({'id': attempt_id, 'step': name, 'arguments_sha256': digest(arguments),
                                             'status': 'pending', 'token_usage': None, 'receipt_sha256': None})
                self._event(state, 'invocation', attempt_id=attempt_id, call=state['calls'])
                self._save(state)
                events = []
                def record(event):
                    if event['event'] not in {'text_delta', 'reasoning_delta', 'text', 'progress'}:
                        if len(events) >= 2048:
                            raise ValueError('runtime event limit exceeded')
                        events.append(event)
                    if self.on_event:
                        self.on_event({**event, 'step': name, 'attempt_id': attempt_id})
                timeout = limits['timeout_s'] if state['deadline'] is None else min(limits['timeout_s'], max(0.001, state['deadline'] - self.clock()))
                policy = RunPolicy(allowed_tools=frozenset(step.get('tools', [])),
                                   read_roots=tuple(step.get('read_roots', [])),
                                   timeout_s=timeout, max_tool_rounds=self.workflow.config.limits.max_tool_rounds,
                                   **({'initial_tool': 'read_file'} if step.get('require_reads') and
                                      'initial_tool_v1' in getattr(self.runtime, 'capabilities', ()) else {}))
                result = self.runtime.run(self.workflow.artifacts[name], json.dumps(arguments),
                                          cwd=self.workflow.path.parent, policy=policy, on_event=record,
                                          cancelled=lambda: bool(self._resource_reason(state)),
                                          **({'acquisition': self.workflow.acquisitions[name]} if name in self.workflow.acquisitions else {}))
                receipt = seal({'version': 1, 'run_id': state['run_id'], 'id': attempt_id, 'step': name, 'arguments_sha256': digest(arguments),
                                'arguments': arguments, 'result': asdict(result), 'events': events})
                write_json(self.directory / 'attempts' / (attempt_id + '.json'), receipt)
                self._accept(state, receipt)
        return state
