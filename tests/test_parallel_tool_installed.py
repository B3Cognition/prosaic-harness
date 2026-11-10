from importlib import metadata
from pathlib import Path
import pytest
import prosaic_harness as api

@pytest.mark.skipif('site-packages' not in Path(api.__file__).parts,reason='installed candidate checkpoint')
def test_installed_parallel_candidate():
    import prosaic_harness_postgres as pg
    assert metadata.version('b3-prosaic-harness')==api.__version__
    assert 'site-packages' in Path(pg.__file__).parts
    assert hasattr(pg.PostgresRunStore,'migrate_parallel_tool_storage')

from test_parallel_tool_workflow import test_host_ceiling_node_narrowing_and_default_omission
from test_parallel_tool_conversation import test_parallel_session_receipt_retains_and_reopens
from test_parallel_tool_recovery import test_parallel_workflow_receipt_adopts_without_redispatch,test_parallel_workflow_with_pack_and_citations_adopts,test_parallel_cancellation_drains_and_blocks_later_window
from support.parallel_tools import parallel_endpoint
from test_workflow_rules_execution import rule_endpoint
