from concurrent.futures import ThreadPoolExecutor
import threading,time
import pytest
import prosaic_runtime as api
from prosaic_harness import ContextPackError
from test_context_pack_reader import reader_case,call


def test_real_worker_threads_cannot_cross_over_same_item_ids():
    reader,first,bindings=reader_case('first private evidence')
    _,second,other=reader_case('second private evidence')
    ready=threading.Barrier(2)
    def work(index,pack,host):
        scope=api.InvocationScope('turn-'+str(index),run_id='run',operation_namespace='test')
        with reader.activate(scope,pack,host,deadline=time.monotonic()+60):
            ready.wait(timeout=5)
            return call(reader,scope,pack.envelope['index'][0]['citationId'])['result']['content']
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures=[workers.submit(work,1,first,bindings),workers.submit(work,2,second,other)]
        assert [future.result(timeout=10) for future in futures]==['first private evidence','second private evidence']
    assert reader.active_count==0


def test_timeout_and_rebinding_do_not_revive_old_grants():
    reader,pack,bindings=reader_case();scope=api.InvocationScope('turn')
    with reader.activate(scope,pack,bindings,deadline=time.monotonic()-1):
        assert call(reader,scope,pack.envelope['index'][0]['citationId'])['result']['error']=='contextSnapshotUnavailable'
        with pytest.raises(ContextPackError):
            with reader.activate(scope,pack,bindings,deadline=time.monotonic()+60): pass
    with reader.activate(scope,pack,bindings,deadline=time.monotonic()+60):
        assert call(reader,scope,pack.envelope['index'][0]['citationId'])['result']['content']=='captured facts'
    assert reader.active_count==0


def test_cleanup_and_new_binding_prevent_inflight_old_authorization_from_disclosing():
    entered=threading.Event();release=threading.Event()
    def authorize(use):
        entered.set();assert release.wait(5);return True
    reader,old,bindings=reader_case('old private evidence',authorize=authorize)
    _,new,other=reader_case('new evidence')
    scope=api.InvocationScope('same-turn')
    with ThreadPoolExecutor(max_workers=1) as worker:
        with reader.activate(scope,old,bindings,deadline=time.monotonic()+60):
            future=worker.submit(call,reader,scope,old.envelope['index'][0]['citationId'])
            assert entered.wait(5)
        with reader.activate(scope,new,other,deadline=time.monotonic()+60):
            release.set()
            assert future.result(timeout=5)['result']['error']=='contextSnapshotUnavailable'
            assert call(reader,scope,new.envelope['index'][0]['citationId'])['result']['content']=='new evidence'
    assert reader.active_count==0
