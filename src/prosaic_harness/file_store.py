"""Filesystem RunStore preserving existing safe, atomic run files."""
from contextlib import contextmanager
import os
from pathlib import Path
import threading

from .store import locked, read_bytes, write_json
from .run_store import (RunSnapshot, RunBusy, RunNotFound, RunAlreadyExists, StoreBusy,
                        LeaseLost, ReceiptConflict, RevisionConflict, StoreCorrupt,
                        encode_document, decode_document, revision_token,
                        validate_namespace, validate_id, validate_revision)


class _FileLease:
    def __init__(self, store, run_id):
        self.store, self.run_id, self.pid = store, run_id, os.getpid()
        self.active = True

    def check_valid(self):
        if not self.active or self.pid != os.getpid():
            raise LeaseLost('filesystem execution session is no longer owned')


class FileRunStore:
    def __init__(self, root, *, namespace='default'):
        self.root = Path(os.path.abspath(root))
        self.namespace = validate_namespace(namespace)
        self._legacy = False
        self._pid = os.getpid()
        self._closed = False
        self._sessions = set()
        self._mutex = threading.RLock()

    @classmethod
    def for_run_dir(cls, run_dir):
        store = cls(run_dir)
        store._legacy = True
        return store

    def _directory(self, run_id):
        if self._legacy:
            if run_id != 'legacy':
                raise ValueError('legacy store requires its bound addressing key')
            return self.root
        return self.root / self.namespace / validate_id(run_id)

    def check_ready(self):
        if self._pid != os.getpid() or self._closed:
            raise StoreBusy('store is closed or inherited; construct a new store')

    def initialize(self):
        self.check_ready()

    @contextmanager
    def lease(self, run_id):
        directory = self._directory(run_id)
        with self._mutex:
            self.check_ready()
            lock = locked(directory)
            try:
                lock.__enter__()
            except ValueError as exc:
                if str(exc) == 'run is locked by another process':
                    raise RunBusy('run is locked by another process') from None
                raise
            session = _FileLease(self, run_id)
            self._sessions.add(session)
        try:
            yield session
        finally:
            with self._mutex:
                session.active = False
                self._sessions.discard(session)
                lock.__exit__(None, None, None)

    def _validate_lease(self, run_id, lease):
        self.check_ready()
        if (not isinstance(lease, _FileLease) or lease.store is not self
                or lease.run_id != run_id or lease not in self._sessions):
            raise LeaseLost('lease does not own this store/run')
        lease.check_valid()

    def _read(self, path):
        try:
            return decode_document(read_bytes(path))
        except FileNotFoundError:
            raise RunNotFound('run document not found') from None
        except (ValueError, UnicodeError):
            raise StoreCorrupt('invalid run document') from None

    def load_run(self, run_id):
        self.check_ready()
        state = self._read(self._directory(run_id) / 'run.json')
        if not self._legacy and state.get('run_id') != run_id:
            raise StoreCorrupt('checkpoint identity does not match its address')
        return RunSnapshot(state, revision_token('file', self.namespace, run_id, state['sha256']))

    def create_run(self, run_id, state, lease):
        self._validate_lease(run_id, lease)
        encode_document(state)
        if not self._legacy and state.get('run_id') != run_id:
            raise StoreCorrupt('checkpoint identity does not match its address')
        try:
            self.load_run(run_id)
        except RunNotFound:
            pass
        else:
            raise RunAlreadyExists('run already exists; use resume or a new identity')
        write_json(self._directory(run_id) / 'run.json', state)
        return self.load_run(run_id).revision

    def save_run(self, run_id, state, expected_revision, lease):
        self._validate_lease(run_id, lease)
        validate_revision(expected_revision)
        if self.load_run(run_id).revision != expected_revision:
            raise RevisionConflict('checkpoint changed; refresh status')
        encode_document(state)
        if not self._legacy and state.get('run_id') != run_id:
            raise StoreCorrupt('checkpoint identity does not match its address')
        write_json(self._directory(run_id) / 'run.json', state)
        return self.load_run(run_id).revision

    def load_receipt(self, run_id, invocation_id):
        self.check_ready()
        path = self._directory(run_id) / 'attempts' / (validate_id(invocation_id) + '.json')
        try:
            receipt = self._read(path)
        except RunNotFound:
            return None
        if receipt.get('id') != invocation_id or (not self._legacy and receipt.get('run_id') != run_id):
            raise StoreCorrupt('receipt identity does not match its address')
        return receipt

    def save_receipt(self, run_id, invocation_id, receipt, lease):
        self._validate_lease(run_id, lease)
        content = encode_document(receipt)
        state = self.load_run(run_id).state
        if receipt.get('id') != validate_id(invocation_id) or receipt.get('run_id') != state['run_id']:
            raise StoreCorrupt('receipt identity does not match its address')
        existing = self.load_receipt(run_id, invocation_id)
        if existing is not None:
            if encode_document(existing) != content:
                raise ReceiptConflict('immutable receipt differs from committed evidence')
            return
        write_json(self._directory(run_id) / 'attempts' / (invocation_id + '.json'), receipt)

    def close(self):
        with self._mutex:
            if self._sessions:
                raise StoreBusy('drain active executions before closing the store')
            self._closed = True

    def __enter__(self):
        self.check_ready()
        return self

    def __exit__(self, *args):
        self.close()
