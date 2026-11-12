from prosaic_harness_postgres import PostgresRunStore

from test_cli import grant_runtime
from test_mcp_recovery import check_offline_adoption
from test_workflow_rules_execution import rule_endpoint


def test_mcp_receipt_adopts_after_reconnect(db_admin_dsn, runtime_dsn, rule_endpoint, monkeypatch):
    with PostgresRunStore(db_admin_dsn, namespace="test") as owner:
        owner.initialize(tool_contracts=True)
    grant_runtime(db_admin_dsn, runtime_dsn)
    with (PostgresRunStore(runtime_dsn, namespace="test") as worker,
          PostgresRunStore(runtime_dsn, namespace="test") as fresh):
        check_offline_adoption(rule_endpoint, monkeypatch, worker, fresh)
