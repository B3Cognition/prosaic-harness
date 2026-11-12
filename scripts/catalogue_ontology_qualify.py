"""Qualify the exact Core/Harness candidate pair with the released Runtime."""
import argparse
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
from xml.etree import ElementTree

from release_artifacts import (ReleaseError, digest, require_qualification, tar_contents,
                               validate_candidate_run, validate_upstream_chain, verify_receipt, write_json)


CORE = 'b3_prosaic-0.5.1'
HARNESS = 'b3_prosaic_harness-0.9.18'
RUNTIME = 'b3_prosaic_runtime-0.9.23-py3-none-any.whl'
RUNTIME_SHA = '5caab59f6d0ffd14299ee0840dd5f9b58b4e4f4a1b724ff6e3e2fa1699f08fd8'
RUNTIME_SOURCE = '48c10ac9aeb18bd06f53015df0624b35d5254646'
RUNTIME_RUN = '43210113804'
RECEIPT = 'catalogue-ontology-compatibility.json'
ORIGINS = ('wheel', 'sdist')
CASES = sorted((
    'test_exact_installed_ontology_sdk',
    'test_projection_uses_existing_visibility_and_owns_the_result',
    'test_attachment_rejects_unknown_aliases[agents]',
    'test_attachment_rejects_unknown_aliases[tools]',
    'test_delegate_aliases_keep_the_existing_admission_boundary',
    'test_ontology_cannot_be_authored_and_does_not_change_saved_identity',
))


def case_results(path, expected=CASES):
    try:
        raw = path.read_bytes()
        suite, = ElementTree.fromstring(raw).iter('testsuite')
        cases = list(suite.iter('testcase'))
        counts = [int(suite.attrib[key]) for key in ('tests', 'failures', 'errors', 'skipped')]
        names = sorted(case.attrib['name'] for case in cases)
    except (OSError, ElementTree.ParseError, KeyError, ValueError) as error:
        raise ReleaseError('invalid ontology qualification result') from error
    if (names != expected or counts != [len(expected), 0, 0, 0]
            or any(case.find(tag) is not None for case in cases for tag in ('failure', 'error', 'skipped'))):
        raise ReleaseError('incomplete ontology qualification result')
    return {'cases': names, 'junit_sha256': digest(raw)}


def package_binding(directory, commit, prefix):
    receipt = verify_receipt(directory, commit)
    names = {prefix + '-py3-none-any.whl', prefix + '.tar.gz'}
    artifacts = [item for item in receipt['artifacts'] if item['filename'] in names]
    if {item['filename'] for item in artifacts} != names:
        raise ReleaseError('incorrect ontology qualification package')
    return {'source_commit': commit, 'receipt_sha256': digest(
        (directory / 'release-receipt.json').read_bytes()), 'artifacts': artifacts}


def runtime_binding(directory):
    raw = (directory / 'upstream-receipt.json').read_bytes()
    upstream = json.loads(raw)
    validate_upstream_chain(upstream)
    runtime, = (item for item in upstream['candidates']
                if item['repository'] == 'B3Cognition/prosaic-runtime')
    if (runtime['source_commit'] != RUNTIME_SOURCE or runtime['run_id'] != RUNTIME_RUN
            or {'filename': RUNTIME, 'sha256': RUNTIME_SHA} not in runtime['wheels']):
        raise ReleaseError('ontology requires the original published Runtime lineage')
    return {'source_commit': RUNTIME_SOURCE, 'run_id': RUNTIME_RUN, 'filename': RUNTIME,
            'sha256': RUNTIME_SHA, 'receipt_sha256': runtime['receipt_sha256'],
            'upstream_sha256': runtime['upstream_sha256'], 'harness_upstream_sha256': digest(raw)}


def core_qualification(directory, commit, run_id):
    if run_id is not None:
        if not re.fullmatch(r'[1-9][0-9]*', run_id):
            raise ReleaseError('invalid Core ontology qualification run')
        run = json.loads((directory / 'ontology-core-run.json').read_bytes())
        validate_candidate_run(run, commit)
        if run['id'] != int(run_id) or run['repository']['full_name'] != 'B3Cognition/prosaic':
            raise ReleaseError('Core ontology qualification run identity differs')
        labels = [f'linux-{runner}-{version}-{origin}'
                  for runner in ('ubuntu-24.04', 'ubuntu-24.04-arm')
                  for version in ('3.11', '3.12', '3.13')
                  for origin in ('source', 'wheel', 'sdist')]
        labels += [f'windows-{kind}{version}' for version in ('3.11', '3.12', '3.13')
                   for kind in ('', 'ontology-')]
        require_qualification(directory, commit, labels)
    return {**package_binding(directory, commit, CORE), 'run_id': run_id}


def fetch_core(directory, commit, run_id):
    if not re.fullmatch(r'[1-9][0-9]*', run_id or ''):
        raise ReleaseError('invalid Core ontology qualification run')
    run = json.loads(subprocess.check_output([
        'gh', 'api', f'repos/B3Cognition/prosaic/actions/runs/{run_id}'], timeout=60))
    validate_candidate_run(run, commit)
    subprocess.run(['gh', 'run', 'download', run_id, '--repo', 'B3Cognition/prosaic',
                    '--name', 'qualified-release', '--dir', str(directory)], check=True, timeout=120)
    write_json(directory / 'ontology-core-run.json', run)
    return core_qualification(directory, commit, run_id)


def rebuild(archive, directory):
    source = directory / 'source'
    source.mkdir(parents=True)
    contents = tar_contents(archive.read_bytes())
    roots = {path.split('/')[0] for path in contents}
    root, = roots
    for name, content in contents.items():
        file = source / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
    wheels = directory / 'wheels'
    subprocess.run([sys.executable, '-m', 'build', '--no-isolation', '--wheel',
                    '--outdir', str(wheels), str(source / root)], check=True)
    wheel, = wheels.glob('*.whl')
    return wheel


