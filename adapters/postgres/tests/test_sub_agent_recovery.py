import pytest

from prosaic_harness import ConversationScope, StoreBusy, StoreIncompatible
from prosaic_harness_postgres import PostgresRunStore, PostgresSessionStore
from test_cli import grant_runtime
from test_session_schema import grant_conversations


@pytest.mark.parametrize('kind', ['workflow', 'conversation'])
def test_delegate_storage_migration_is_explicit_and_fenced(db_admin_dsn, runtime_dsn, kind):
    workflow = kind == 'workflow'
    cls = PostgresRunStore if workflow else PostgresSessionStore
    grant = grant_runtime if workflow else grant_conversations
    with cls(db_admin_dsn, namespace='test') as owner:
        owner.initialize(parallel_tools=True)
        grant(db_admin_dsn, runtime_dsn)
        with cls(runtime_dsn, namespace='test') as worker:
            assert 'sub_agents_v1' not in worker.capabilities
            with pytest.raises(StoreIncompatible):
                worker.migrate_sub_agent_storage()
            options = {} if workflow else {'scope': ConversationScope('test','sandbox','app','tenant','actor')}
            with worker.lease('a' * 32, **options):
                with pytest.raises(StoreBusy):
                    owner.migrate_sub_agent_storage()
            owner.migrate_sub_agent_storage()
            owner.migrate_parallel_tool_storage()
            assert 'sub_agents_v1' in worker.capabilities
