"""Closed conversation errors: no source, binding or driver diagnostics."""
from .run_store import StoreError


class ConversationError(ValueError):
    CODES = frozenset({'bindingMismatch', 'identityMismatch', 'capabilityMissing',
        'invalidMessage', 'messageConflict', 'contextLimit', 'sessionLimit',
        'confirmationRequired', 'interactionStale', 'invalidInterpretation'})
    def __init__(self, code, limit=None):
        if type(code) is not str or code not in self.CODES:
            raise ValueError('invalid conversation error')
        self.code = code
        self.limit = limit if type(limit) is str and limit.isascii() and limit.isidentifier() else None
        super().__init__(code)


class SessionNotFound(StoreError):
    code = 'session_not_found'


class SessionAlreadyExists(StoreError):
    code = 'session_already_exists'


class SessionBusy(StoreError):
    code = 'session_busy'
