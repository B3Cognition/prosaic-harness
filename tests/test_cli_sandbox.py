"""Sandbox policy is host authority and is bound to durable workflow identity."""
import json
from dataclasses import replace
from pathlib import Path
import sys
import shutil

import pytest
import yaml
pytest.importorskip('prosaic_runtime.sandbox', reason='requires the unreleased CLI sandbox Runtime capability')
from prosaic_harness import Harness, Workflow
from prosaic_harness.workflow import runtime_identity
from prosaic_runtime import CliSandboxConfig, ProsaicRuntime
from test_harness import setup, FakeRuntime
from test_transport import endpoint, text
from test_cli_tools import cli_blueprint
from test_custom_tools import call


@pytest.mark.skipif(not ((sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').is_file())
                        or (sys.platform == 'linux' and Path('/usr/bin/bwrap').is_file())),
                    reason='requires Seatbelt or Bubblewrap')
def test_documented_sandboxed_blueprint_runs_tool_then_requires_human(endpoint, tmp_path):
    url, requests, replies = endpoint
    examples = Path(__file__).resolve().parents[1] / 'examples'
    copied = tmp_path / 'examples'
    shutil.copytree(examples, copied, ignore=shutil.ignore_patterns('*.local.yml', '*.local.yaml', '__pycache__'))
    config = copied / 'cli-tools-sandboxed-runtime.yml'
    raw = yaml.safe_load(config.read_text())
    raw['profiles']['local'].update(base_url=url, features={'streaming': False})
    config.write_text(yaml.safe_dump(raw))
    executable = tmp_path / 'analyzer'
    # Native CLI fixture: the controller must observe execution before admission.
    # Runtime's companion test runs the actual shipped analyzer implementation.
    expected = {'requirements': 2, 'vague_ids': ['REQ-002'], 'passed': False}
    executable.write_text(f'#!{sys.executable}\nimport json, pathlib, sys\n'
        'if sys.argv[1:] == ["--version"]: print("prosaic-example-analyzer 1.0")\n'
        'else:\n'
        '    assert "REQ-002" in pathlib.Path(sys.argv[1]).read_text()\n'
        f'    print(json.dumps({expected!r}))\n')
    executable.chmod(0o700)
    manifest = copied / '.prosaic/tools/analyze-spec.yml'
    data = yaml.safe_load(manifest.read_text())
    data['executable'] = str(executable)
    manifest.write_text(yaml.safe_dump(data))
    workflow = Workflow.load(copied / 'cli-tool-sandboxed.yml')
    tool_call = call()
    function = tool_call['tool_calls'][0]['function']
    function.update(name='analyze_spec', arguments='{"spec":"evidence/requirements.md"}')
    replies.extend([tool_call, text(expected)])
    h = Harness(workflow, tmp_path / 'run')
    assert h.run({'spec': 'evidence/requirements.md'})['status'] == 'waiting'
    assert h.resume()['status'] == 'waiting'
    assert h.resume(choice='approve')['status'] == 'completed'
    tool = next(m for m in requests[1]['messages'] if m['role'] == 'tool')
    assert json.loads(tool['content']) == {'status': 'ok', 'result': expected}
    assert len(requests) == 2


def test_default_off_sandbox_preserves_legacy_runtime_identity(tmp_path, monkeypatch):
    workflow = setup(tmp_path, monkeypatch)
    identity = runtime_identity(workflow.config)
    assert 'cli_sandbox' not in identity


def test_changing_sandbox_policy_invalidates_pending_approval(tmp_path, monkeypatch):
    workflow = setup(tmp_path, monkeypatch, pause=True)
    h = Harness(workflow, tmp_path / 'run', runtime=FakeRuntime(['{"approved":true}']))
    assert h.run({})['status'] == 'waiting'
    path = tmp_path / 'runtime.yml'
    cfg = yaml.safe_load(path.read_text())
    cfg['cli_sandbox'] = {'mode': 'required'}
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match='changed'):
        Harness(Workflow.load(tmp_path / 'flow.yml'), tmp_path / 'run', runtime=FakeRuntime([])).resume(choice='approve')


@pytest.mark.skipif(not ((sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').is_file())
                        or (sys.platform == 'linux' and Path('/usr/bin/bwrap').is_file())),
                    reason='requires Seatbelt or Bubblewrap')
def test_harness_cli_sandbox_denies_outside_secret_and_preserves_pause(endpoint, tmp_path):
    url, requests, replies = endpoint
    path, executable, _ = cli_blueprint(tmp_path, url)
    secret = tmp_path / 'host-secret.txt'
    secret.write_text('SYNTHETIC-HOST-SECRET')
    executable.write_text(f'#!{sys.executable}\nimport json, pathlib, sys\n'
        'if sys.argv[1:] == ["--version"]: print("catalog 1.0")\n'
        'else:\n'
        f'    try: pathlib.Path({str(secret)!r}).read_text()\n'
        '    except (PermissionError, FileNotFoundError): print(json.dumps({"found":True}))\n'
        '    else: print(json.dumps({"found":False}))\n')
    config = tmp_path / 'runtime.yml'
    raw = yaml.safe_load(config.read_text())
    raw['cli_sandbox'] = {'mode': 'required'}
    config.write_text(yaml.safe_dump(raw))
    workflow = Workflow.load(path)
    replies.extend([call(), text({'found': True})])
    h = Harness(workflow, tmp_path / 'run')
    result = h.run({})
    assert result['status'] == 'waiting' and result['outputs']['lookup'] == {'found': True}
    assert 'SYNTHETIC-HOST-SECRET' not in json.dumps(requests)
    assert h.resume()['status'] == 'waiting'


@pytest.mark.skipif(not ((sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').is_file())
                        or (sys.platform == 'linux' and Path('/usr/bin/bwrap').is_file())),
                    reason='requires Seatbelt or Bubblewrap')
@pytest.mark.parametrize('change', ['off', 'missing_capability', 'after_construction'])
def test_injected_adapter_cannot_downgrade_required_sandbox(endpoint, tmp_path, change):
    url, requests, replies = endpoint
    replies.append(text({'found': True}))  # Keep a broken implementation's HTTP response well-formed.
    path, _, _ = cli_blueprint(tmp_path, url)
    config = tmp_path / 'runtime.yml'
    raw = yaml.safe_load(config.read_text())
    raw['cli_sandbox'] = {'mode': 'required'}
    config.write_text(yaml.safe_dump(raw))
    workflow = Workflow.load(path)
    adapter = ProsaicRuntime(workflow.config)
    if change == 'missing_capability':
        adapter.capabilities = frozenset({'custom_tools_v1'})
    elif change == 'off':
        adapter.config = replace(adapter.config, cli_sandbox=CliSandboxConfig())
    if change == 'after_construction':
        h = Harness(workflow, tmp_path / 'run', runtime=adapter)
        adapter.config = replace(adapter.config, cli_sandbox=CliSandboxConfig())
        with pytest.raises(ValueError, match='sandbox'):
            h.run({})
    else:
        with pytest.raises(ValueError, match='sandbox'):
            Harness(workflow, tmp_path / 'run', runtime=adapter)
    assert requests == [] and not (tmp_path / 'run/run.json').exists()
