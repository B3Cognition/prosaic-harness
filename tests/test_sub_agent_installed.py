"""Installed consumer witnesses for Harness receipt adoption."""
from pathlib import Path

import prosaic_harness as h
import prosaic_runtime as rt

from test_sub_agent_recovery import (
    rule_endpoint,
    test_lost_parent_receipt_ack_adopts_with_endpoints_offline,
    test_native_workflow_rejects_delegate_proposals_and_adopts_receipt,
)


def test_installed_delegation_sdk():
    assert 'site-packages' in Path(h.__file__).parts
    assert 'site-packages' in Path(rt.__file__).parts
    assert hasattr(h, 'SubAgentBindingsV1')
