"""Durable private session storage, independent of legacy RunStore files."""
from dataclasses import replace
import os
from pathlib import Path
import stat

import pytest

from prosaic_harness import (StoreCorrupt, StoreUninitialized, StoreUnavailable,
    LeaseLost, RevisionConflict, ReceiptConflict, SessionNotFound, SessionBusy)
from prosaic_harness.session_contracts import new_session, seal
from support.conversations import binding_factory, scope
from test_session_contracts import reserve, receipt, mark_dispatch, SID, AID


@pytest.fixture
def store_type():
    from prosaic_harness.file_session_store import FileSessionStore
    return FileSessionStore


@pytest.fixture
def file_store(tmp_path,store_type):
    store=store_type(tmp_path/'private',namespace='test')
    store.initialize()
    yield store
    store.close()


def create(store,scope,binding_factory,*,running=False):
    state=new_session(SID,scope,binding_factory())
    if running: state=mark_dispatch(reserve(state),AID)
    with store.lease(SID,scope=scope) as lease:
        revision=store.create_session(SID,state,lease,scope=scope)
    return state,revision


def test_root_is_explicit_absolute_and_initialization_is_required(tmp_path,store_type):
    with pytest.raises(TypeError): store_type(namespace='test')
    with pytest.raises(ValueError): store_type(Path('relative'),namespace='test')
    store=store_type(tmp_path/'missing',namespace='test')
    with pytest.raises(StoreUninitialized): store.check_ready()
    assert not (tmp_path/'missing').exists()
    store.initialize()
    store.check_ready()
    store.close()


def test_restart_reads_canonical_owned_snapshot(file_store,store_type,scope,binding_factory):
    state,revision=create(file_store,scope,binding_factory)
    restarted=store_type(file_store.root,namespace='test')
    restarted.check_ready()
    loaded=restarted.load_session(SID,scope=scope)
    assert loaded.state==state and loaded.revision==revision
    loaded.state['turns'].append({'forged':True})
    assert restarted.load_session(SID,scope=scope).state['turns']==[]
    restarted.close()


def test_file_store_shared_conformance(file_store,scope,binding_factory):
    from prosaic_harness.testing import assert_session_store_contract
    state=reserve(new_session(SID,scope,binding_factory()))
    assert_session_store_contract(file_store,scope=scope,state=state,
        receipt=receipt(mark_dispatch(state,AID)))


def test_foreign_owner_cannot_read_or_write(file_store,scope,binding_factory):
    state,revision=create(file_store,scope,binding_factory,running=True)
    with file_store.lease(SID,scope=scope) as lease:
        file_store.save_receipt(SID,AID,receipt(state),lease,scope=scope)
    foreign=replace(scope,actor='other')
    with pytest.raises(SessionNotFound): file_store.load_session(SID,scope=foreign)
    with pytest.raises(SessionNotFound): file_store.load_receipt(SID,AID,scope=foreign)
    with pytest.raises(SessionNotFound):
        with file_store.lease(SID,scope=foreign) as lease:
            file_store.save_session(SID,state,revision,lease,scope=foreign)


def test_lease_is_scoped_to_store_address_owner_and_lifetime(file_store,store_type,scope,binding_factory):
    other=store_type(file_store.root,namespace='test')
    state=new_session(SID,scope,binding_factory())
    with file_store.lease(SID,scope=scope) as lease:
        with pytest.raises(LeaseLost): other.create_session(SID,state,lease,scope=scope)
        with pytest.raises(LeaseLost): file_store.create_session('c'*32,state,lease,scope=scope)
        with pytest.raises(LeaseLost): file_store.create_session(SID,state,lease,scope=replace(scope,actor='other'))
        with pytest.raises(SessionBusy):
            with other.lease(SID,scope=scope): pass
    with pytest.raises(LeaseLost): file_store.create_session(SID,state,lease,scope=scope)
    other.close()


def test_receipt_survives_restart_before_snapshot_adoption(file_store,store_type,scope,binding_factory):
    state,_=create(file_store,scope,binding_factory,running=True)
    with file_store.lease(SID,scope=scope) as lease:
        saved=receipt(state)
        file_store.save_receipt(SID,AID,saved,lease,scope=scope)
    restarted=store_type(file_store.root,namespace='test')
    assert restarted.load_receipt(SID,AID,scope=scope)==saved
    assert restarted.load_session(SID,scope=scope).state['attempts'][AID]['receiptAdopted'] is False
    restarted.close()


