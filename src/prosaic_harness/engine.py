"""A deterministic controller around one-agent invocations and validated results."""
from dataclasses import asdict
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import uuid
import time
import threading
import math
from tempfile import TemporaryDirectory

from prosaic_runtime import ProsaicRuntime, RunPolicy
from .file_store import FileRunStore
from .run_store import (LeaseLost, StoreError, StoreBusy, StoreCorrupt, RevisionConflict,
                        validate_id, validate_revision)
from .workflow import digest
from .contracts import seal, validate_state, validate_receipt, output_json
from .validation import Validator, CheckContext
from .admission_data import snapshot_json, parse_bounded_json
from .errors import WorkflowAdmissionError, HumanResponseError, response_schema_issues
from .interaction import project_interaction
from .schema_validation import evaluate_schema, SchemaEvaluationError
from .factory import admit_workflow, _config_from_json
from .observations import CommittedObserver

_TERMINAL_HEADROOM = 4096
_TERMINAL_NODES = 16


class Harness:
    def __init__(self, workflow, run_dir=None, *, store=None, run_id=None, runtime=None, on_event=None, observer=None, validators=None, cancelled=None, clock=time.time, context=None, accounting=None):
        self.workflow = workflow
        admission = admit_workflow(workflow)
        self._admission = admission
        self._last_saved_state = None
        self._cwd = None
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
        self.runtime = runtime or (ProsaicRuntime(_config_from_json(admission.config_json), custom_tools=admission.tools) if admission else
                                   ProsaicRuntime(workflow.config, custom_tools=workflow.custom_tools)
                                   if workflow.custom_tools else ProsaicRuntime(workflow.config))
        self.context = context
        self.accounting = accounting
        self._accounting_enabled = (context is not None or accounting is not None
                                    or getattr(self.runtime, 'accounting', None) is not None
                                    or getattr(self.runtime, 'context_defaults', None) is not None)
        if self._accounting_enabled and 'accounting_v1' not in getattr(self.runtime, 'capabilities', ()):
            raise ValueError('accounting/context needs a Prosaic Runtime with accounting_v1 support')
        self.on_event = on_event
        self._observations = CommittedObserver(observer)
        self.validators = dict(admission.validators if admission and validators is None else validators or {})
        self.cancelled = cancelled or (lambda: False)
        self.clock = clock
        needed = {v for step in workflow.definition['steps'].values() for v in step.get('validators', [])}
        if any(name not in self.validators or not isinstance(self.validators[name], Validator) for name in needed):
            raise ValueError('missing trusted validators; supply validators= or --checks')
        self.validator_versions = {name: self.validators[name].version for name in sorted(needed)}
        self._validator_versions_json = json.dumps(self.validator_versions, sort_keys=True)
        if any(step.get('require_reads') for step in workflow.definition['steps'].values()) and 'read_receipts_v1' not in getattr(self.runtime, 'capabilities', ()):
            raise ValueError('require_reads needs a Prosaic Runtime with read_receipts_v1 support')
        if workflow.acquisitions and 'acquisition_v1' not in getattr(self.runtime, 'capabilities', ()):
            raise ValueError('acquisition needs a Prosaic Runtime with acquisition_v1 support')
        self._check_custom_tools()
        self._admit()

    def _admit(self):
        if self._observations.observer is not None and 'observer_v1' not in getattr(self.runtime, 'capabilities', ()):
            raise ValueError('observer needs a Prosaic Runtime with observer_v1 support')
        if self._admission is None:
            self._check_custom_tools()  # Preserve released trusted-adapter diagnostics.
        admission = admit_workflow(self.workflow, runtime=self.runtime, validators=self.validators)
        if admission is not self._admission:
            raise WorkflowAdmissionError('identity_mismatch')
        needed = {name for step in self.workflow.definition['steps'].values() for name in step.get('validators', [])}
        if any(not isinstance(self.validators.get(name), Validator) for name in needed):
            raise WorkflowAdmissionError('binding_mismatch')
        actual = {name: self.validators[name].version for name in sorted(needed)}
        if (json.dumps(actual, sort_keys=True) != self._validator_versions_json
                or actual != self.validator_versions):
            raise WorkflowAdmissionError('binding_mismatch')

    def _snapshot(self, value, maximum):
        policy = self._admission.policy
        return snapshot_json(value, maximum_bytes=maximum,
                             maximum_depth=policy.max_json_depth, maximum_nodes=policy.max_json_nodes)

    def _bounded_document(self, value, maximum, *, reserve=0, reserve_nodes=0):
        policy = self._admission.policy
        if policy.max_json_nodes <= reserve_nodes:
            raise WorkflowAdmissionError('limit_exceeded')
        owned = snapshot_json(value, maximum_bytes=maximum, maximum_depth=policy.max_json_depth,
                              maximum_nodes=policy.max_json_nodes - reserve_nodes)
        # Match FileRunStore's exact legacy on-disk encoder. SQL adapters use a
        # smaller encoding; this conservative bound works for both contracts.
        if len(json.dumps(owned, indent=2, allow_nan=False).encode()) > maximum - reserve:
            raise WorkflowAdmissionError('limit_exceeded')
        return owned

    def _schema_profile(self, *, human=False):
        return self._admission.policy.schema_profile(human=human) if self._admission else None

    def _output(self, text):
        if not self._admission:
            return output_json(text)
        import re
        policy = self._admission.policy
        if type(text) is not str or len(text.encode()) > policy.max_output_bytes:
            raise WorkflowAdmissionError('limit_exceeded')
        text = text.strip()
        match = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', text, re.S)
        return parse_bounded_json(match[1] if match else text, maximum_bytes=policy.max_output_bytes,
                                  maximum_depth=policy.max_json_depth, maximum_nodes=policy.max_json_nodes)

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

    def _resume_accounting(self, state, *, persist=True):
        """Validate accounting identity, optionally staging migration until admission."""
        if 'accounting_context' not in state and not self._accounting_enabled:
            return False
        scope = self._accounting_scope()
        if 'accounting_scope' in state and scope is not None and scope != state['accounting_scope']:
            raise ValueError('accounting scope conflicts with saved scope')
        from prosaic_runtime.accounting import ATTRIBUTION, ResolvedContext
        changed = False
        if 'accounting_context' not in state:
            if not self._accounting_enabled:
                return False
            state['accounting_context'] = self._resolved_accounting_context(state['run_id']).to_dict()
            state['accounting_migration'] = {'source': 'legacy_checkpoint', 'time': self.clock()}
            if scope is not None:
                state['accounting_scope'] = scope
            changed = True
        else:
            saved = ResolvedContext.from_dict(state['accounting_context'])
            if self.context is not None:
                for name in (*ATTRIBUTION, 'actor_id', 'project_id', 'run_id', 'request_id'):
                    provided = getattr(self.context, name)
                    if provided is not None and provided != getattr(saved, name):
                        raise ValueError('supplied accounting context conflicts with saved context')
            if scope is not None and 'accounting_scope' not in state:
                state['accounting_scope'] = scope
                changed = True
        if changed and persist:
            self._save(state)
        return changed

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
        if self._admission:
            try:
                self._bounded_document(state, self._admission.policy.max_state_bytes,
                                       reserve=0 if state['status'] == 'blocked' else _TERMINAL_HEADROOM,
                                       reserve_nodes=0 if state['status'] == 'blocked' else _TERMINAL_NODES)
            except WorkflowAdmissionError:
                if self._last_saved_state is None:
                    raise WorkflowAdmissionError('limit_exceeded') from None
                previous = deepcopy(self._last_saved_state)
                # Receipt completion is durable, even when its proposed output
                # cannot fit. Retain the ledger/accounting instead of retrying.
                if (previous['pending'] is not None and state['pending'] is None
                        and state['invocations'][-1]['status'] == 'complete'):
                    previous['invocations'][-1] = deepcopy(state['invocations'][-1])
                    previous['pending'] = None
                previous.update(status='blocked', reason='state_limit')
                previous['history'].append({'event': 'blocked', 'step': previous['current'],
                    'sequence': len(previous['history']) + 1, 'time': self.clock(), 'reason': 'state_limit'})
                state.clear()
                state.update(previous)
                self._bounded_document(state, self._admission.policy.max_state_bytes)
        state.update(seal(state))
        if self._admission:
            self._bounded_document(state, self._admission.policy.max_state_bytes)
        created = self._revision is None
        if created:
            self._revision = self.store.create_run(self._storage_run_id, state, self._lease)
        else:
            self._revision = self.store.save_run(self._storage_run_id, state, self._revision, self._lease)
        if self._admission:
            self._last_saved_state = deepcopy(state)
        if self._observations.observer is not None:
            self._observations.emit_committed(state, self._revision,
                                              recovery=self._observations.recovering, started=created)

    @contextmanager
    def _execution(self):
        if not self._execution_lock.acquire(blocking=False):
            raise StoreBusy('do not share a Harness instance between executions')
        context = None
        workspace = None
        try:
            self._admit()
            if self._admission:
                workspace = TemporaryDirectory(prefix='prosaic-workflow-')
                self._cwd = Path(workspace.name)
            else:
                self._cwd = self.workflow.path.parent
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
            try:
                if workspace is not None:
                    workspace.cleanup()
            finally:
                self._cwd = None
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
        self._admit()
        snapshot = self.store.load_run(self._storage_run_id)
        if self._admission:
            self._bounded_document(snapshot.state, self._admission.policy.max_state_bytes)
        validate_state(snapshot.state, self.workflow)
        self._validate_address(snapshot.state)
        self._evidence_unchanged(snapshot.state)
        if snapshot.state['validators'] != self.validator_versions:
            raise WorkflowAdmissionError('binding_mismatch')
        self._verify_ledger(snapshot.state)
        return snapshot

    def interaction(self, *, review_outputs=(), include_response_schema=False, maximum_bytes=262_144):
        """Return a bounded public view from one verified, read-only snapshot."""
        snapshot = self.status()
        return project_interaction(self.workflow, snapshot, review_outputs=review_outputs,
                                   include_response_schema=include_response_schema,
                                   maximum_bytes=maximum_bytes,
                                   policy=self._admission.policy if self._admission else None)

    def _validate_address(self, state):
        if not self._legacy_file_mode and state['run_id'] != self._storage_run_id:
            raise StoreCorrupt('checkpoint identity does not match its storage address')

    def _check_expected_revision(self, expected_revision, *, human_action):
        if human_action and not self._legacy_file_mode and expected_revision is None:
            raise HumanResponseError('expected_revision_required')
        if expected_revision is not None:
            validate_revision(expected_revision)
            if expected_revision != self._revision:
                raise RevisionConflict('checkpoint changed; refresh status')

    def _event(self, state, event_type, **data):
        event = {'event': event_type, 'step': state['current'], 'sequence': len(state['history']) + 1, 'time': self.clock(), **data}
        state['history'].append(event)
        if self.on_event:
            self.on_event(deepcopy(event) if self._admission else event)

    def _block(self, state, reason):
        state.update(status='blocked', reason=reason)
        self._event(state, 'blocked', reason=reason)
        self._save(state)
        return state

    def run(self, inputs):
        self._admit()
        self._check_custom_tools()
        if self._admission:
            inputs = self.workflow.prepare_inputs(inputs)
        else:
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
            if self._observations.observer is not None:
                self._observations.begin(state['run_id'])
            self._save(state)
            return self._drive(state)

    def resume(self, *, choice=None, response=None, retry_interrupted=False, expected_revision=None):
        self._admit()
        self._check_custom_tools()
        with self._execution():
            snapshot = self.store.load_run(self._storage_run_id)
            state, self._revision = snapshot.state, snapshot.revision
            if self._admission:
                self._bounded_document(state, self._admission.policy.max_state_bytes)
                self._last_saved_state = deepcopy(state)
            validate_state(state, self.workflow)
            self._validate_address(state)
            self._check_expected_revision(expected_revision, human_action=choice is not None or response is not None or retry_interrupted)
            if state['fingerprint'] != self.workflow.fingerprint or state['validators'] != self.validator_versions:
                raise ValueError('workflow, prose, schema, or runtime configuration changed; start a new run')
            self._evidence_unchanged(state)
            self._verify_ledger(state)
            if self._observations.observer is not None:
                self._observations.begin(state['run_id'])
            # Invalid human actions must not persist even an accounting upgrade.
            # Keep identity/conflict admission early, staging its owned state
            # changes until choice/schema/product validation has succeeded.
            human_action = choice is not None or response is not None
            accounting_changed = self._resume_accounting(state, persist=not human_action)
            if state['status'] in {'completed', 'rejected'}:
                if choice is not None or response is not None:
                    raise HumanResponseError('completed_run')
                return state
            if state['status'] == 'blocked' and state['reason'] != 'interrupted_call':
                if human_action and accounting_changed:
                    self._save(state)
                return state
            reason = self._resource_reason(state)
            if reason and state['pending'] is None:
                return self._block(state, reason)
            if state['status'] == 'waiting':
                step = self.workflow.definition['steps'][state['current']]
                if choice is None:
                    if response is not None:
                        raise HumanResponseError('response_requires_choice')
                    return state
                if type(choice) is not str or choice not in step['choices']:
                    raise HumanResponseError('invalid_choice')
                if 'response_schema' in step:
                    try:
                        response = (self._snapshot(response, self._admission.policy.max_human_response_bytes)
                                    if self._admission else output_json(json.dumps(response, allow_nan=False)))
                    except (ValueError, TypeError, UnicodeError, RecursionError):
                        raise HumanResponseError('response_limit') from None
                    try:
                        errors = evaluate_schema(self.workflow.schemas[state['current']], response,
                                                 profile=self._schema_profile(human=True))
                    except SchemaEvaluationError:
                        return self._block(state, self._resource_reason(state) or 'schema_error')
                    if errors:
                        raise HumanResponseError('response_schema_invalid', response_schema_issues(errors))
                    try:
                        error = self._checks(state, state['current'], {'choice': choice, 'response': response}, step.get('validators', []))
                    except StoreError:
                        raise
                    except ValueError:
                        raise HumanResponseError('response_validation_failed') from None
                    if error:
                        raise HumanResponseError('response_validation_failed')
                elif response is not None:
                    raise HumanResponseError('response_not_allowed')
                if accounting_changed:
                    self._save(state)
                    if state['status'] == 'blocked':
                        return state
                self._event(state, 'human_decision', choice=choice, **({'response': response} if 'response_schema' in step else {}))
                self._advance(state, step['choices'][choice])
                if state['status'] == 'blocked':
                    return state
            elif choice is not None or response is not None:
                raise HumanResponseError('no_pending_choice')
            pending = state['pending']
            if pending is not None:
                receipt = self.store.load_receipt(self._storage_run_id, pending['id'])
                if receipt is not None:
                    validate_receipt(receipt, state, pending)
                    with self._observations.recovery():
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
        self._admit()
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
                if self._admission:
                    self._bounded_document(receipt, self._admission.policy.max_receipt_bytes)
                validate_receipt(receipt, state, invocation)
                if receipt['sha256'] != invocation['receipt_sha256'] or receipt['result']['token_usage'] != invocation['token_usage']:
                    raise ValueError('invocation ledger receipt mismatch')
                for name, binding in state['bindings'].items():
                    if binding['id'] == invocation['id']:
                        refs = self.workflow.definition['steps'][name].get('inputs', [])
                        dependencies = {ref: receipt['arguments']['artifact_bindings'][ref] for ref in refs}
                        if (name != invocation['step'] or self._output(receipt['result']['stdout']) != state['outputs'][name]
                                or binding['dependencies'] != dependencies):
                            raise ValueError('accepted output/binding differs from receipt')
                        if evaluate_schema(self.workflow.schemas[name], state['outputs'][name], profile=self._schema_profile()):
                            raise ValueError('accepted output failed schema validation')

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
            if self._admission and result['metadata'].get('failure_reason') in {
                    'output_limit', 'metadata_limit', 'event_limit', 'receipt_limit', 'result_limit'}:
                return self._block(state, self._resource_reason(state) or result['metadata']['failure_reason'])
            reason = ('cancelled' if result['exit_code'] == 130 else
                      'runtime_timeout' if result['timed_out'] else
                      'tool_choice_not_honored' if result['metadata'].get('failure_reason') == 'tool_choice_not_honored' else
                      'acquisition_failed' if result['metadata'].get('failure_reason') == 'acquisition_failed' else
                      'runtime_failure')
            return self._block(state, self._resource_reason(state) or reason)
        else:
            try:
                output = self._output(result['stdout'])
                errors = evaluate_schema(self.workflow.schemas[state['current']], output,
                                         profile=self._schema_profile())
                if errors:
                    error = '; '.join(errors)[:2048]
            except SchemaEvaluationError:
                return self._block(state, self._resource_reason(state) or 'schema_error')
            except WorkflowAdmissionError as exc:
                if exc.code == 'limit_exceeded':
                    return self._block(state, self._resource_reason(state) or 'output_limit')
                error = 'response must be one JSON value, optionally in a JSON code fence'
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
                if state['status'] == 'blocked':
                    return state
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
                if self._admission:
                    try:
                        arguments = self._snapshot(arguments, self._admission.policy.max_invocation_bytes)
                        rendered = self.workflow.artifacts[name].render(json.dumps(arguments))
                        if len(rendered.encode()) > self._admission.policy.max_invocation_bytes:
                            raise WorkflowAdmissionError('limit_exceeded')
                    except (WorkflowAdmissionError, ValueError, TypeError):
                        return self._block(state, 'invocation_limit')
                self._admit()
                attempt_id = uuid.uuid4().hex
                accounting_options = self._invocation_accounting(state, attempt_id, name)
                if self._admission:
                    # Even the failure form must fit before a remote operation
                    # can begin. A tiny host receipt cap cannot strand a call.
                    minimum = seal({'version': 1, 'run_id': state['run_id'], 'id': attempt_id, 'step': name,
                        'arguments_sha256': digest(arguments), 'arguments': arguments,
                        'result': self._failure_result({}, 'receipt_limit'), 'events': []})
                    try:
                        self._bounded_document(minimum, self._admission.policy.max_receipt_bytes,
                                               reserve=4096, reserve_nodes=_TERMINAL_NODES)
                    except WorkflowAdmissionError:
                        return self._block(state, 'receipt_limit')
                state['calls'] += 1
                state['attempt'] += 1
                state['pending'] = {'id': attempt_id, 'step': name, 'arguments_sha256': digest(arguments), 'arguments': arguments}
                state['invocations'].append({'id': attempt_id, 'step': name, 'arguments_sha256': digest(arguments),
                                             'status': 'pending', 'token_usage': None, 'receipt_sha256': None})
                self._event(state, 'invocation', attempt_id=attempt_id, call=state['calls'])
                self._save(state)
                if state['status'] == 'blocked':
                    return state
                events = []
                event_failure = None
                event_bytes = 2
                def record(event):
                    nonlocal event_failure, event_bytes
                    if self._admission:
                        try:
                            event = self._snapshot(event, self._admission.policy.max_event_bytes)
                            if type(event) is not dict or type(event.get('event')) is not str:
                                raise WorkflowAdmissionError('invalid_definition')
                        except WorkflowAdmissionError:
                            event_failure = 'event_limit'
                            return
                    if event['event'] not in {'text_delta', 'reasoning_delta', 'text', 'progress'}:
                        if len(events) >= 2048:
                            if self._admission:
                                event_failure = 'event_limit'
                                return
                            raise ValueError('runtime event limit exceeded')
                        if self._admission:
                            size = len(json.dumps(event, allow_nan=False).encode()) + 2
                            if event_bytes + size > self._admission.policy.max_event_bytes:
                                event_failure = 'event_limit'
                                return
                            event_bytes += size
                        events.append(event)
                    if self.on_event:
                        self.on_event(deepcopy({**event, 'step': name, 'attempt_id': attempt_id}) if self._admission
                                      else {**event, 'step': name, 'attempt_id': attempt_id})
                timeout = limits['timeout_s'] if state['deadline'] is None else min(limits['timeout_s'], max(0.001, state['deadline'] - self.clock()))
                policy = RunPolicy(allowed_tools=frozenset(step.get('tools', [])),
                                   read_roots=tuple(step.get('read_roots', [])),
                                   timeout_s=timeout, max_tool_rounds=self.workflow.config.limits.max_tool_rounds,
                                   **({'max_input_bytes': self._admission.policy.max_invocation_bytes} if self._admission else {}),
                                   **({'initial_tool': 'read_file'} if step.get('require_reads') and
                                      'initial_tool_v1' in getattr(self.runtime, 'capabilities', ()) else {}))
                self._check_ownership()
                observation_options = {}
                if self._observations.observer is not None:
                    from prosaic_runtime import InvocationScope
                    observation_options = {'observer': self._observations.observer,
                        'operation_context': InvocationScope(attempt_id, run_id=state['run_id'],
                            step_id=name if self._admission else None)}
                result = self.runtime.run(self.workflow.artifacts[name], json.dumps(arguments),
                                          cwd=self._cwd, policy=policy, on_event=record,
                                          cancelled=lambda: bool(event_failure) or self._runtime_cancelled(state),
                                          **({'acquisition': self.workflow.acquisitions[name]} if name in self.workflow.acquisitions else {}),
                                          **observation_options,
                                          **accounting_options)
                self._check_ownership()
                receipt = self._receipt(state, attempt_id, name, arguments, result, events, event_failure)
                self.store.save_receipt(self._storage_run_id, attempt_id, receipt, self._lease)
                self._accept(state, receipt)
        return state

    def _receipt(self, state, attempt_id, name, arguments, result, events, failure):
        if not self._admission:
            payload = asdict(result)
        else:
            policy = self._admission.policy
            payload = {key: getattr(result, key) for key in (
                'exit_code', 'stdout', 'stderr', 'token_usage', 'cost_usd', 'timed_out', 'metadata')}
            try:
                if type(payload['metadata']) is not dict:
                    raise WorkflowAdmissionError('invalid_definition')
                payload['metadata'] = self._snapshot(payload['metadata'], policy.max_metadata_bytes)
            except WorkflowAdmissionError:
                failure = failure or 'metadata_limit'
            try:
                valid_text = (type(payload['stdout']) is str and type(payload['stderr']) is str
                    and len(payload['stdout'].encode()) <= policy.max_output_bytes
                    and len(payload['stderr'].encode()) <= policy.max_output_bytes)
            except UnicodeError:
                valid_text = False
            if not valid_text:
                failure = failure or 'output_limit'
            cost, usage = payload['cost_usd'], payload['token_usage']
            if (type(payload['exit_code']) is not int or type(payload['timed_out']) is not bool
                    or (usage is not None and (type(usage) is not int or usage < 0 or usage.bit_length() > 256))
                    or (cost is not None and (type(cost) not in (int, float)
                        or (type(cost) is int and cost.bit_length() > 1023) or not math.isfinite(cost)))):
                failure = failure or 'result_limit'
            if failure is None:
                try:
                    payload = self._snapshot(payload, min(8_388_608,
                        policy.max_metadata_bytes + 2 * policy.max_output_bytes + 4096))
                except WorkflowAdmissionError:
                    failure = 'result_limit'
            if failure:
                payload = self._failure_result(payload, failure)
                events = []
        receipt = seal({'version': 1, 'run_id': state['run_id'], 'id': attempt_id, 'step': name,
                        'arguments_sha256': digest(arguments), 'arguments': arguments,
                        'result': payload, 'events': events})
        if self._admission:
            try:
                validate_receipt(receipt, state, state['pending'])
            except (ValueError, TypeError, OverflowError):
                # Invalid accounting/result shape cannot become immutable poison
                # evidence. Strip invalid lineage and retain known safe usage.
                safe = self._failure_result(payload, failure or 'result_limit')
                safe['metadata'].pop('accounting_v1', None)
                receipt['result'], receipt['events'] = safe, []
                receipt = seal(receipt)
            try:
                self._bounded_document(receipt, policy.max_receipt_bytes)
            except WorkflowAdmissionError:
                receipt['result'] = self._failure_result(payload, failure or 'receipt_limit')
                receipt['events'] = []
                receipt = seal(receipt)
                try:
                    self._bounded_document(receipt, policy.max_receipt_bytes)
                except WorkflowAdmissionError:
                    receipt['result']['metadata'].pop('accounting_v1', None)
                    receipt = seal(receipt)
                    self._bounded_document(receipt, policy.max_receipt_bytes)
            validate_receipt(receipt, state, state['pending'])
        return receipt

    def _failure_result(self, payload, reason):
        metadata = {'failure_reason': reason}
        # Keep safe accounting lineage where it fits, without retaining arbitrary
        # oversized product metadata or claiming truncated stdout is valid JSON.
        if type(payload.get('metadata')) is dict and 'accounting_v1' in payload['metadata']:
            try:
                metadata['accounting_v1'] = self._bounded_document(payload['metadata']['accounting_v1'], 2048)
            except WorkflowAdmissionError:
                pass
        usage = payload.get('token_usage')
        usage = usage if type(usage) is int and usage >= 0 and usage.bit_length() <= 256 else None
        return {'exit_code': 1, 'stdout': '', 'stderr': reason, 'token_usage': usage,
                'cost_usd': None, 'timed_out': bool(payload.get('timed_out')), 'metadata': metadata}
