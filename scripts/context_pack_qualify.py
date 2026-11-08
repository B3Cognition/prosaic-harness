"""Qualify exact paired SDK artifacts in a fresh wheel-only environment.

Run this with the target Python interpreter, natively or inside a container.
The release roots are outputs of release_artifacts.py build, never checkouts.
"""
import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import zipfile


def sha256(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def release(root,names):
    receipt=json.loads((root/'artifacts/release-receipt.json').read_text())
    assert receipt['version']==1 and re.fullmatch('[0-9a-f]{40}',receipt['source_commit'])
    wheels=[]
    for item in receipt['artifacts']:
        assert Path(item['filename']).name==item['filename']
        path=root/'artifacts'/item['filename']
        assert sha256(path)==item['sha256'],str(path)
        if path.suffix=='.whl': wheels.append(path)
    versions={item['name']:item['version'] for item in receipt['distributions']}
    assert set(versions)==set(names) and len(wheels)==len(names)
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            metadata=BytesParser().parsebytes(archive.read(next(name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))))
        assert versions[metadata['Name']]==metadata['Version']
    return receipt,wheels


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-release',type=Path,required=True)
    parser.add_argument('--harness-release',type=Path,required=True)
    parser.add_argument('--witnesses',type=Path,required=True)
    parser.add_argument('--constraints',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execution-mode',choices=['native','container-native','container-emulated'],default='native')
    args=parser.parse_args()
    rt_root=args.runtime_release.resolve();harness_root=args.harness_release.resolve()
    rt,rt_wheels=release(rt_root,{'b3-prosaic-runtime'})
    harness,harness_wheels=release(harness_root,{'b3-prosaic-harness','b3-prosaic-harness-postgres'})
    witnesses=[args.witnesses.resolve()/name for name in ('b3_prosaic-0.5.0-py3-none-any.whl','b3_prosaic_runtime_postgres-0.3.0-py3-none-any.whl')]
    assert all(path.is_file() for path in witnesses)
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    commands=[]
    env={key:value for key,value in os.environ.items() if key not in {'PYTHONPATH','PYTHONHOME'}}
    def run(label,command,*,timeout=240):
        before=time.monotonic()
        with (output/(label+'.log')).open('w') as log:
            result=subprocess.run(list(map(str,command)),cwd=output,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        commands.append({'label':label,'command':list(map(str,command)),'exitCode':result.returncode,
            'elapsedSeconds':round(time.monotonic()-before,3)})
        return result.returncode==0
    assert run('create-environment',[sys.executable,'-m','venv',output/'env'])
    python=output/'env/bin/python'
    env['PATH']=str(python.parent)+os.pathsep+env.get('PATH','')
    install=[python,'-m','pip','install','--disable-pip-version-check',*witnesses,*rt_wheels,*harness_wheels]
    if args.constraints: install.extend(['--constraint',args.constraints.resolve()])
    installed=run('install',install)
    passed=installed
    if installed:
        passed=run('pip-check',[python,'-m','pip','check']) and passed
        for prefix,root,names in (('runtime',rt_root,('wheel_smoke.py','native_wheel_smoke.py','production_wheel_smoke.py',
                'conversation_wheel_smoke.py','terminal_completion_smoke.py','rule_admission_wheel_smoke.py','context_pack_wheel_smoke.py')),
                ('harness',harness_root,('workflow_factory_smoke.py','conversation_smoke.py','terminal_completion_smoke.py','context_pack_smoke.py'))):
            for name in names:
                passed=run(prefix+'-'+name,[python,'-I',root/'source/scripts'/name]) and passed
        passed=run('harness-context-assembly',[python,'-I',harness_root/'source/scripts/conversation_smoke.py','--context-assembly']) and passed
        passed=run('installed-versions',[python,'-m','pip','list','--format=json']) and passed
    assert release(rt_root,{'b3-prosaic-runtime'})[0]==rt
    assert release(harness_root,{'b3-prosaic-harness','b3-prosaic-harness-postgres'})[0]==harness
    record={'version':1,'python':sys.version,'platform':sys.platform,'machine':platform.machine(),
        'executionMode':args.execution_mode,'driverSha256':sha256(Path(__file__).resolve()),'runtime':rt,'harness':harness,'commands':commands,
        'witnesses':[{'filename':path.name,'sha256':sha256(path)} for path in witnesses],
        'constraintsSha256':sha256(args.constraints.resolve()) if args.constraints else None,'passed':passed}
    (output/'qualification.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'passed':passed,'platform':sys.platform,'machine':platform.machine(),'python':platform.python_version(),
        'executionMode':args.execution_mode,'receipt':str(output/'qualification.json')},sort_keys=True))
    raise SystemExit(0 if passed else 1)


if __name__=='__main__': main()
