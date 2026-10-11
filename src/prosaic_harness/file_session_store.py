"""Private, descriptor-pinned durable conversation records on Linux/macOS.

The root is explicit host configuration. Initialization creates private directories;
ordinary reads never create a path. A lease retains every directory descriptor and
checks their incarnations before writing or dispatching through ``check_valid``.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import secrets
import stat
import threading

from .conversation_bindings import ConversationScope
from .conversation_errors import ConversationError, SessionNotFound, SessionAlreadyExists, SessionBusy
from .run_store import (LeaseLost, RevisionConflict, ReceiptConflict, StoreBusy,
    StoreUninitialized, StoreIncompatible, StoreUnavailable, StoreCorrupt,
    validate_namespace, validate_id, validate_revision)
from .session_codec import decode, digest, encode
from .session_contracts import (encode_session, verify_session, verify_receipt,
    match_receipt, validate_session_transition)
from .session_store import SessionSnapshot


_MAX_BYTES = 8 * 1024 * 1024
_MARKER = b'{"storageContract":1,"version":1}'


def _identity(fd):
    value=os.fstat(fd)
    return value.st_dev,value.st_ino


def _private(value, *, directory=False):
    appropriate=stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode)
    if (not appropriate or value.st_uid!=os.getuid()
            or stat.S_IMODE(value.st_mode)!=(0o700 if directory else 0o600)
            or (not directory and value.st_nlink!=1)):
        raise StoreUnavailable()


class _Directories:
    def __init__(self):
        self.fds=[os.open('/',os.O_RDONLY|os.O_DIRECTORY)]
        self.links=[]
    @property
    def fd(self): return self.fds[-1]
    def append(self,name,*,create=False,private=False):
        parent=self.fd
        if create:
            try:
                os.mkdir(name,mode=0o700,dir_fd=parent)
                os.fsync(parent)
            except FileExistsError:
                pass
        child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
        self.fds.append(child)
        self.links.append((parent,name,child,private))
        if private: _private(os.fstat(child),directory=True)
        return child
    def check(self):
        for parent,name,child,private in self.links:
            value=os.stat(name,dir_fd=parent,follow_symlinks=False)
            if not stat.S_ISDIR(value.st_mode) or (value.st_dev,value.st_ino)!=_identity(child):
                raise LeaseLost()
            if private: _private(value,directory=True)
    def close(self):
        for fd in reversed(self.fds): os.close(fd)
        self.fds=[]


def _read(parent,name,*,maximum=_MAX_BYTES):
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
    try:
        before=os.fstat(fd)
        try: _private(before)
        except StoreUnavailable: raise StoreCorrupt() from None
        if before.st_size>maximum: raise StoreCorrupt()
        chunks=[]
        remaining=maximum+1
        while remaining:
            chunk=os.read(fd,min(65536,remaining))
            if not chunk: break
            chunks.append(chunk)
            remaining-=len(chunk)
        after=os.fstat(fd)
        named=os.stat(name,dir_fd=parent,follow_symlinks=False)
        if ((before.st_dev,before.st_ino)!=(named.st_dev,named.st_ino) or
                (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns)):
            raise StoreCorrupt()
        content=b''.join(chunks)
        if len(content)>maximum or not content: raise StoreCorrupt()
        return content
    finally:
        os.close(fd)


def _fill(fd,content):
    with os.fdopen(fd,'wb') as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _exclusive_write(parent,name,content):
    """No partial final record is ever treated as absent after a crashed write."""
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
    _fill(fd,content)
    os.fsync(parent)


def _replace_write(parent,name,content):
    existing=os.stat(name,dir_fd=parent,follow_symlinks=False)
    _private(existing)
    temporary='.session-'+secrets.token_hex(16)
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
    try:
        _fill(fd,content)
        # A replacement never follows the destination, even if a hostile actor
        # changes it after the regular-file check above.
        os.replace(temporary,name,src_dir_fd=parent,dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try: os.unlink(temporary,dir_fd=parent)
        except FileNotFoundError: pass


class _FileSessionLease:
    def __init__(self,store,session_id,owner,directories,session_fd,receipt_fd,lock_fd):
        self.store,self.session_id,self.scope=store,session_id,owner
        self.pid,self.active=os.getpid(),True
        self.directories=directories
        self.session_fd,self.receipt_fd,self.lock_fd=session_fd,receipt_fd,lock_fd
        self.lock_identity=_identity(lock_fd)
    def check_valid(self):
        if (not self.active or self.pid!=os.getpid() or self.store._pid!=os.getpid()
                or self.store._closed or self not in self.store._leases):
            raise LeaseLost()
        try:
            self.directories.check()
            lock=os.stat('session.lock',dir_fd=self.session_fd,follow_symlinks=False)
            if (not stat.S_ISREG(lock.st_mode) or (lock.st_dev,lock.st_ino)!=self.lock_identity):
                raise LeaseLost()
            _private(lock)
        except (OSError,StoreUnavailable):
            raise LeaseLost() from None


class FileSessionStore:
    """Explicit durable private file store; no fallback and no implicit workspace."""
    durable=True
    def __init__(self,root: Path,*,namespace: str):
        value=Path(root)
        if not value.is_absolute() or '..' in value.parts or value==Path('/'):
            raise ValueError('session root must be an explicit absolute private directory')
        self._root=value
        self._namespace=validate_namespace(namespace)
        self._pid=os.getpid()
        self._closed=False
        self._incarnation=None
        self._leases=set()
        self._mutex=threading.RLock()
    @property
    def root(self): return self._root
    @property
    def namespace(self): return self._namespace
    def _available(self):
        if self._closed or self._pid!=os.getpid(): raise StoreUnavailable()
    def _scope(self,scope):
        if type(scope) is not ConversationScope or scope.namespace!=self.namespace:
            raise SessionNotFound()
        return scope.to_dict()
    def _directories(self,*,create=False):
        paths=_Directories()
        try:
            for index,part in enumerate(self.root.parts[1:]):
                is_root=index==len(self.root.parts)-2
                paths.append(part,create=create and is_root,private=is_root)
            root_identity=_identity(paths.fd)
            paths.append(self.namespace,create=create,private=True)
            incarnation=(root_identity,_identity(paths.fd))
            if self._incarnation is not None and incarnation!=self._incarnation:
                raise StoreUnavailable()
            return paths,incarnation
        except BaseException:
            paths.close()
            raise
    def _ready(self,paths,incarnation):
        try: marker=_read(paths.fd,'.conversation-store.json',maximum=1024)
        except FileNotFoundError: raise StoreUninitialized() from None
        if marker!=_MARKER: raise StoreIncompatible()
        paths.check()
        with self._mutex:
            if self._incarnation is not None and self._incarnation!=incarnation:
                raise StoreUnavailable()
            self._incarnation=incarnation
    def initialize(self):
        self._available()
        paths=None
        try:
            paths,incarnation=self._directories(create=True)
            try: _exclusive_write(paths.fd,'.conversation-store.json',_MARKER)
            except FileExistsError: pass
            self._ready(paths,incarnation)
        except OSError:
            raise StoreUnavailable() from None
        finally:
            if paths is not None: paths.close()
    def check_ready(self):
        self._available()
        paths=None
        try:
            paths,incarnation=self._directories()
            self._ready(paths,incarnation)
        except FileNotFoundError:
            raise StoreUninitialized() from None
        except OSError:
            raise StoreUnavailable() from None
        finally:
            if paths is not None: paths.close()
    @contextmanager
    def _read_directory(self,session_id):
        self.check_ready()
        paths=None
        try:
            paths,incarnation=self._directories()
            self._ready(paths,incarnation)
            try: paths.append(session_id,private=True)
            except FileNotFoundError: raise SessionNotFound() from None
            yield paths
            paths.check()
        except OSError:
            raise StoreUnavailable() from None
        finally:
            if paths is not None: paths.close()
    def _snapshot(self,session_id,parent,owner):
        try: content=_read(parent,'session.json')
        except FileNotFoundError: raise SessionNotFound() from None
        try: state=decode(content)
        except (ValueError,TypeError,UnicodeError): raise StoreCorrupt() from None
        if type(state) is not dict: raise StoreCorrupt()
        saved_scope=state.get('scope')
        if type(saved_scope) is not dict or set(saved_scope)!=set(owner): raise StoreCorrupt()
        try:
            ConversationScope(saved_scope['namespace'],saved_scope['environment'],saved_scope['application'],
                saved_scope['tenant'],saved_scope['actor'],saved_scope['billingAccount'])
        except ConversationError: raise StoreCorrupt() from None
        if saved_scope!=owner: raise SessionNotFound()
        state=verify_session(state)
        if state['sessionId']!=session_id: raise StoreCorrupt()
        revision=digest(['file',self.namespace,session_id,state['scope'],state['sha256']])
        return SessionSnapshot(session_id,state,revision)
    def load_session(self,session_id,*,scope):
        validate_id(session_id)
        owner=self._scope(scope)
        with self._read_directory(session_id) as paths:
            return self._snapshot(session_id,paths.fd,owner)
    @contextmanager
    def lease(self,session_id,*,scope):
        self.check_ready()
        validate_id(session_id)
        owner=self._scope(scope)
        paths=None
        lock_fd=None
        lease=None
        try:
            paths,incarnation=self._directories()
            self._ready(paths,incarnation)
            session_fd=paths.append(session_id,create=True,private=True)
            try: self._snapshot(session_id,session_fd,owner)
            except SessionNotFound:
                # An existing foreign record must not look like free space.
                try: os.stat('session.json',dir_fd=session_fd,follow_symlinks=False)
                except FileNotFoundError: pass
                else: raise SessionNotFound() from None
            receipt_fd=paths.append('receipts',create=True,private=True)
            try:
                lock_fd=os.open('session.lock',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,
                    0o600,dir_fd=session_fd)
                os.fsync(lock_fd)
                os.fsync(session_fd)
            except FileExistsError:
                lock_fd=os.open('session.lock',os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=session_fd)
            _private(os.fstat(lock_fd))
            try: fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise SessionBusy() from None
            lease=_FileSessionLease(self,session_id,owner,paths,session_fd,receipt_fd,lock_fd)
            with self._mutex: self._leases.add(lease)
            lease.check_valid()
            # Creation may have raced the first owner check before this lock.
            try: self._snapshot(session_id,session_fd,owner)
            except SessionNotFound:
                try: os.stat('session.json',dir_fd=session_fd,follow_symlinks=False)
                except FileNotFoundError: pass
                else: raise SessionNotFound() from None
            yield lease
        except OSError:
            raise StoreUnavailable() from None
        finally:
            if lease is not None:
                lease.active=False
                with self._mutex: self._leases.discard(lease)
            if lock_fd is not None:
                os.close(lock_fd)
            if paths is not None: paths.close()
    def _lease(self,session_id,lease,scope):
        self._available()
        validate_id(session_id)
        owner=self._scope(scope)
        if (type(lease) is not _FileSessionLease or lease.store is not self or
                lease.session_id!=session_id or lease.scope!=owner):
            raise LeaseLost()
        lease.check_valid()
        return owner
    def _content(self,session_id,state,owner):
        value=verify_session(state)
        if value['sessionId']!=session_id or value['scope']!=owner: raise StoreCorrupt()
        return value,encode_session(value)
    def create_session(self,session_id,state,lease,*,scope):
        owner=self._lease(session_id,lease,scope)
        value,content=self._content(session_id,state,owner)
        try:
            try: self._snapshot(session_id,lease.session_fd,owner)
            except SessionNotFound:
                try: os.stat('session.json',dir_fd=lease.session_fd,follow_symlinks=False)
                except FileNotFoundError: pass
                else: raise SessionNotFound() from None
            else: raise SessionAlreadyExists()
            lease.check_valid()
            _exclusive_write(lease.session_fd,'session.json',content)
            lease.check_valid()
            return digest(['file',self.namespace,session_id,value['scope'],value['sha256']])
        except OSError:
            raise StoreUnavailable(outcome_unknown=True) from None
    def save_session(self,session_id,state,expected_revision,lease,*,scope):
        owner=self._lease(session_id,lease,scope)
        validate_revision(expected_revision)
        current=self._snapshot(session_id,lease.session_fd,owner)
        if current.revision!=expected_revision: raise RevisionConflict()
        value=validate_session_transition(current.state,state)
        value,content=self._content(session_id,value,owner)
        try:
            lease.check_valid()
            _replace_write(lease.session_fd,'session.json',content)
            lease.check_valid()
            return digest(['file',self.namespace,session_id,value['scope'],value['sha256']])
        except OSError:
            raise StoreUnavailable(outcome_unknown=True) from None
    def _receipt(self,state,invocation_id,parent):
        try: content=_read(parent,invocation_id+'.json',maximum=min(_MAX_BYTES,state['policy']['maxReceiptBytes']))
        except FileNotFoundError: return None
        except OSError: raise StoreCorrupt() from None
        try: value=decode(content)
        except (ValueError,TypeError,UnicodeError): raise StoreCorrupt() from None
        if type(value) is not dict or value.get('invocationId')!=invocation_id: raise StoreCorrupt()
        return match_receipt(state,value)
    def load_receipt(self,session_id,invocation_id,*,scope):
        validate_id(session_id)
        validate_id(invocation_id)
        owner=self._scope(scope)
        with self._read_directory(session_id) as paths:
            state=self._snapshot(session_id,paths.fd,owner).state
            try: paths.append('receipts',private=True)
            except FileNotFoundError: raise StoreCorrupt() from None
            return self._receipt(state,invocation_id,paths.fd)
    def save_receipt(self,session_id,invocation_id,receipt,lease,*,scope):
        owner=self._lease(session_id,lease,scope)
        validate_id(invocation_id)
        state=self._snapshot(session_id,lease.session_fd,owner).state
        value=verify_receipt(receipt)
        if value['invocationId']!=invocation_id: raise StoreCorrupt()
        content=encode(value)
        existing=self._receipt(state,invocation_id,lease.receipt_fd)
        if existing is not None:
            if encode(existing)!=content: raise ReceiptConflict()
            return
        match_receipt(state,value)
        try:
            lease.check_valid()
            _exclusive_write(lease.receipt_fd,invocation_id+'.json',content)
            lease.check_valid()
        except FileExistsError:
            existing=self._receipt(state,invocation_id,lease.receipt_fd)
            if existing is None or encode(existing)!=content: raise ReceiptConflict() from None
        except OSError:
            raise StoreUnavailable(outcome_unknown=True) from None
    def close(self):
        with self._mutex:
            if self._leases: raise StoreBusy()
            self._closed=True