@pytest.mark.parametrize('content',[b'',b'{',b'{}',b'[]',b'null',b'{"version":1,"version":1}'])
def test_corrupt_receipt_is_never_missing(file_store,scope,binding_factory,content):
    create(file_store,scope,binding_factory,running=True)
    assert file_store.load_receipt(SID,AID,scope=scope) is None
    path=file_store.root/'test'/SID/'receipts'/(AID+'.json')
    path.write_bytes(content)
    path.chmod(0o600)
    with pytest.raises(StoreCorrupt): file_store.load_receipt(SID,AID,scope=scope)


def test_tampered_snapshot_and_oversized_receipt_are_explicit(file_store,scope,binding_factory):
    state,_=create(file_store,scope,binding_factory,running=True)
    path=file_store.root/'test'/SID/'receipts'/(AID+'.json')
    with path.open('wb') as handle: handle.truncate(8*1024*1024+1)
    path.chmod(0o600)
    with pytest.raises(StoreCorrupt): file_store.load_receipt(SID,AID,scope=scope)
    from prosaic_harness.session_codec import encode
    (file_store.root/'test'/SID/'session.json').write_bytes(encode(state|{'bindingVersion':'tampered'}))
    with pytest.raises(StoreCorrupt): file_store.load_session(SID,scope=scope)


def test_created_directories_and_records_are_private(file_store,scope,binding_factory):
    state,_=create(file_store,scope,binding_factory,running=True)
    with file_store.lease(SID,scope=scope) as lease:
        file_store.save_receipt(SID,AID,receipt(state),lease,scope=scope)
    for path in [file_store.root,*file_store.root.rglob('*')]:
        permissions=stat.S_IMODE(path.stat().st_mode)
        assert permissions==(0o700 if path.is_dir() else 0o600)


def test_public_root_permissions_fail_explicitly(tmp_path,store_type):
    root=tmp_path/'public'
    root.mkdir(mode=0o755)
    with pytest.raises(StoreUnavailable): store_type(root,namespace='test').initialize()
    assert stat.S_IMODE(root.stat().st_mode)==0o755


@pytest.mark.parametrize('component',['root','namespace','session','receipt'])
def test_symlinks_cannot_escape_store(tmp_path,file_store,store_type,scope,binding_factory,component):
    state,_=create(file_store,scope,binding_factory,running=True)
    outside=tmp_path/'outside'
    outside.mkdir()
    if component=='root':
        root=tmp_path/'linked'
        root.symlink_to(outside,target_is_directory=True)
        with pytest.raises(StoreUnavailable): store_type(root,namespace='test').initialize()
        assert list(outside.iterdir())==[]
        return
    if component=='namespace': path=file_store.root/'test'
    elif component=='session': path=file_store.root/'test'/SID
    else: path=file_store.root/'test'/SID/'receipts'/(AID+'.json')
    if path.exists(): path.rename(path.with_name(path.name+'.old'))
    path.symlink_to(outside,target_is_directory=True)
    with pytest.raises((StoreCorrupt,StoreUnavailable,LeaseLost)):
        if component=='receipt': file_store.load_receipt(SID,AID,scope=scope)
        else: file_store.load_session(SID,scope=scope)
    assert list(outside.iterdir())==[]


@pytest.mark.parametrize('component',['root','namespace','session','receipts','lock'])
def test_replaced_directory_or_lock_invalidates_pinned_lease(file_store,scope,binding_factory,component):
    state=new_session(SID,scope,binding_factory())
    with file_store.lease(SID,scope=scope) as lease:
        paths={'root':file_store.root,'namespace':file_store.root/'test',
            'session':file_store.root/'test'/SID,'receipts':file_store.root/'test'/SID/'receipts',
            'lock':file_store.root/'test'/SID/'session.lock'}
        path=paths[component]
        old=path.with_name(path.name+'.old')
        path.rename(old)
        if component=='lock': path.write_bytes(b''); path.chmod(0o600)
        else: path.mkdir(mode=0o700)
        with pytest.raises(LeaseLost): lease.check_valid()
        with pytest.raises(LeaseLost): file_store.create_session(SID,state,lease,scope=scope)
        assert not (paths['session']/'session.json').exists()


def test_address_traversal_never_creates_files(file_store,scope):
    for sid in ['../escape','a'*31,'A'*32,'/private/tmp/escape']:
        with pytest.raises(ValueError):
            with file_store.lease(sid,scope=scope): pass
    assert list((file_store.root/'test').glob('[a-f0-9]'*32))==[]


def test_store_and_lease_cannot_be_inherited(file_store,scope,binding_factory):
    with file_store.lease(SID,scope=scope) as lease:
        lease.pid=-1
        with pytest.raises(LeaseLost): lease.check_valid()
    file_store._pid=-1
    with pytest.raises(StoreUnavailable): file_store.load_session(SID,scope=scope)
    file_store._pid=os.getpid()


