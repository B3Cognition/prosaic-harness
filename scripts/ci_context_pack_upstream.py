"""Build the exact unpublished Runtime commit for ordinary branch CI.

Release promotion still requires successful immutable upstream run receipts.
This helper never manufactures release qualification or a run identifier.
"""
import hashlib
import os
import json
from pathlib import Path
import re
import subprocess
import sys

CORE_SHA='e858a853595746c6930fbe062e84bd8ece1a366aa3b126f2fe11bfb7cb2ceb81'
WHEELS=('b3_prosaic-0.5.0-py3-none-any.whl','b3_prosaic_runtime-0.9.19-py3-none-any.whl')


def verify_branch_upstream(wheels,receipt,expected_commit):
    """Local CI evidence only; never accepted by release.verify_upstream."""
    wheels,receipt=Path(wheels),Path(receipt)
    if receipt.is_symlink() or receipt.stat().st_size>16384:raise ValueError('invalid branch receipt')
    data=json.loads(receipt.read_text())
    if (type(data) is not dict or set(data)!={'version','kind','runtimeSourceCommit','artifacts'} or
            type(data['version']) is not int or data['version']!=1 or data['kind']!='branch-source-build' or
            type(expected_commit) is not str or not re.fullmatch('[0-9a-f]{40}',expected_commit) or
            data['runtimeSourceCommit']!=expected_commit or type(data['artifacts']) is not list or
            len(data['artifacts'])!=2):raise ValueError('invalid branch source identity')
    for item,filename in zip(data['artifacts'],WHEELS):
        path=wheels/filename
        if (type(item) is not dict or set(item)!={'filename','sha256'} or item['filename']!=filename or
                type(item['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',item['sha256']) or
                path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']):
            raise ValueError('branch wheel bytes differ')
    if data['artifacts'][0]['sha256']!=CORE_SHA:raise ValueError('Core witness bytes mismatch')
    return [wheels/name for name in WHEELS]


def write_branch_receipt(wheels,receipt,commit):
    data={'version':1,'kind':'branch-source-build','runtimeSourceCommit':commit,'artifacts':[
        {'filename':name,'sha256':hashlib.sha256((Path(wheels)/name).read_bytes()).hexdigest()} for name in WHEELS]}
    receipt=Path(receipt);receipt.parent.mkdir(parents=True,exist_ok=True)
    receipt.write_text(json.dumps(data,sort_keys=True,indent=2)+'\n')
    verify_branch_upstream(wheels,receipt,commit)


def main():
    expected=os.environ['RUNTIME_COMMIT']
    checkout=Path('.ci-runtime')
    actual=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
    if actual!=expected:raise RuntimeError('Runtime checkout identity mismatch')
    wheels=Path('.ci-upstream/wheels');wheels.mkdir(parents=True,exist_ok=True)
    subprocess.run([sys.executable,'-m','pip','download','--no-deps','--dest',str(wheels),'b3-prosaic==0.5.0'],check=True)
    core=wheels/'b3_prosaic-0.5.0-py3-none-any.whl'
    if hashlib.sha256(core.read_bytes()).hexdigest()!=CORE_SHA:
        raise RuntimeError('Core witness bytes mismatch')
    subprocess.run([sys.executable,'-m','build',str(checkout),'--outdir',str(wheels.resolve())],check=True)
    if not (wheels/'b3_prosaic_runtime-0.9.19-py3-none-any.whl').is_file():
        raise RuntimeError('unexpected Runtime candidate version')
    write_branch_receipt(wheels,Path('.ci-upstream/artifacts/branch-build.json'),expected)


if __name__=='__main__':main()
