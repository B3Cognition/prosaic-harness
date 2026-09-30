"""Embed the same workflow controller through its public Python API."""
import argparse
import json
from pathlib import Path

from prosaic_harness import Harness, Workflow
from prosaic_harness.validation import load_validators


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('workflow', type=Path)
    p.add_argument('--input', type=Path)
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--choice')
    p.add_argument('--checks', type=Path, help='trusted local validation code')
    args = p.parse_args()
    if not args.resume and args.input is None:
        p.error('--input is required for a new run')
    h = Harness(Workflow.load(args.workflow), args.run_dir,
                validators=load_validators(args.checks) if args.checks else {})
    state = h.resume(choice=args.choice) if args.resume else h.run(json.loads(args.input.read_text()))
    print(json.dumps({'status': state['status'], 'outputs': state['outputs']}, indent=2))
    return 0 if state['status'] in {'completed', 'waiting'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
