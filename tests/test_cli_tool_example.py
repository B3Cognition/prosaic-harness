import json
from pathlib import Path
import shutil
import subprocess
import sys
import yaml
from test_transport import endpoint, text

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


def test_shipped_cli_blueprint_validates_then_requires_native_execution(endpoint, tmp_path):
    url, requests, replies = endpoint
    workspace = tmp_path / 'examples'; shutil.copytree(EXAMPLES, workspace)
    executable = tmp_path / 'analyzer'
    executable.write_text(f'#!{sys.executable}\nimport json, pathlib, sys\n'
        'if sys.argv[1:] == ["--version"]: print("prosaic-example-analyzer 1.0")\n'
        'else:\n    assert "REQ-002:" in pathlib.Path(sys.argv[1]).read_text()\n'
        '    print(json.dumps({"requirements":2,"vague_ids":["REQ-002"],"passed":False}))\n')
    executable.chmod(0o755)
    manifest = workspace / '.prosaic/tools/analyze-spec.yml'
    data = yaml.safe_load(manifest.read_text()); data['executable'] = str(executable)
    manifest.write_text(yaml.safe_dump(data))
    config = workspace / 'cli-tools-runtime.yml'; data = yaml.safe_load(config.read_text())
    for profile in data['profiles'].values():
        profile.update(base_url=url, api_key_env=None, features={'streaming': False})
    config.write_text(yaml.safe_dump(data))
    workflow = workspace / 'cli-tool.yml'
    command = [sys.executable, '-m', 'prosaic_harness.cli']
    checked = subprocess.run([*command, 'validate', str(workflow)], capture_output=True, text=True, timeout=10)
    assert checked.returncode == 0, checked.stderr
    assert requests == []
    report = {'requirements': 2, 'vague_ids': ['REQ-002'], 'passed': False}
    replies.extend([{'content': '', 'tool_calls': [{'id': 'analyze', 'type': 'function', 'function': {
        'name': 'analyze_spec', 'arguments': '{"spec":"evidence/requirements.md"}'}}]}, text(report)])
    run_dir = tmp_path / 'run'
    ran = subprocess.run([*command, 'run', str(workflow), '--input', str(workspace / 'cli-tool-input.json'),
                          '--run-dir', str(run_dir), '--events'], capture_output=True, text=True, timeout=15)
    assert ran.returncode == 0, ran.stderr
    status = json.loads(ran.stdout.splitlines()[-1])
    assert status['status'] == 'waiting' and status['outputs']['analysis'] == report
    tool = next(m for m in requests[1]['messages'] if m['role'] == 'tool')
    assert json.loads(tool['content'])['result'] == report
    resumed = subprocess.run([*command, 'resume', str(workflow), '--run-dir', str(run_dir), '--choice', 'approve', '--events'],
                             capture_output=True, text=True, timeout=10)
    assert resumed.returncode == 0 and len(requests) == 2
    assert json.loads(resumed.stdout.splitlines()[-1])['status'] == 'completed'
