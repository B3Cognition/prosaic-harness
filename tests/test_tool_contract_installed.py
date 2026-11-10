"""The candidate consumer must import installed payloads outside this checkout."""
import os
from pathlib import Path
import subprocess
import pytest


def test_installed_tool_contract_consumer(tmp_path):
    python=os.environ.get('PROSAIC_TOOL_CONTRACT_HARNESS_PYTHON')
    if not python:pytest.skip('explicit installed candidate environment required')
    script=Path(__file__).resolve().parents[1]/'scripts/tool_contract_smoke.py'
    result=subprocess.run([python,'-I',str(script)],cwd=tmp_path,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
    assert '"passed": true' in result.stdout
