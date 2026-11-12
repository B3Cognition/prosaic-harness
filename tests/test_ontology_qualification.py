"""Receipt checks for the separate installed ontology combination."""
import json
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
try:
    import catalogue_ontology_qualify as ontology
    from release_artifacts import ReleaseError, digest, write_json
finally:
    sys.path.pop(0)


def _report(path, cases):
    path.write_text(f'<testsuites><testsuite tests="{len(cases)}" errors="0" failures="0" skipped="0">'
                    + ''.join(f'<testcase name="{case}"/>' for case in cases) + '</testsuite></testsuites>')


def test_compatibility_requires_exact_cases_and_no_skips(tmp_path):
    path = tmp_path / 'results.xml'
    expected = ['first', 'second']
    _report(path, expected)
    assert ontology.case_results(path, expected)['cases'] == expected
    for cases in ([], ['first'], ['first', 'first'], ['first', 'unexpected']):
        _report(path, cases)
        with pytest.raises(ReleaseError, match='ontology qualification'):
            ontology.case_results(path, expected)
    _report(path, expected)
    path.write_text(path.read_text().replace('name="first"/>', 'name="first"><skipped/></testcase>'))
    with pytest.raises(ReleaseError, match='ontology qualification'):
        ontology.case_results(path, expected)


def _package(directory, prefix, commit):
    directory.mkdir()
    artifacts = []
    for suffix in ('-py3-none-any.whl', '.tar.gz'):
        name = prefix + suffix
        payload = name.encode()
        (directory / name).write_bytes(payload)
        artifacts.append({'filename': name, 'sha256': digest(payload)})
    write_json(directory / 'release-receipt.json',
               {'version': 1, 'source_commit': commit, 'artifacts': artifacts})
    return ontology.package_binding(directory, commit, prefix)


def test_gate_rebinds_core_qualification_and_reports(tmp_path):
    core_dir, harness_dir = tmp_path / 'core', tmp_path / 'harness'
    core_commit, harness_commit = 'a' * 40, 'b' * 40
    core = _package(core_dir, ontology.CORE, core_commit)
    harness = _package(harness_dir, ontology.HARNESS, harness_commit)
    floor = {'repository': 'B3Cognition/prosaic'}
    upstream = {'version': 1, 'candidates': [floor]}
    upstream_sha = digest((json.dumps(upstream, sort_keys=True, indent=2) + '\n').encode())
    write_json(harness_dir / 'upstream-receipt.json', {'version': 1, 'candidates': [floor, {
        'repository': 'B3Cognition/prosaic-runtime', 'run_id': ontology.RUNTIME_RUN,
        'source_commit': ontology.RUNTIME_SOURCE, 'receipt_sha256': 'a' * 64,
        'upstream_receipt': upstream, 'upstream_sha256': upstream_sha,
        'wheels': [{'filename': ontology.RUNTIME, 'sha256': ontology.RUNTIME_SHA}],
    }]})
    results = {}
    for origin in ontology.ORIGINS:
        report = harness_dir / f'catalogue-ontology-{origin}.xml'
        _report(report, ontology.CASES)
        results[origin] = {**ontology.case_results(report), 'core_wheel_sha256': core['artifacts'][0]['sha256'],
                           'harness_wheel_sha256': harness['artifacts'][0]['sha256']}
    proof = {'version': 1, 'kind': 'catalogue-ontology', 'core': {**core, 'run_id': None},
             'harness': harness, 'runtime': ontology.runtime_binding(harness_dir),
             'python': '3.12.15', 'platform': 'linux', 'machine': 'x86_64', 'results': results}
    path = harness_dir / ontology.RECEIPT
    write_json(path, proof)
    assert ontology.verify(harness_dir, harness_commit, hosted=False, core_dir=core_dir) == proof
    with pytest.raises(ReleaseError, match='provenance'):
        ontology.verify(harness_dir, harness_commit, hosted=True, core_dir=core_dir)
    proof['core']['receipt_sha256'] = 'f' * 64
    write_json(path, proof)
    with pytest.raises(ReleaseError, match='Core candidate'):
        ontology.verify(harness_dir, harness_commit, hosted=False, core_dir=core_dir)
    write_json(path, {**proof, 'core': {**core, 'run_id': None}})
    (harness_dir / 'catalogue-ontology-sdist.xml').write_text('<testsuites/>')
    with pytest.raises(ReleaseError, match='qualification'):
        ontology.verify(harness_dir, harness_commit, hosted=False, core_dir=core_dir)


def test_hosted_core_receipt_uses_the_exact_run_and_source(tmp_path, monkeypatch):
    commit = 'a' * 40
    directory = tmp_path / 'core'
    package = _package(directory, ontology.CORE, commit)
    path = directory / 'ontology-core-run.json'
    run = {'id': 123, 'repository': {'full_name': 'B3Cognition/prosaic'}, 'head_sha': commit,
           'conclusion': 'success', 'name': 'Publish SDK', 'path': '.github/workflows/publish.yml',
           'event': 'workflow_dispatch'}
    expected_labels = []

    def qualify(receipts, source, labels):
        assert receipts == directory and source == commit
        expected_labels.extend(labels)

    monkeypatch.setattr(ontology, 'require_qualification', qualify)
    write_json(path, run)
    assert ontology.core_qualification(directory, commit, '123') == {**package, 'run_id': '123'}
    assert len(expected_labels) == len(set(expected_labels)) == 24
    for change in ({'id': 124}, {'head_sha': 'b' * 40}, {'conclusion': 'failure'},
                   {'repository': {'full_name': 'other/prosaic'}}, {'path': 'other.yml'}):
        write_json(path, {**run, **change})
        with pytest.raises(ReleaseError, match='Core ontology|Publish SDK'):
            ontology.core_qualification(directory, commit, '123')
