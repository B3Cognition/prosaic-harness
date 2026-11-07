"""Copied V2 resources exercise tags; the V1 validator example remains intact."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import yaml

import pytest
from prosaic_harness import Harness
from test_revision_review_blueprint import context, queue_initial
from test_transport import endpoint, text

ROOT = Path(__file__).resolve().parents[1] / 'examples/workflow-enforcement'


def host(root):
    spec = importlib.util.spec_from_file_location('workflow_enforcement_host', root / 'host.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('mode', ['yaml', 'native'])
def test_copied_blueprint_repairs_untouched_finding_then_requires_approval(endpoint, tmp_path, mode):
    url, requests, replies = endpoint
    root = tmp_path / 'copy'; shutil.copytree(ROOT, root)
    config = yaml.safe_load((root / 'runtime.yml').read_text())
    config['profiles']['local']['base_url'] = url
    (root / 'runtime.yml').write_text(yaml.safe_dump(config))
    h = host(root); flow = h.workflow(mode=mode, executable=str(Path(sys.executable).with_name('prosaic')))
    queue_initial(replies)
    replies.extend([text({'findings': [{'insight_id': 'C', 'text': 'untouched'}]}),
        text({'findings': [{'insight_id': 'B', 'text': 'changed'}]})])
    controller = Harness(flow, tmp_path / 'run', validators=h.validators())
    state = controller.run(context().request)
    assert state['status'] == 'waiting' and state['calls'] == 3 and len(requests) == 4
    assert state['outputs']['revised_review']['findings'][0]['insight_id'] == 'B'
    evidence = controller.recovery_evidence()
    proof = evidence['receipts'][-1]['result']['metadata']['workflow_rules_v1']
    assert proof['rules']['violated'] and proof['rules']['evaluated']
    assert controller.resume(choice='accept')['status'] == 'completed' and len(requests) == 4


def test_workflow_capability_is_public():
    assert 'workflow_rules_v1' in Harness.capabilities


def test_copied_runner_selects_same_python_cli_without_ambient_path(tmp_path):
    import os, subprocess
    root=tmp_path/'copy';shutil.copytree(ROOT,root)
    command=[sys.executable, '-I', str(root/'run.py'), '--run-dir',str(tmp_path/'run')]
    result=subprocess.run(command,env={**os.environ,'PATH':''},capture_output=True,text=True,timeout=20)
    assert result.returncode==2 and '--live' in result.stderr and not (tmp_path/'run').exists()
