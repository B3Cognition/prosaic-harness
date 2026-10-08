"""A deterministic controller around one-agent invocations and validated results."""
from dataclasses import asdict
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import uuid
import time
import threading

from jsonschema import Draft202012Validator
from prosaic_runtime import ProsaicRuntime, RunPolicy
from .file_store import FileRunStore
from .run_store import (LeaseLost, StoreError, StoreBusy, StoreCorrupt, RevisionConflict,
                        validate_id, validate_revision)
from .workflow import digest
from .contracts import seal, validate_state, validate_receipt, output_json
from .validation import Validator, CheckContext


class Harness:
    def __init__(self, workflow, run_dir=None, *, store=None, run_id=None, runtime=None, on_event=None, validators=None, cancelled=None, clock=time.time, context=None, accounting=None):
        self.workflow = workflow
        if (run_dir is None) == (store is None) or (run_dir is not None and run_id is not None):
            raise ValueError('supply either run_dir or store with run_id')
        self._legacy_file_mode = run_dir is not None
        self.directory = Path(run_dir).absolute() if self._legacy_file_mode else None
        self.file = self.directory / 'run.json' if self.directory is not None else None
        self.store = FileRunStore.for_run_dir(self.directory) if self._legacy_file_mode else store
        self._storage_run_id = 'legacy' if self._legacy_file_mode else validate_id(run_id)
        self._lease = None
        self._revision = None
        self._ownership_failure = None
        self._execution_lock = threading.Lock()
        self.runtime = runtime or (ProsaicRuntime(workflow.config, custom_tools=workflow.custom_tools)
                                   if workflow.custom_tools else ProsaicRuntime(workflow.config))
        self.context = context
        self.accounting = accounting
        self._accounting_enabled = (context is not None or accounting is not None
                                    or getattr(self.runtime, 'accounting', None) is not None
                                    or getattr(self.runtime, 'context_defaults', None) is not None)
        if self._accounting_enabled and 'accounting_v1' not in getattr(self.runtime, 'capabilities', ()):
            raise ValueError('accounting/context needs a Prosaic Runtime with accounting_v1 support')
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

    def _accounting_scope(self):
        recorder = self.accounting if self.accounting is not None else getattr(self.runtime, 'accounting', None)
        if recorder is None:
            return None
        from prosaic_runtime.accounting import identifier
        return {name: identifier(getattr(recorder, name)) for name in ('namespace', 'environment')}

    def _resolved_accounting_context(self, run_id):
        from dataclasses import replace
        from prosaic_runtime.accounting import resolve_context
        recorder = self.accounting if self.accounting is not None else getattr(self.runtime, 'accounting', None)
        defaults = getattr(recorder, 'defaults', None) or getattr(self.runtime, 'context_defaults', None)
        context = resolve_context(self.context, defaults)
        if context.run_id is not None and context.run_id != run_id:
            raise ValueError('accounting context run_id conflicts with run identity')
        return replace(context, run_id=run_id)

    def _resume_accounting(self, state):
        if 'accounting_context' not in state and not self._accounting_enabled:
            return
        scope = self._accounting_scope()
        if 'accounting_scope' in state and scope is not None and scope != state['accounting_scope']:
            raise ValueError('accounting scope conflicts with saved scope')
        from prosaic_runtime.accounting import ATTRIBUTION, ResolvedContext
        if 'accounting_context' not in state:
            if not self._accounting_enabled:
                return
            state['accounting_context'] = self._resolved_accounting_context(state['run_id']).to_dict()
            state['accounting_migration'] = {'source': 'legacy_checkpoint', 'time': self.clock()}
            if scope is not None:
                state['accounting_scope'] = scope
            self._save(state)
        else:
            saved = ResolvedContext.from_dict(state['accounting_context'])
            if self.context is not None:
                for name in (*ATTRIBUTION, 'actor_id', 'project_id', 'run_id', 'request_id'):
                    provided = getattr(self.context, name)
                    if provided is not None and provided != getattr(saved, name):
                        raise ValueError('supplied accounting context conflicts with saved context')
            if scope is not None and 'accounting_scope' not in state:
                state['accounting_scope'] = scope
                self._save(state)

    def _invocation_accounting(self, state, attempt_id, step):
        if 'accounting_context' not in state:
            return {}
        scope = self._accounting_scope()
        if 'accounting_scope' in state and scope != state['accounting_scope']:
            raise ValueError('saved accounting scope requires its configured recorder')
        if 'accounting_v1' not in getattr(self.runtime, 'capabilities', ()):
            raise ValueError('saved accounting context needs accounting_v1 support')
        from prosaic_runtime.accounting import ResolvedContext
        child = ResolvedContext.from_dict(state['accounting_context']).child(
            invocation_id=attempt_id, run_id=state['run_id'], step_id=step)
        options = {'context': child}
        if self.accounting is not None:
            options['accounting'] = self.accounting
        return options

    def _check_custom_tools(self):
        expected = self.workflow.tool_descriptors
        sandbox = getattr(self.workflow.config, 'cli_sandbox', None)
        if (getattr(sandbox, 'mode', 'off') == 'required' and
                self.workflow.config.tool_directories and expected):
            if 'cli_sandbox_v1' not in getattr(self.runtime, 'capabilities', ()):
                raise ValueError('required CLI sandbox needs cli_sandbox_v1 support')
            if getattr(getattr(self.runtime, 'config', None), 'cli_sandbox', None) != sandbox:
                raise ValueError('required CLI sandbox adapter policy does not match workflow')
        if expected:
            if 'custom_tools_v1' not in getattr(self.runtime, 'capabilities', ()):
                raise ValueError('custom tools require custom_tools_v1 support')
            actual = getattr(self.runtime, 'tool_descriptors', {})
            if any(actual.get(name) != descriptor for name, descriptor in expected.items()):
                raise ValueError('custom tool adapter descriptors do not match workflow')

    def _save(self, state):
        self._check_ownership()
        state.update(seal(state))
        if self._revision is None:
            self._revision = self.store.create_run(self._storage_run_id, state, self._lease)
        else:
            self._revision = self.store.save_run(self._storage_run_id, state, self._revision, self._lease)

    @contextmanager
    def _execution(self):
        if not self._execution_lock.acquire(blocking=False):
            raise StoreBusy('do not share a Harness instance between executions')
        context = None
        try:
            self.store.check_ready()
            context = self.store.lease(self._storage_run_id)
            self._lease = context.__enter__()
            self._ownership_failure = None
            self._revision = None
            try:
                yield
            except BaseException as exc:
                try:
                    context.__exit__(type(exc), exc, exc.__traceback__)
                except Exception:
                    exc.add_note('storage session cleanup failed; reconcile before retrying')
                raise
            else:
                context.__exit__(None, None, None)
        finally:
            self._lease = None
            self._execution_lock.release()

    def _check_ownership(self):
        if self._ownership_failure is not None:
            raise self._ownership_failure
        if self._lease is None:
            raise LeaseLost('no active execution session')
        self._lease.check_valid()

    def _runtime_cancelled(self, state):
        try:
            self._check_ownership()
        except StoreError as exc:
            self._ownership_failure = exc
            return True
        return bool(self._resource_reason(state))

    def status(self):
        snapshot = self.store.load_run(self._storage_run_id)
        validate_state(snapshot.state, self.workflow)
        self._validate_address(snapshot.state)
        self._verify_ledger(snapshot.state)
        return snapshot

    def _validate_address(self, state):
        if not self._legacy_file_mode and state['run_id'] != self._storage_run_id:
            raise StoreCorrupt('checkpoint identity does not match its storage address')

    def _check_expected_revision(self, expected_revision, *, human_action):
        if human_action and not self._legacy_file_mode and expected_revision is None:
            raise ValueError('expected_revision is required for this response')
        if expected_revision is not None:
            validate_revision(expected_revision)
            if expected_revision != self._revision:
                raise RevisionConflict('checkpoint changed; refresh status')

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
        with self._execution():
            now = self.clock()
            state = {'version': 2, 'run_id': uuid.uuid4().hex if self._legacy_file_mode else self._storage_run_id, 'fingerprint': self.workflow.fingerprint,
                     'validators': self.validator_versions, 'inputs': inputs,
                     'status': 'running', 'reason': None, 'current': self.workflow.definition['start'],
                     'calls': 0, 'visits': {}, 'outputs': {}, 'history': [], 'pending': None,
                     'entered': False, 'attempt': 0, 'feedback': None, 'bindings': {}, 'invocations': [],
                     'evidence': self.workflow.snapshot(), 'started_at': now,
                     'deadline': now + self.workflow.definition['limits']['max_run_s'] if 'max_run_s' in self.workflow.definition['limits'] else None}
            if self._accounting_enabled:
                state['accounting_context'] = self._resolved_accounting_context(state['run_id']).to_dict()
                scope = self._accounting_scope()
                if scope is not None:
                    state['accounting_scope'] = scope
            self._save(state)
            return self._drive(state)

    def resume(self, *, choice=None, response=None, retry_interrupted=False, expected_revision=None):
        self._check_custom_tools()
        with self._execution():
            snapshot = self.store.load_run(self._storage_run_id)
            state, self._revision = snapshot.state, snapshot.revision
            validate_state(state, self.workflow)
            self._validate_address(state)
            self._check_expected_revision(expected_revision, human_action=choice is not None or response is not None or retry_interrupted)
            if state['fingerprint'] != self.workflow.fingerprint or state['validators'] != self.validator_versions:
                raise ValueError('workflow, prose, schema, or runtime configuration changed; start a new run')
            self._evidence_unchanged(state)
            self._verify_ledger(state)
            self._resume_accounting(state)
            if state['status'] in {'completed', 'rejected'}:
                if choice is not None or response is not None:
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
                    if response is not None:
                        raise ValueError('response requires a declared choice')
                    return state
                if choice not in step['choices']:
                    raise ValueError('choice is not declared by the pending pause')
                if 'response_schema' in step:
                    response = output_json(json.dumps(response, allow_nan=False))
                    errors = list(Draft202012Validator(self.workflow.schemas[state['current']]).iter_errors(response))
                    if errors:
                        raise ValueError('human response failed schema validation')
                    error = self._checks(state, state['current'], {'choice': choice, 'response': response}, step.get('validators', []))
                    if error:
                        raise ValueError('human response failed validation: ' + error)
                elif response is not None:
                    raise ValueError('pause has no response schema')
                self._event(state, 'human_decision', choice=choice, **({'response': response} if 'response_schema' in step else {}))
                self._advance(state, step['choices'][choice])
            elif choice is not None or response is not None:
                raise ValueError('run has no pending human choice')
            pending = state['pending']
            if pending is not None:
                receipt = self.store.load_receipt(self._storage_run_id, pending['id'])
                if receipt is not None:
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
                receipt = self.store.load_receipt(self._storage_run_id, invocation['id'])
                if receipt is None:
                    raise StoreCorrupt('completed invocation is missing its receipt')
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
                               deepcopy(state['evidence']), deepcopy(state['bindings']), self._human_responses(state))
        issues = []
        for validator in names:
            try:
                result = self.validators[validator].check(deepcopy(output), context)
                if not isinstance(result, list) or any(not isinstance(i, str) or not i for i in result):
                    raise ValueError('validators must return a list of nonempty issue strings')
            except StoreError:
                raise
            except Exception as exc:
                raise ValueError(f'trusted validator {validator} failed ({type(exc).__name__})') from exc
            issues.extend(result[:8])
        return '; '.join(issues)[:2048] or None

    def _human_responses(self, state):
        return deepcopy({event['step']: {'choice': event['choice'], 'response': event['response']}
                         for event in state['history'] if event['event'] == 'human_decision' and 'response' in event})

    def _advance(self, state, target, *, feedback=None):
        self._event(state, 'transition', target=target)
        state.update(current=target, entered=False, attempt=0, feedback=feedback, status='running', reason=None)
        self._save(state)

    def _accept(self, state, receipt):
        self._check_ownership()
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
            except StoreError:
                raise
            except ValueError:
                return self._block(state, 'validator_error')
        self._check_ownership()
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
            self._check_ownership()
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
                    except StoreError:
                        raise
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
                responses = self._human_responses(state)
                if responses:
                    arguments['human_responses'] = responses
                attempt_id = uuid.uuid4().hex
                accounting_options = self._invocation_accounting(state, attempt_id, name)
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
                self._check_ownership()
                result = self.runtime.run(self.workflow.artifacts[name], json.dumps(arguments),
                                          cwd=self.workflow.path.parent, policy=policy, on_event=record,
                                          cancelled=lambda: self._runtime_cancelled(state),
                                          **({'acquisition': self.workflow.acquisitions[name]} if name in self.workflow.acquisitions else {}),
                                          **accounting_options)
                self._check_ownership()
                receipt = seal({'version': 1, 'run_id': state['run_id'], 'id': attempt_id, 'step': name, 'arguments_sha256': digest(arguments),
                                'arguments': arguments, 'result': asdict(result), 'events': events})
                self.store.save_receipt(self._storage_run_id, attempt_id, receipt, self._lease)
                self._accept(state, receipt)
        return state
