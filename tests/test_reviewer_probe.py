"""The opt-in probe reports an approving reviewer as a failed evaluation."""
import json
import subprocess
import sys
from pathlib import Path
import pytest
from test_transport import endpoint, copy_blueprint, text


@pytest.mark.parametrize('approved,exit_code', [(True, 1), (False, 0)])
def test_reviewer_probe_checks_decision_not_only_schema(endpoint, tmp_path, approved, exit_code):
    url, requests, replies = endpoint
    root = copy_blueprint(tmp_path, 'review.yml', url).parent
    # The probe uses the configured strong route. Use the same local profile for all tiers.
    import yaml
    cfg = yaml.safe_load((root / 'runtime.yml').read_text())
    cfg['routes']['strong'] = 'local'
    (root / 'runtime.yml').write_text(yaml.safe_dump(cfg))
    replies.extend([text({'approved': approved, 'issues': [] if approved else ['S4: Mislabelled metric']})] * 2)
    result = subprocess.run([sys.executable, str(root / 'evaluate_reviewer.py'), '--config', str(root / 'runtime.yml'), '--live'],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == exit_code, result.stderr
    report = json.loads(result.stdout)
    assert report['passed'] is (not approved) and len(report['cases']) == 2
    assert len(requests) == 2
