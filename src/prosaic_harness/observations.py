"""Project durable workflow state into optional, owned safe observations."""
import uuid
from contextlib import contextmanager

from .run_store import validate_id

_REASONS = frozenset({'cancelled', 'invocation_timeout', 'inspection_timeout',
                     'budget_exceeded', 'accounting_failed', 'incomplete_response',
                     'admission_failure', 'critical_hook_error', 'execution_failure'})


class CommittedObserver:
    """One sequence per public execution, independent of critical evidence."""
    def __init__(self, observer):
        if observer is not None and not callable(observer):
            raise ValueError('observer must be callable')
        self.observer = observer
        self.emitter = None
        self.recovering = False

    def begin(self, run_id):
        from prosaic_runtime import InvocationScope, ObserverEmitter
        self.emitter = ObserverEmitter(self.observer, source='harness', scope=InvocationScope(
            uuid.uuid4().hex, run_id=validate_id(run_id)))

    @contextmanager
    def recovery(self):
        self.recovering = True
        try:
            yield
        finally:
            self.recovering = False

    def emit_committed(self, state, revision, *, recovery=False, started=False):
        kind = ('blocked_committed' if state['status'] == 'blocked' else
                'waiting_committed' if state['status'] == 'waiting' else
                'run_completed' if state['status'] in {'completed', 'rejected'} else
                'run_started' if started else
                'recovery_committed' if recovery else 'transition_committed')
        fields = {'outcome': state['status'], 'revision': revision, 'calls': state['calls']}
        reason = state.get('reason')
        if reason is not None:
            fields['reason'] = reason if type(reason) is str and reason in _REASONS else 'unknown'
        self.emitter.emit(kind, **fields)
