"""Opt-in example. Configure the copied endpoint before authorizing model calls."""
import argparse
import json
import runpy
from pathlib import Path
import sys
from prosaic_harness import Harness



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--request', type=Path, default=Path(__file__).with_name('request.json'))
    parser.add_argument('--mode', choices=['yaml', 'native'], default='yaml')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live explicitly authorizes model calls; no calls were made')
    request = json.loads(args.request.read_text())
    host = runpy.run_path(str(Path(__file__).with_name('host.py')))
    host['validate_request'](request)
    flow = host['workflow'](mode=args.mode, executable=str(Path(sys.executable).with_name('prosaic')))
    harness = Harness(flow, args.run_dir, validators=host['validators']())
    print(json.dumps(harness.run(request), indent=2))


if __name__ == '__main__':
    main()
