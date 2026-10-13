"""Host restoration reads validated receipts without executing validators/tools."""
import pytest
from prosaic_harness import Harness
from test_harness import setup, FakeRuntime


def test_completed_evidence_is_owned_ordered_and_read_only(tmp_path,monkeypatch):
    flow=setup(tmp_path,monkeypatch)
    runtime=FakeRuntime(['{"approved":true}'])
    harness=Harness(flow,tmp_path/'run',runtime=runtime)
    harness.run({'task':'preview'})
    evidence=harness.recovery_evidence()
    assert evidence['recoveryStatus']=='ready'
    assert evidence['checkpoint']['status']=='completed'
    assert len(evidence['receipts'])==1
    evidence['receipts'][0]['result']['stdout']='forged'
    assert harness.recovery_evidence()['receipts'][0]['result']['stdout']=='{"approved":true}'
    assert len(runtime.calls)==1
    with pytest.raises(ValueError): harness.recovery_evidence(maximum_bytes=100)


def test_saved_pending_receipt_is_available_without_adoption(tmp_path,monkeypatch):
    flow=setup(tmp_path,monkeypatch)
    runtime=FakeRuntime(['{"approved":true}'])
    harness=Harness(flow,tmp_path/'run',runtime=runtime)
    def crash(*args): raise OSError('fixture crash after saved receipt')
    monkeypatch.setattr(harness,'_accept',crash)
    with pytest.raises(OSError): harness.run({})
    evidence=harness.recovery_evidence()
    assert evidence['recoveryStatus']=='receiptAvailable'
    assert evidence['checkpoint']['pending'] is not None and len(evidence['receipts'])==1
    assert len(runtime.calls)==1


def test_dispatched_call_without_receipt_requires_resolution(tmp_path,monkeypatch):
    flow=setup(tmp_path,monkeypatch)
    runtime=FakeRuntime([KeyboardInterrupt()])
    harness=Harness(flow,tmp_path/'run',runtime=runtime)
    with pytest.raises(KeyboardInterrupt): harness.run({})
    evidence=harness.recovery_evidence()
    assert evidence['recoveryStatus']=='needsResolution' and evidence['receipts']==[]
    assert len(runtime.calls)==1
