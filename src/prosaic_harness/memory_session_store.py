"""Explicit single-process, non-durable conversation testing store."""
from contextlib import contextmanager
import os
import threading

from .conversation_bindings import ConversationScope
from .conversation_errors import SessionNotFound, SessionAlreadyExists, SessionBusy
from .run_store import (LeaseLost, RevisionConflict, ReceiptConflict, StoreUninitialized,
    StoreUnavailable, StoreCorrupt, validate_id, validate_namespace, validate_revision)
from .session_store import SessionSnapshot
from .session_codec import digest, encode
from .session_contracts import (encode_session, decode_session, verify_receipt, match_receipt)


class MemoryLease:
    def __init__(self,store,session_id,scope):
        self.store,self.session_id,self.scope=store,session_id,scope.to_dict()
        self.pid,self.active=os.getpid(),True
    def check_valid(self):
        if not self.active or self.pid!=os.getpid() or self.store._closed:
            raise LeaseLost()


class MemorySessionStore:
    durable=False
    def __init__(self,*,namespace):
        self._namespace=validate_namespace(namespace)
        self._pid=os.getpid()
        self._closed=False
        self._initialized=False
        self._records={}
        self._receipts={}
        self._locks={}
        self._mutex=threading.RLock()
        self._leases=set()
    @property
    def namespace(self): return self._namespace
    def initialize(self):
        if self._closed or self._pid!=os.getpid(): raise StoreUnavailable()
        self._initialized=True
    def check_ready(self):
        if self._closed or self._pid!=os.getpid(): raise StoreUnavailable()
        if not self._initialized: raise StoreUninitialized()
    def _scope(self,scope):
        if type(scope) is not ConversationScope or scope.namespace!=self.namespace:
            raise SessionNotFound()
        return scope.to_dict()
    def _lease(self,session_id,lease,scope):
        self.check_ready()
        validate_id(session_id)
        value=self._scope(scope)
        if (type(lease) is not MemoryLease or lease.store is not self or lease.session_id!=session_id
                or lease.scope!=value or lease not in self._leases):
            raise LeaseLost()
        lease.check_valid()
    @contextmanager
    def lease(self,session_id,*,scope):
        self.check_ready()
        validate_id(session_id)
        self._scope(scope)
        with self._mutex:
            lock=self._locks.setdefault(session_id,threading.Lock())
        if not lock.acquire(blocking=False): raise SessionBusy()
        lease=MemoryLease(self,session_id,scope)
        with self._mutex: self._leases.add(lease)
        try: yield lease
        finally:
            lease.active=False
            with self._mutex: self._leases.discard(lease)
            lock.release()
    def _revision(self,session_id,state):
        return digest(['memory',self.namespace,session_id,state['scope'],state['sha256']])
    def load_session(self,session_id,*,scope):
        self.check_ready()
        validate_id(session_id)
        owner=self._scope(scope)
        with self._mutex:
            content=self._records.get(session_id)
            if content is None: raise SessionNotFound()
            state=decode_session(content)
            if state['scope']!=owner: raise SessionNotFound()
            if state['sessionId']!=session_id: raise StoreCorrupt()
            return SessionSnapshot(session_id,state,self._revision(session_id,state))
    def _content(self,session_id,state,scope):
        content=encode_session(state)
        admitted=decode_session(content)
        if admitted['sessionId']!=session_id or admitted['scope']!=self._scope(scope): raise StoreCorrupt()
        return content
    def create_session(self,session_id,state,lease,*,scope):
        self._lease(session_id,lease,scope)
        content=self._content(session_id,state,scope)
        with self._mutex:
            if session_id in self._records:
                self.load_session(session_id,scope=scope)
                raise SessionAlreadyExists()
            self._records[session_id]=content
        return self._revision(session_id,decode_session(content))
    def save_session(self,session_id,state,expected_revision,lease,*,scope):
        self._lease(session_id,lease,scope)
        validate_revision(expected_revision)
        with self._mutex:
            current=self.load_session(session_id,scope=scope)
            if current.revision!=expected_revision: raise RevisionConflict()
            content=self._content(session_id,state,scope)
            admitted=decode_session(content)
            from .session_contracts import validate_session_transition
            validate_session_transition(current.state,admitted)
            self._records[session_id]=content
        return self._revision(session_id,admitted)
    def load_receipt(self,session_id,invocation_id,*,scope):
        validate_id(invocation_id)
        with self._mutex:
            state=self.load_session(session_id,scope=scope).state
            content=self._receipts.get((session_id,invocation_id))
            if content is None: return None
            from .session_codec import decode
            return match_receipt(state,decode(content))
    def save_receipt(self,session_id,invocation_id,receipt,lease,*,scope):
        self._lease(session_id,lease,scope)
        validate_id(invocation_id)
        value=verify_receipt(receipt)
        if value['invocationId']!=invocation_id: raise StoreCorrupt()
        content=encode(value)
        with self._mutex:
            state=self.load_session(session_id,scope=scope).state
            old=self._receipts.get((session_id,invocation_id))
            if old is not None and old!=content: raise ReceiptConflict()
            match_receipt(state,value)
            self._receipts[(session_id,invocation_id)]=content
    def close(self):
        with self._mutex:
            self._closed=True
            for lease in tuple(self._leases): lease.active=False
