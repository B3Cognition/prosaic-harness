"""Released controller records stay readable without re-sealing expected bytes."""
import hashlib
import json
from pathlib import Path
from prosaic_harness.session_contracts import verify_session, verify_receipt
from prosaic_harness.contracts import validate_receipt, verify_seal


def test_released_legacy_fixtures_load_unchanged():
    content = (Path(__file__).parent / 'fixtures/context_packs/legacy/released.json').read_bytes()
    assert hashlib.sha256(content).hexdigest() == '67022cb32d7dccb729649db7ad100cc569f47b50e3ca1f5b3a225b7f9046c665'
    fixture = json.loads(content)
    for version in (1, 2):
        record = fixture[str(version)]
        assert verify_session(record['session']) == record['session']
        assert record['session']['version'] == version
        assert verify_receipt(record['receipt']) == record['receipt']
        assert record['receipt']['version'] == version
    workflow = fixture['workflow']
    verify_seal(workflow['checkpoint'])
    packet = workflow['receipt']
    pending = {k: packet[k] for k in ('id', 'step', 'arguments_sha256')}
    validate_receipt(packet, workflow['checkpoint'], pending)
    assert workflow['checkpoint']['version'] == 2 and packet['version'] == 1
