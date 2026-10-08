"""Public synchronous persistence contract; no database dependencies."""
from dataclasses import dataclass
import hashlib
import json
import re
from typing import ContextManager, Protocol

from .contracts import verify_seal
from .store import MAX_BYTES, parse_json

STORAGE_CONTRACT_VERSION = 1


class StoreError(ValueError):
    """A safe public error. Driver details must not be passed as its message."""
    code = 'store_error'

    def __init__(self, message=None):
        super().__init__(message or self.code)


class StoreUninitialized(StoreError):
    code = 'store_uninitialized'


class StoreIncompatible(StoreError):
    code = 'store_incompatible'


class StoreUnavailable(StoreError):
    code = 'store_unavailable'

    def __init__(self, message=None, *, outcome_unknown=False):
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


class StoreBusy(StoreError):
    code = 'store_busy'


class RunBusy(StoreError):
    code = 'run_busy'


class LeaseLost(StoreError):
    code = 'lease_lost'


class RevisionConflict(StoreError):
    code = 'revision_conflict'


class ReceiptConflict(StoreError):
    code = 'receipt_conflict'


class RunNotFound(StoreError):
    code = 'run_not_found'


class RunAlreadyExists(StoreError):
    code = 'run_already_exists'


class StoreCorrupt(StoreError):
    code = 'store_corrupt'


@dataclass(frozen=True)
class RunSnapshot:
    state: dict
    revision: str


class LeaseSession(Protocol):
    def check_valid(self) -> None: ...


class RunStore(Protocol):
    namespace: str
    def initialize(self) -> None: ...
    def check_ready(self) -> None: ...
    def lease(self, run_id: str) -> ContextManager[LeaseSession]: ...
    def load_run(self, run_id: str) -> RunSnapshot: ...
    def create_run(self, run_id: str, state: dict, lease: LeaseSession) -> str: ...
    def save_run(self, run_id: str, state: dict, expected_revision: str, lease: LeaseSession) -> str: ...
    def load_receipt(self, run_id: str, invocation_id: str) -> dict | None: ...
    def save_receipt(self, run_id: str, invocation_id: str, receipt: dict, lease: LeaseSession) -> None: ...
    def close(self) -> None: ...


def validate_namespace(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise ValueError('namespace must be a bounded ASCII identifier')
    return value


def validate_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}', value):
        raise ValueError('run/invocation identifier must be lowercase UUID hex')
    return value


def validate_revision(value):
    if not isinstance(value, str) or not value or len(value.encode('utf-8')) > 512:
        raise ValueError('expected_revision must be a bounded token')


def revision_token(backend, namespace, run_id, revision):
    return hashlib.sha256(json.dumps([backend, namespace, run_id, revision],
                                     sort_keys=True).encode()).hexdigest()


def encode_document(value):
    try:
        if not isinstance(value, dict):
            raise ValueError('not an object')
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_BYTES:
            raise ValueError('too large')
        verify_seal(value)
        return encoded
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise StoreCorrupt('checkpoint/receipt is not bounded, finite, sealed JSON') from None


def decode_document(content):
    try:
        if isinstance(content, str):
            content = content.encode('utf-8')
        if not isinstance(content, bytes) or len(content) > MAX_BYTES:
            raise ValueError('too large')
        value = parse_json(content.decode('utf-8'))
        encode_document(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise StoreCorrupt('checkpoint/receipt is not bounded, finite, sealed JSON') from None