def test_missing_root_parent_is_not_created(tmp_path,store_type):
    root=tmp_path/'not-owned'/'private'
    with pytest.raises(StoreUnavailable): store_type(root,namespace='test').initialize()
    assert not root.parent.exists()


def test_read_only_root_fails_before_creating_namespace(tmp_path,store_type):
    root=tmp_path/'readonly'
    root.mkdir(mode=0o500)
    with pytest.raises(StoreUnavailable): store_type(root,namespace='test').initialize()
    assert list(root.iterdir())==[]


def test_directory_permission_drift_invalidates_active_lease(file_store,scope,binding_factory):
    state=new_session(SID,scope,binding_factory())
    with file_store.lease(SID,scope=scope) as lease:
        (file_store.root/'test'/SID/'receipts').chmod(0o755)
        with pytest.raises(LeaseLost): lease.check_valid()
        with pytest.raises(LeaseLost): file_store.create_session(SID,state,lease,scope=scope)


def test_hardlinked_receipt_cannot_read_outside_private_root(tmp_path,file_store,scope,binding_factory):
    from prosaic_harness.session_codec import encode
    state,_=create(file_store,scope,binding_factory,running=True)
    outside=tmp_path/'outside-receipt.json'
    outside.write_bytes(encode(receipt(state)))
    outside.chmod(0o600)
    os.link(outside,file_store.root/'test'/SID/'receipts'/(AID+'.json'))
    with pytest.raises(StoreCorrupt): file_store.load_receipt(SID,AID,scope=scope)


def test_initialization_and_new_records_fsync_files_and_parent_links(tmp_path,store_type,scope,binding_factory,monkeypatch):
    # Keep real fsync; record its target to catch lost directory durability.
    observed=[]
    actual=os.fsync
    def synced(fd):
        info=os.fstat(fd)
        observed.append((info.st_dev,info.st_ino,stat.S_ISDIR(info.st_mode)))
        return actual(fd)
    monkeypatch.setattr(os,'fsync',synced)
    store=store_type(tmp_path/'private',namespace='test')
    store.initialize()
    state,_=create(store,scope,binding_factory,running=True)
    with store.lease(SID,scope=scope) as lease:
        store.save_receipt(SID,AID,receipt(state),lease,scope=scope)
    for path in [tmp_path,store.root,store.root/'test',store.root/'test'/SID,
                 store.root/'test'/SID/'receipts']:
        info=path.stat()
        assert (info.st_dev,info.st_ino,True) in observed
    for path in [store.root/'test'/'.conversation-store.json',store.root/'test'/SID/'session.json',
                 store.root/'test'/SID/'receipts'/(AID+'.json')]:
        info=path.stat()
        assert (info.st_dev,info.st_ino,False) in observed
    store.close()


def test_failed_atomic_replace_keeps_previous_checkpoint(file_store,scope,binding_factory,monkeypatch):
    original,revision=create(file_store,scope,binding_factory)
    def failed(*args,**kwargs): raise OSError('synthetic filesystem failure')
    with file_store.lease(SID,scope=scope) as lease:
        monkeypatch.setattr(os,'replace',failed)
        with pytest.raises(StoreUnavailable):
            file_store.save_session(SID,reserve(original),revision,lease,scope=scope)
    assert file_store.load_session(SID,scope=scope).state==original
    assert not list((file_store.root/'test'/SID).glob('.session-*'))


def test_unknown_receipt_fsync_is_reported_without_deleting_evidence(file_store,scope,binding_factory,monkeypatch):
    state,_=create(file_store,scope,binding_factory,running=True)
    actual=os.fsync
    def failed(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode): raise OSError('synthetic parent fsync failure')
        return actual(fd)
    with file_store.lease(SID,scope=scope) as lease:
        monkeypatch.setattr(os,'fsync',failed)
        with pytest.raises(StoreUnavailable) as caught:
            file_store.save_receipt(SID,AID,receipt(state),lease,scope=scope)
        assert caught.value.outcome_unknown is True
    assert file_store.load_receipt(SID,AID,scope=scope)==receipt(state)


@pytest.mark.parametrize('content',[b'{}',b'[]',b'null',b'{"scope":{}}'])
def test_corrupt_snapshot_cannot_masquerade_as_absent_owner(file_store,scope,binding_factory,content):
    create(file_store,scope,binding_factory)
    (file_store.root/'test'/SID/'session.json').write_bytes(content)
    with pytest.raises(StoreCorrupt): file_store.load_session(SID,scope=scope)