def qualify(directory, commit, core_dir, core_commit, runtime_wheel, *, core_run=None):
    core = core_qualification(core_dir, core_commit, core_run)
    harness = package_binding(directory, commit, HARNESS)
    runtime = runtime_binding(directory)
    if runtime_wheel.name != RUNTIME or digest(runtime_wheel.read_bytes()) != runtime['sha256']:
        raise ReleaseError('retained Runtime wheel digest differs')
    (directory / RECEIPT).unlink(missing_ok=True)
    test = Path(__file__).resolve().parents[1] / 'qualification/test_catalogue_ontology.py'
    records = {}
    for origin in ORIGINS:
        with tempfile.TemporaryDirectory(prefix='ontology-qualification-') as temporary:
            work = Path(temporary)
            report = directory / f'catalogue-ontology-{origin}.xml'
            report.unlink(missing_ok=True)
            if origin == 'wheel':
                core_wheel = core_dir / (CORE + '-py3-none-any.whl')
                harness_wheel = directory / (HARNESS + '-py3-none-any.whl')
            else:
                core_wheel = rebuild(core_dir / (CORE + '.tar.gz'), work / 'core')
                harness_wheel = rebuild(directory / (HARNESS + '.tar.gz'), work / 'harness')
            subprocess.run([sys.executable, '-m', 'venv', str(work / 'env')], check=True)
            python = work / 'env/bin/python'
            subprocess.run([str(python), '-m', 'pip', 'install', 'pytest',
                            str(core_wheel), str(harness_wheel), str(runtime_wheel)], check=True)
            subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
            subprocess.run([str(python), '-I', '-m', 'pytest', '-o', 'pythonpath=',
                            '-q', str(test), f'--junitxml={report}'], cwd=work, check=True)
            records[origin] = {**case_results(report), 'core_wheel_sha256': digest(core_wheel.read_bytes()),
                               'harness_wheel_sha256': digest(harness_wheel.read_bytes())}
    write_json(directory / RECEIPT, {'version': 1, 'kind': 'catalogue-ontology', 'core': core,
        'harness': harness, 'runtime': runtime, 'python': platform.python_version(),
        'platform': sys.platform, 'machine': platform.machine(), 'results': records})
    return verify(directory, commit, hosted=core_run is not None, core_dir=core_dir)


def verify(directory, commit, *, hosted, core_dir=None):
    record = json.loads((directory / RECEIPT).read_bytes())
    core, results = record['core'], record['results']
    if (record['version'] != 1 or record['kind'] != 'catalogue-ontology'
            or record['harness'] != package_binding(directory, commit, HARNESS)
            or record['runtime'] != runtime_binding(directory)
            or not re.fullmatch(r'[0-9a-f]{40}', core['source_commit'])
            or not re.fullmatch(r'[0-9a-f]{64}', core['receipt_sha256'])
            or (hosted and (not re.fullmatch(r'[1-9][0-9]*', core['run_id'] or '')
                            or record['platform'] != 'linux' or record['machine'] != 'x86_64'))
            or set(results) != set(ORIGINS)):
        raise ReleaseError('ontology compatibility provenance differs')
    if core_dir is not None:
        verified_core = core_qualification(core_dir, core['source_commit'], core['run_id'])
    elif hosted:
        with tempfile.TemporaryDirectory(prefix='ontology-core-evidence-') as temporary:
            verified_core = fetch_core(Path(temporary), core['source_commit'], core['run_id'])
    else:
        raise ReleaseError('Core candidate evidence is required')
    if verified_core != core:
        raise ReleaseError('Core candidate compatibility binding differs')
    for package, prefix in (('core', CORE), ('harness', HARNESS)):
        artifacts = record[package]['artifacts']
        hashes = {item['filename']: item['sha256'] for item in artifacts}
        wheel = prefix + '-py3-none-any.whl'
        if (len(artifacts) != 2 or set(hashes) != {wheel, prefix + '.tar.gz'}
                or any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in hashes.values())
                or results['wheel'][package + '_wheel_sha256'] != hashes[wheel]):
            raise ReleaseError('ontology qualification package binding differs')
    for origin, result in results.items():
        evidence = case_results(directory / f'catalogue-ontology-{origin}.xml')
        if (any(result[key] != value for key, value in evidence.items())
                or any(not re.fullmatch(r'[0-9a-f]{64}', result[key])
                       for key in ('core_wheel_sha256', 'harness_wheel_sha256'))):
            raise ReleaseError('ontology qualification result digest differs')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('fetch-core', 'qualify', 'verify'))
    parser.add_argument('--directory', type=lambda value: Path(value).resolve(), required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--core-directory', type=lambda value: Path(value).resolve())
    parser.add_argument('--core-commit')
    parser.add_argument('--core-run')
    parser.add_argument('--runtime-wheel', type=lambda value: Path(value).resolve())
    parser.add_argument('--hosted', action='store_true')
    args = parser.parse_args()
    if args.action == 'fetch-core':
        fetch_core(args.directory, args.commit, args.core_run)
    elif args.action == 'qualify':
        if not all((args.core_directory, args.core_commit, args.runtime_wheel)):
            parser.error('qualification requires Core candidate artifacts and a retained Runtime wheel')
        qualify(args.directory, args.commit, args.core_directory, args.core_commit,
                args.runtime_wheel, core_run=args.core_run)
    else:
        verify(args.directory, args.commit, hosted=args.hosted, core_dir=args.core_directory)


if __name__ == '__main__':
    main()
