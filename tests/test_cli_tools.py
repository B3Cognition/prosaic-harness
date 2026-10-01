"""CLI manifests must be preflighted before a workflow can make model calls."""
import json
import sys
import pytest
import yaml
from prosaic_harness import Harness, Workflow
from test_transport import endpoint, text
from test_custom_tools import blueprint, call


def cli_blueprint(tmp_path, url):
    path = blueprint(tmp_path, url)
    executable = tmp_path / 'catalog-cli'
    executable.write_text(f'#!{sys.executable}\nimport json, sys\n'
        'if sys.argv[1:] == ["--version"]: print("catalog 1.0")\n'
        'else: print(json.dumps({"found": sys.argv[1] == "SKU-001"}))\n')
    executable.chmod(0o755)
    directory = tmp_path / '.prosaic/tools'; directory.mkdir()
    manifest = directory / 'catalog.yml'
    manifest.write_text(yaml.safe_dump({'schema_version': 1, 'name': 'lookup_catalog',
        'description': 'Read a catalogue', 'tool_version': '1.0', 'executable': str(executable),
        'argv': ['{sku}'], 'parameters': {'type': 'object', 'additionalProperties': False,
            'required': ['sku'], 'properties': {'sku': {'type': 'string'}}},
        'output_format': 'json', 'version_probe': ['--version']}))
    config = tmp_path / 'runtime.yml'; data = yaml.safe_load(config.read_text())
    data['tool_directories'] = ['.prosaic/tools']; config.write_text(yaml.safe_dump(data))
    return path, executable, manifest


def test_cli_workflow_uses_native_receipt_and_human_pause(endpoint, tmp_path):
    url, requests, replies = endpoint
    path, _, _ = cli_blueprint(tmp_path, url)
    workflow = Workflow.load(path)
    replies.extend([call(), text({'found': True})])
    harness = Harness(workflow, tmp_path / 'run')
    assert harness.run({})['status'] == 'waiting'
    receipt = json.loads(next((tmp_path / 'run/attempts').glob('*.json')).read_text())
    assert any(e.get('name') == 'lookup_catalog' and e.get('status') == 'ok' for e in receipt['events'])
    assert harness.resume(choice='approve')['status'] == 'completed'
    assert len(requests) == 2


def test_missing_cli_executable_blocks_workflow_load_before_network(endpoint, tmp_path):
    url, requests, _ = endpoint
    path, executable, _ = cli_blueprint(tmp_path, url)
    executable.unlink()
    with pytest.raises(ValueError, match='preflight'):
        Workflow.load(path)
    assert requests == []


def test_cli_manifest_change_blocks_resume(endpoint, tmp_path):
    url, requests, replies = endpoint
    path, _, manifest = cli_blueprint(tmp_path, url)
    workflow = Workflow.load(path)
    replies.extend([call(), text({'found': True})])
    assert Harness(workflow, tmp_path / 'run').run({})['status'] == 'waiting'
    data = yaml.safe_load(manifest.read_text()); data['argv'] = ['{sku}', '--changed']
    manifest.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match='changed'):
        Harness(Workflow.load(path), tmp_path / 'run').resume(choice='approve')
    assert len(requests) == 2
