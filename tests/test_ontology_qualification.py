"""Receipt checks for the separate installed ontology combination."""
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
try:
    from catalogue_ontology_qualify import case_results
    from release_artifacts import ReleaseError
finally:
    sys.path.pop(0)


def _report(path, cases):
    path.write_text(f'<testsuites><testsuite tests="{len(cases)}" errors="0" failures="0" skipped="0">'
                    + ''.join(f'<testcase name="{case}"/>' for case in cases) + '</testsuite></testsuites>')


def test_compatibility_requires_exact_cases_and_no_skips(tmp_path):
    path = tmp_path / 'results.xml'
    expected = ['first', 'second']
    _report(path, expected)
    assert case_results(path, expected)['cases'] == expected
    for cases in ([], ['first'], ['first', 'first'], ['first', 'unexpected']):
        _report(path, cases)
        with pytest.raises(ReleaseError, match='ontology qualification'):
            case_results(path, expected)
    _report(path, expected)
    path.write_text(path.read_text().replace('name="first"/>', 'name="first"><skipped/></testcase>'))
    with pytest.raises(ReleaseError, match='ontology qualification'):
        case_results(path, expected)
