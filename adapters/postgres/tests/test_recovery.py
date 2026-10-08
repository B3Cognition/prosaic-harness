import uuid
import psycopg
import pytest

from support.workers import Worker


def clear_dead_owner(dsn, run_id):
    with psycopg.connect(dsn) as admin:
        admin.execute("UPDATE prosaic_harness.leases SET expires_at=clock_timestamp()-interval '1 second' WHERE run_id=%s", (run_id,))


@pytest.mark.parametrize('edge', ['initial', 'pending', 'receipt', 'transition', 'completed'])
def test_process_death_at_durable_edges(db_admin_dsn, worker_flow, model_server, edge):
    from prosaic_harness_postgres import PostgresRunStore
    run_id = uuid.uuid4().hex
    with PostgresRunStore(db_admin_dsn, namespace='workers') as store:
        store.initialize()
    with Worker(db_admin_dsn, worker_flow, run_id, 'start', edge=edge) as first:
        assert first.ready.wait(10), first.failure()
        first.kill()
    with PostgresRunStore(db_admin_dsn, namespace='workers') as reader:
        retained = reader.load_run(run_id).state
    clear_dead_owner(db_admin_dsn, run_id)
    with Worker(db_admin_dsn, worker_flow, run_id, 'resume') as second:
        state = second.result()
    assert state['started_at'] == retained['started_at'] and state['deadline'] == retained['deadline']
    if edge == 'pending':
        assert state['reason'] == 'interrupted_call' and model_server.request_count == 0
        with Worker(db_admin_dsn, worker_flow, run_id, 'status') as reader:
            snapshot = reader.result()
        with Worker(db_admin_dsn, worker_flow, run_id, 'resume', retry=True, revision=snapshot['revision']) as retry:
            blocked = retry.result()
            assert blocked['status'] == 'blocked' and blocked['reason'] == 'usage_unknown'
            assert blocked['calls'] == 1
        assert model_server.request_count == 0
    elif edge == 'completed':
        assert state['status'] == 'completed' and model_server.request_count == 1
    else:
        assert state['status'] == 'waiting' and state['calls'] == 1
        assert model_server.request_count == 1


def test_pending_model_request_never_redispatches_without_consent(db_admin_dsn, worker_flow, model_server):
    from prosaic_harness_postgres import PostgresRunStore
    with PostgresRunStore(db_admin_dsn, namespace='workers') as store:
        store.initialize()
    run_id = uuid.uuid4().hex
    model_server.delay.clear()
    with Worker(db_admin_dsn, worker_flow, run_id, 'start') as first:
        assert model_server.received.wait(10)
        first.kill()
    model_server.delay.set()
    clear_dead_owner(db_admin_dsn, run_id)
    with Worker(db_admin_dsn, worker_flow, run_id, 'resume') as second:
        state = second.result()
    assert state['reason'] == 'interrupted_call' and state['calls'] == 1
    assert model_server.request_count == 1


@pytest.mark.parametrize('asset', ['prose', 'schema', 'runtime'])
def test_changed_shared_assets_fail_before_dispatch(db_admin_dsn, worker_flow, model_server, asset):
    import yaml
    from prosaic_harness_postgres import PostgresRunStore
    with PostgresRunStore(db_admin_dsn, namespace='workers') as store:
        store.initialize()
    run_id = uuid.uuid4().hex
    with Worker(db_admin_dsn, worker_flow, run_id, 'start', edge='initial') as first:
        assert first.ready.wait(10)
        first.kill()
    clear_dead_owner(db_admin_dsn, run_id)
    root = worker_flow.parent
    if asset == 'prose':
        prose = root / '.prosaic/subagents/author.md'
        prose.write_text(prose.read_text() + '\nChanged trusted prose.\n')
    elif asset == 'schema':
        (root / 'result.json').write_text('{"type":"object","required":["different"]}')
    else:
        path = root / 'runtime.yml'
        runtime = yaml.safe_load(path.read_text())
        runtime['profiles']['local']['model'] = 'changed-model'
        path.write_text(yaml.safe_dump(runtime))
    with Worker(db_admin_dsn, worker_flow, run_id, 'resume') as changed:
        assert changed.result(allow_error=True)['error'] == 'ValueError'
    assert model_server.request_count == 0


def test_committed_decision_survives_worker_death(db_admin_dsn, worker_flow, model_server):
    from prosaic_harness_postgres import PostgresRunStore
    with PostgresRunStore(db_admin_dsn, namespace='workers') as store:
        store.initialize()
    run_id = uuid.uuid4().hex
    with Worker(db_admin_dsn, worker_flow, run_id, 'start') as first:
        assert first.result()['status'] == 'waiting'
    with Worker(db_admin_dsn, worker_flow, run_id, 'status') as reader:
        revision = reader.result()['revision']
    with Worker(db_admin_dsn, worker_flow, run_id, 'resume', edge='decision', choice='approve', revision=revision) as decider:
        assert decider.ready.wait(10), decider.failure()
        decider.kill()
    clear_dead_owner(db_admin_dsn, run_id)
    with Worker(db_admin_dsn, worker_flow, run_id, 'resume') as next_worker:
        state = next_worker.result()
    assert state['status'] == 'completed' and model_server.request_count == 1


def test_fresh_retry_consent_preserves_consumed_calls(db_admin_dsn, worker_flow, model_server):
    import yaml
    from prosaic_harness_postgres import PostgresRunStore
    definition = yaml.safe_load(worker_flow.read_text())
    del definition['limits']['max_tokens']
    worker_flow.write_text(yaml.safe_dump(definition))
    with PostgresRunStore(db_admin_dsn, namespace='workers') as store:
        store.initialize()
    run_id = uuid.uuid4().hex
    with Worker(db_admin_dsn, worker_flow, run_id, 'start', edge='pending') as first:
        assert first.ready.wait(10)
        first.kill()
    clear_dead_owner(db_admin_dsn, run_id)
    with Worker(db_admin_dsn, worker_flow, run_id, 'resume') as second:
        assert second.result()['reason'] == 'interrupted_call'
    with Worker(db_admin_dsn, worker_flow, run_id, 'status') as reader:
        revision = reader.result()['revision']
    with Worker(db_admin_dsn, worker_flow, run_id, 'resume', retry=True, revision='stale') as denied:
        assert denied.result(allow_error=True)['error'] == 'revision_conflict'
    assert model_server.request_count == 0
    with Worker(db_admin_dsn, worker_flow, run_id, 'resume', retry=True, revision=revision) as consenting:
        state = consenting.result()
    assert state['status'] == 'waiting' and state['calls'] == 2
    assert model_server.request_count == 1


def test_unknown_receipt_commit_is_adopted_from_primary(db_admin_dsn, worker_flow, model_server):
    from prosaic_harness_postgres import PostgresRunStore
    from support.tcp_proxy import TcpProxy
    with PostgresRunStore(db_admin_dsn, namespace='workers') as store:
        store.initialize()
    run_id = uuid.uuid4().hex
    with TcpProxy(db_admin_dsn) as proxy:
        with Worker(proxy.dsn, worker_flow, run_id, 'start', edge='pending') as first:
            assert first.ready.wait(10), first.failure()
            proxy.block_next_commit_reply()
            first.release.set()
            result = first.result(allow_error=True)
            assert result['error'] == 'store_unavailable'
            assert proxy.commit_sent.is_set()
    clear_dead_owner(db_admin_dsn, run_id)
    with Worker(db_admin_dsn, worker_flow, run_id, 'resume') as fresh:
        assert fresh.result()['status'] == 'waiting'
    assert model_server.request_count == 1
