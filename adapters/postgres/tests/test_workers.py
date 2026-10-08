import uuid
from support.workers import Worker


def test_simultaneous_human_submissions_do_not_double_advance(db_admin_dsn, worker_flow, model_server):
    from prosaic_harness_postgres import PostgresRunStore
    with PostgresRunStore(db_admin_dsn, namespace='workers') as store:
        store.initialize()
    run_id = uuid.uuid4().hex
    with Worker(db_admin_dsn, worker_flow, run_id, 'start') as first:
        assert first.result()['status'] == 'waiting'
    with Worker(db_admin_dsn, worker_flow, run_id, 'status') as reader:
        revision = reader.result()['revision']
    with Worker(db_admin_dsn, worker_flow, run_id, 'resume', choice='approve', revision=revision) as a:
        with Worker(db_admin_dsn, worker_flow, run_id, 'resume', choice='approve', revision=revision) as b:
            results = [a.result(allow_error=True), b.result(allow_error=True)]
    assert sum(r.get('status') == 'completed' for r in results) == 1
    assert any(r.get('error') in {'run_busy', 'revision_conflict'} for r in results)
    assert model_server.request_count == 1
