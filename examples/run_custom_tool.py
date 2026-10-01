"""Embed native custom tools with deterministic admission and bound human approval."""
import argparse
import json
from pathlib import Path
import sys
from prosaic_harness import Harness, Workflow
from prosaic_harness.validation import load_validators, Validator
from prosaic_runtime import RuntimeConfig
from catalog_tools import make_tools, load_catalog

EXAMPLES = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--sku', default='SKU-001')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--choice', choices=['approve', 'reject'])
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required for run and resume (resume may perform inference)')
    if args.choice and not args.resume:
        parser.error('--choice requires --resume')
    try:
        workflow = Workflow.load(EXAMPLES / 'catalog-tool.yml', custom_tools=make_tools())
        if args.config:
            workflow.config = RuntimeConfig.load(args.config)
            workflow.fingerprint = workflow.current_fingerprint()
        checks = load_validators(EXAMPLES / 'catalog-checks.py')
        # Validator identity also binds fixed data, not just the check's code bytes.
        _, checksum = load_catalog()
        checks = {name: Validator(check.version + ':' + checksum, check.check) for name, check in checks.items()}
        harness = Harness(workflow, args.run_dir, validators=checks)
        state = harness.resume(choice=args.choice) if args.resume else harness.run({'sku': args.sku})
        print(json.dumps({'status': state['status'], 'reason': state['reason'], 'outputs': state['outputs'],
                          'calls': state['calls'], 'question': state.get('question'), 'choices': state.get('choices')}))
        return 0 if state['status'] in {'waiting', 'completed', 'rejected'} else 1
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
