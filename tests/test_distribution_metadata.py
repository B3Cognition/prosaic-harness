"""The clean Git snapshot must produce index-compatible public SDK wheels."""
from email.parser import BytesParser
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

from packaging.requirements import Requirement
import pytest


@pytest.mark.parametrize('project,name,version,module,dependency,entry', [
    ('.', 'b3-prosaic-harness', '0.7.1', 'prosaic_harness',
     'b3-prosaic-runtime>=0.8,<0.9', 'prosaic-harness = prosaic_harness.cli:main'),
    ('adapters/postgres', 'b3-prosaic-harness-postgres', '0.2.1',
     'prosaic_harness_postgres', 'b3-prosaic-harness>=0.7,<0.8',
     'prosaic-harness-postgres = prosaic_harness_postgres.cli:main'),
])
def test_clean_wheel_public_identity_and_dependencies(tmp_path, project, name,
                                                     version, module, dependency, entry):
    root = Path(__file__).resolve().parents[1]
    # An explicit staged tree permits the regression to run before the metadata
    # commit; HEAD is the ordinary CI and committed-candidate contract.
    revision = os.environ.get('PROSAIC_RELEASE_REF', 'HEAD')
    assert not revision.startswith('-')
    archive = subprocess.check_output(['git', 'archive', '--format=tar', revision], cwd=root)
    source = tmp_path / 'source'
    source.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as files:
        files.extractall(source, filter='data')
    distributions = tmp_path / 'dist'
    result = subprocess.run([sys.executable, '-m', 'build', '--wheel', '--no-isolation',
                             '--outdir', str(distributions), str(source / project)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(distributions.glob('*.whl'))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        metadata_path = next(path for path in names if path.endswith('.dist-info/METADATA'))
        metadata = BytesParser().parsebytes(wheel.read(metadata_path))
        assert metadata['Name'] == name
        assert metadata['Version'] == version
        requirements = [Requirement(value) for value in metadata.get_all('Requires-Dist', [])]
        assert all(requirement.url is None for requirement in requirements)
        assert Requirement(dependency) in requirements
        assert not {'prosaic', 'prosaic-runtime', 'prosaic-harness'} & {
            requirement.name for requirement in requirements}
        assert f"__version__ = '{version}'".encode() in wheel.read(f'{module}/__init__.py')
        assert entry.encode() in wheel.read(metadata_path.replace('METADATA', 'entry_points.txt'))
        assert metadata['License-Expression'] == 'Apache-2.0'
        assert set(metadata.get_all('License-File', [])) == {'LICENSE', 'NOTICE'}
        license_root = metadata_path.removesuffix('METADATA') + 'licenses/'
        for filename in ('LICENSE', 'NOTICE'):
            assert wheel.read(license_root + filename) == (source / project / filename).read_bytes()
        if project == '.':
            assert not any(path.startswith('prosaic_harness_postgres/') for path in names)
            assert not any(requirement.name.startswith('psycopg') for requirement in requirements)
