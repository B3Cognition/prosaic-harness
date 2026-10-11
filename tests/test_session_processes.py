"""Actual worker death and OS lock behavior, with no model/network effects."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from prosaic_harness import SessionBusy, StoreUnavailable, LeaseLost
from prosaic_harness.file_session_store import FileSessionStore
from prosaic_harness.session_contracts import new_session
from prosaic_harness.session_codec import encode
from support.conversations import binding_factory, scope
from test_session_contracts import reserve, receipt, mark_dispatch, SID, AID


_PRELUDE='''
import os, sys, json
from pathlib import Path
from prosaic_harness import ConversationScope
from prosaic_harness.file_session_store import FileSessionStore
root=Path(sys.argv[1])
scope=ConversationScope('test','sandbox','app','tenant','actor')
store=FileSessionStore(root,namespace='test')
sid='a'*32
aid='b'*32
'''


def worker(root,body,*,stdin=None):
    environment=dict(os.environ)
    environment['PYTHONPATH']=str(Path(__file__).resolve().parents[1]/'src')
    return subprocess.Popen([sys.executable,'-c',_PRELUDE+body,str(root)],
        env=environment,stdin=stdin,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)


def test_worker_death_releases_session_lock(tmp_path,scope):
    store=FileSessionStore(tmp_path/'private',namespace='test')
    store.initialize()
    child=worker(store.root,"""
with store.lease(sid,scope=scope):
    print('locked',flush=True)
    sys.stdin.readline()
""",stdin=subprocess.PIPE)
    try:
        assert child.stdout.readline().strip()=='locked'
        with pytest.raises(SessionBusy):
            with store.lease(SID,scope=scope): pass
        child.kill()
        _,error=child.communicate(timeout=10)
        assert not error
        with store.lease(SID,scope=scope) as lease: lease.check_valid()
    finally:
        if child.poll() is None: child.kill(); child.communicate(timeout=10)
        store.close()


def test_crash_after_receipt_save_is_recoverable_without_adoption(tmp_path,scope,binding_factory):
    store=FileSessionStore(tmp_path/'private',namespace='test')
    store.initialize()
    state=mark_dispatch(reserve(new_session(SID,scope,binding_factory())),AID)
    with store.lease(SID,scope=scope) as lease: store.create_session(SID,state,lease,scope=scope)
    saved=receipt(state)
    packet=tmp_path/'private-receipt.json'
    packet.write_bytes(encode(saved))
    packet.chmod(0o600)
    child=worker(store.root,"""
with store.lease(sid,scope=scope) as lease:
    value=json.loads((root.parent/'private-receipt.json').read_text())
    store.save_receipt(sid,aid,value,lease,scope=scope)
    os._exit(91)
""")
    output,error=child.communicate(timeout=10)
    assert child.returncode==91 and not output and not error
    restarted=FileSessionStore(store.root,namespace='test')
    assert restarted.load_receipt(SID,AID,scope=scope)==saved
    assert restarted.load_session(SID,scope=scope).state['attempts'][AID]['receiptAdopted'] is False
    with restarted.lease(SID,scope=scope) as lease: lease.check_valid()
    restarted.close()
    store.close()


def test_forked_store_and_lease_are_rejected(tmp_path,scope,binding_factory):
    store=FileSessionStore(tmp_path/'private',namespace='test')
    store.initialize()
    with store.lease(SID,scope=scope) as lease:
        store.create_session(SID,new_session(SID,scope,binding_factory()),lease,scope=scope)
        read_fd,write_fd=os.pipe()
        pid=os.fork()
        if pid==0:
            os.close(read_fd)
            result=[]
            try: store.load_session(SID,scope=scope)
            except StoreUnavailable: result.append('store')
            try: lease.check_valid()
            except LeaseLost: result.append('lease')
            os.write(write_fd,','.join(result).encode())
            os._exit(0)
        os.close(write_fd)
        assert os.read(read_fd,64)==b'store,lease'
        os.close(read_fd)
        _,status=os.waitpid(pid,0)
        assert status==0
        lease.check_valid()
    store.close()
