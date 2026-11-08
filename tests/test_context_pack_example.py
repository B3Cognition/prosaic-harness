"""The documented example is executable with installed SDK public APIs."""
from pathlib import Path
import runpy


def test_per_node_documentation_example(tmp_path):
    root = Path(__file__).resolve().parents[1]
    smoke = runpy.run_path(str(root / 'scripts/context_pack_smoke.py'))
    with smoke['fixture']['endpoint']() as (url, requests, replies):
        result = smoke['documentation_example'](tmp_path.resolve(), url, requests, replies)
    assert result == {'nodes': 3, 'providerRequests': 3, 'undeclaredDisclosures': 0}
