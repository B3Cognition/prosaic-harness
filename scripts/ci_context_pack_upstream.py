"""Build the exact unpublished Runtime commit for ordinary branch CI.

Release promotion still requires successful immutable upstream run receipts.
This helper never manufactures release qualification or a run identifier.
"""
import hashlib
import os
from pathlib import Path
import subprocess
import sys


def main():
    expected=os.environ['RUNTIME_COMMIT']
    checkout=Path('.ci-runtime')
    actual=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
    if actual!=expected:raise RuntimeError('Runtime checkout identity mismatch')
    wheels=Path('.ci-upstream/wheels');wheels.mkdir(parents=True,exist_ok=True)
    subprocess.run([sys.executable,'-m','pip','download','--no-deps','--dest',str(wheels),'b3-prosaic==0.5.0'],check=True)
    core=wheels/'b3_prosaic-0.5.0-py3-none-any.whl'
    if hashlib.sha256(core.read_bytes()).hexdigest()!='e858a853595746c6930fbe062e84bd8ece1a366aa3b126f2fe11bfb7cb2ceb81':
        raise RuntimeError('Core witness bytes mismatch')
    subprocess.run([sys.executable,'-m','build',str(checkout),'--outdir',str(wheels.resolve())],check=True)
    if not (wheels/'b3_prosaic_runtime-0.9.19.dev0-py3-none-any.whl').is_file():
        raise RuntimeError('unexpected Runtime candidate version')


if __name__=='__main__':main()
