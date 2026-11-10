from pathlib import Path
import yaml


def test_harness_contract_ci_uses_exact_runtime_source():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/tests.yml').read_text())
    assert workflow['env']['RUNTIME_COMMIT'] == '524758001da0d768e398aa51b1a97812adf09032'
    assert 'b3_prosaic_runtime-0.9.20.dev1-py3-none-any.whl' in (root / 'scripts/ci_context_pack_upstream.py').read_text()
    assert 'b3_prosaic_runtime-0.9.19-py3-none-any.whl' not in (root / '.github/workflows/tests.yml').read_text()
