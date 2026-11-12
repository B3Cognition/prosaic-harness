from pathlib import Path
import yaml


def test_harness_contract_ci_uses_exact_runtime_source():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/tests.yml').read_text())
    assert workflow['env']['RUNTIME_COMMIT'] == '48c10ac9aeb18bd06f53015df0624b35d5254646'
    assert 'b3_prosaic_runtime-0.9.23-py3-none-any.whl' in (root / 'scripts/ci_context_pack_upstream.py').read_text()
    assert 'b3_prosaic_runtime-0.9.19-py3-none-any.whl' not in (root / '.github/workflows/tests.yml').read_text()


def test_ordinary_ci_installs_current_clean_build_filenames():
    import tomllib
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    workflow=(root/'.github/workflows/tests.yml').read_text()
    for project,name in [('.','b3_prosaic_harness'),('adapters/postgres','b3_prosaic_harness_postgres')]:
        version=tomllib.loads((root/project/'pyproject.toml').read_text())['project']['version']
        assert name+'-'+version+'-py3-none-any.whl' in workflow
