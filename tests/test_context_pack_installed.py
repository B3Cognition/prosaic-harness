"""Required by artifact CI; ordinary source tests need no prebuilt wheel env."""
import os
from pathlib import Path
import subprocess
import pytest


def test_installed_context_pack_workflows(tmp_path):
    python=os.environ.get('CONTEXT_PACK_QUAL_PYTHON')
    if not python:
        if os.environ.get('CONTEXT_PACK_REQUIRE_INSTALLED')=='1': pytest.fail('CONTEXT_PACK_QUAL_PYTHON is required')
        pytest.skip('explicit installed-wheel qualification environment is not configured')
    assert Path(python).is_absolute()
    script=Path(__file__).resolve().parents[1]/'scripts/context_pack_smoke.py'
    env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONHOME'}}
    result=subprocess.run([python,'-I',str(script)],cwd=tmp_path,env=env,
        capture_output=True,text=True,timeout=180)
    assert result.returncode==0,result.stdout+result.stderr
