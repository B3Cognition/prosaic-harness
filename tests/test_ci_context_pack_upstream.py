"""Branch-build evidence is explicitly distinct from hosted release evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest


@pytest.fixture
def upstream(tmp_path,monkeypatch):
    path=Path(__file__).resolve().parents[1]/'scripts/ci_context_pack_upstream.py'
    spec=importlib.util.spec_from_file_location('branch_upstream',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    core=tmp_path/'b3_prosaic-0.5.0-py3-none-any.whl';core.write_bytes(b'core-fixture')
    runtime=tmp_path/'b3_prosaic_runtime-0.9.21-py3-none-any.whl';runtime.write_bytes(b'runtime-fixture')
    monkeypatch.setattr(module,'CORE_SHA',hashlib.sha256(core.read_bytes()).hexdigest(),raising=False)
    return module,tmp_path,'a'*40


def test_branch_build_receipt_admits_only_exact_bytes(upstream):
    module,wheels,commit=upstream
    receipt=wheels/'branch-build.json'
    module.write_branch_receipt(wheels,receipt,commit)
    assert len(module.verify_branch_upstream(wheels,receipt,commit))==2
    assert json.loads(receipt.read_text())['kind']=='branch-source-build'


def test_branch_receipt_cannot_replace_hosted_release_qualification(upstream):
    module,wheels,commit=upstream
    module.write_branch_receipt(wheels,wheels/'upstream-receipt.json',commit)
    path=Path(__file__).resolve().parents[1]/'scripts/release_artifacts.py'
    spec=importlib.util.spec_from_file_location('release_artifacts',path)
    release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
    with pytest.raises(release.ReleaseError):release.verify_upstream(wheels,wheels)


@pytest.mark.parametrize('damage',['source','runtime','core','extra','symlink','hosted'])
def test_branch_build_receipt_refuses_substitution(upstream,damage):
    module,wheels,commit=upstream;receipt=wheels/'branch-build.json'
    module.write_branch_receipt(wheels,receipt,commit)
    data=json.loads(receipt.read_text())
    if damage=='source':data['runtimeSourceCommit']='b'*40
    elif damage in {'runtime','core'}:
        wheel=next(wheels.glob('b3_prosaic_runtime-*.whl' if damage=='runtime' else 'b3_prosaic-*.whl'))
        wheel.write_bytes(b'changed')
    elif damage=='extra':data['run_id']='12345'
    elif damage=='hosted':data['kind']='hosted-release'
    else:
        old=wheels/'saved.json';receipt.rename(old);receipt.symlink_to(old)
    if damage!='symlink':receipt.write_text(json.dumps(data))
    with pytest.raises((ValueError,OSError)):module.verify_branch_upstream(wheels,receipt,commit)
