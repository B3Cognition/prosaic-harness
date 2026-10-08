"""Run the existing controller fixtures against the real PostgreSQL facade."""
from pathlib import Path
import sys
import uuid

import pytest
import yaml
from prosaic_harness import Harness, Workflow, RevisionConflict, LeaseLost
from test_store import pg_store

# Fixture reuse only; core's installed SDK has no dependency on test modules.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tests'))
from test_harness import setup, FakeRuntime


def test_pg_engine_stale_approval_at_later_same_named_pause(pg_store, tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch, pause=True)
    raw = yaml.safe_load(flow.path.read_text())
    raw['steps']['approval']['choices']['approve'] = 'second'
    raw['steps']['second'] = {'kind': 'pause', 'question': 'Again?', 'choices': {'approve': 'done'}}
    flow.path.write_text(yaml.safe_dump(raw))
    runtime = FakeRuntime(['{"approved":true}'])
    h = Harness(Workflow.load(flow.path), store=pg_store, run_id=uuid.uuid4().hex, runtime=runtime)
    h.run({})
    old = h.status().revision
    assert h.resume(choice='approve', expected_revision=old)['current'] == 'second'
    with pytest.raises(RevisionConflict):
        h.resume(choice='approve', expected_revision=old)
    assert h.resume(choice='approve', expected_revision=h.status().revision)['status'] == 'completed'
    assert len(runtime.calls) == 1


def test_pg_engine_receipt_recovery_without_redispatch(pg_store, tmp_path, monkeypatch):
    flow = setup(tmp_path, monkeypatch, pause=False)
    runtime = FakeRuntime(['{"approved":true}'])
    h = Harness(flow, store=pg_store, run_id=uuid.uuid4().hex, runtime=runtime)
    accept = h._accept
    monkeypatch.setattr(h, '_accept', lambda *args: (_ for _ in ()).throw(OSError('synthetic crash')))
    with pytest.raises(OSError):
        h.run({})
    monkeypatch.setattr(h, '_accept', accept)
    assert h.resume()['status'] == 'completed'
    assert len(runtime.calls) == 1


def test_pg_engine_loss_during_runtime_discards_output(db_admin_dsn, pg_store, tmp_path, monkeypatch):
    import psycopg
    flow = setup(tmp_path, monkeypatch, pause=False)
    runtime = FakeRuntime(['{"approved":true}'])
    h = Harness(flow, store=pg_store, run_id=uuid.uuid4().hex, runtime=runtime)
    run = runtime.run
    def lose(*args, **kwargs):
        with psycopg.connect(db_admin_dsn) as admin:
            admin.execute("UPDATE prosaic_harness.leases SET expires_at=clock_timestamp()-interval '1 second'")
        return run(*args, **kwargs)
    runtime.run = lose
    with pytest.raises(LeaseLost):
        h.run({})
    assert h.status().state['outputs'] == {}
    assert h.status().state['pending'] is not None
