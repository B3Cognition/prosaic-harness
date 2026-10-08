"""Operator demo only: authenticate/authorize/filter state in your application."""
import argparse
import json
from pathlib import Path
import sys

from prosaic_harness import Harness, Workflow, StoreError
from prosaic_harness_postgres import PostgresRunStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['start', 'status', 'resume'])
    parser.add_argument('--dsn-env', required=True)
    parser.add_argument('--namespace', required=True, help='trusted application namespace, not untrusted tenant input')
    parser.add_argument('--run-id', required=True, help='lowercase UUID hex retained by the application')
    parser.add_argument('--workflow', type=Path, default=Path(__file__).with_name('pause.yml'))
    parser.add_argument('--choice')
    parser.add_argument('--expected-revision')
    parser.add_argument('--retry-interrupted', action='store_true')
    args = parser.parse_args()
    try:
        with PostgresRunStore.from_env(args.dsn_env, namespace=args.namespace) as store:
            store.check_ready()
            h = Harness(Workflow.load(args.workflow.resolve()), store=store, run_id=args.run_id)
            if args.command == 'start':
                content = sys.stdin.read(8 * 1024 * 1024 + 1)
                if len(content.encode('utf-8')) > 8 * 1024 * 1024:
                    raise ValueError('input too large')
                inputs = json.loads(content) if content.strip() else {}
                if not isinstance(inputs, dict):
                    raise ValueError('inputs must be an object')
                h.run(inputs)
            elif args.command == 'resume':
                h.resume(choice=args.choice, expected_revision=args.expected_revision,
                         retry_interrupted=args.retry_interrupted)
            snapshot = h.status()
            result = {'state': snapshot.state, 'revision': snapshot.revision}
        print(json.dumps(result, allow_nan=False))
        return 0
    except StoreError as exc:
        print(json.dumps({'error': exc.code, 'message': str(exc)}), file=sys.stderr)
        return 1
    except Exception:
        print('{"error":"invalid_request","message":"check workflow assets, request and revision"}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
