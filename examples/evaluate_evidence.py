"""Opt-in live comparison of native acquisition and no-tool preloaded evidence.

Every configured profile runs the same final schema and evidence checks. Model
responses are stochastic: a passing run is not a general accuracy guarantee.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path

from prosaic_harness import Harness, Workflow
from prosaic_harness.validation import load_validators
from prosaic_runtime import ProsaicRuntime, RuntimeConfig

EXAMPLES = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='explicitly permit model requests')
    parser.add_argument('--config', type=Path, default=EXAMPLES / 'tokenproxy.yml')
    parser.add_argument('--run-dir', type=Path, required=True, help='new directory for local receipts')
    parser.add_argument('--streaming', choices=['on', 'off', 'both'], default='both')
    parser.add_argument('--mode', choices=['staged', 'preloaded', 'both'], default='both')
    parser.add_argument('--jobs', type=int, choices=[1, 2], default=1)
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required; no requests were made')
    if args.run_dir.exists():
        parser.error('--run-dir must be a new directory')
    if args.mode != 'preloaded' and 'acquisition_v1' not in ProsaicRuntime.capabilities:
        parser.error('staged mode requires development Runtime acquisition_v1; no requests were made')
    config = RuntimeConfig.load(args.config)
    validators = load_validators(EXAMPLES / 'checks.py')
    modes = ['staged', 'preloaded'] if args.mode == 'both' else [args.mode]
    streams = [False, True] if args.streaming == 'both' else [args.streaming == 'on']
    jobs = [(profile, streaming, mode) for profile in config.profiles for streaming in streams for mode in modes]

    def run(job):
        profile, streaming, mode = job
        filename = 'staged-read.yml' if mode == 'staged' else 'preloaded-evidence.yml'
        workflow = Workflow.load(EXAMPLES / filename)
        endpoint = config.profiles[profile]
        workflow.config = replace(config, routes={**config.routes, 'balanced': profile},
            profiles={**config.profiles, profile: replace(endpoint, features={**endpoint.features, 'streaming': streaming})})
        workflow.fingerprint = workflow.current_fingerprint()
        directory = args.run_dir / profile / ('stream' if streaming else 'nonstream') / mode
        state = Harness(workflow, directory, validators=validators).run({'task': 'Summarize evidence/pilot.md; separate observations and unknowns.'})
        reads = 0
        for receipt in (directory / 'attempts').glob('*.json'):
            data = json.loads(receipt.read_text())
            reads += sum(e['event'] == 'tool_completed' and e.get('name') == 'read_file' and e.get('status') == 'ok'
                         for e in data['events'])
        return {'profile': profile, 'model': endpoint.model, 'streaming': streaming, 'mode': mode,
                'status': state['status'], 'reason': state.get('reason'), 'calls': state['calls'],
                'native_reads': reads, 'run_dir': str(directory.resolve())}

    failed = False
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for row in pool.map(run, jobs):
            print(json.dumps(row), flush=True)
            failed |= row['status'] != 'completed'
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
