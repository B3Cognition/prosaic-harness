"""Explicitly opt-in example; configure a copied blueprint before real model calls."""
import argparse
import json
from pathlib import Path

from prosaic_harness import Harness, Workflow
from checks import validators, _index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--request', type=Path, default=Path(__file__).with_name('request.json'))
    args = parser.parse_args()
    if not args.live:
        parser.error('--live explicitly authorizes model calls; no calls were made')
    request = json.loads(args.request.read_text())
    _index(request, 'insights', 'id')  # Host input validation before reserving or executing a run.
    harness = Harness(Workflow.load(Path(__file__).with_name('workflow.yml')),
                      args.run_dir, validators=validators())
    print(json.dumps(harness.run(request), indent=2))


if __name__ == '__main__':
    main()
