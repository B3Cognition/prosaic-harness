"""Local workflow CLI; stdout is JSON only when --events is selected."""
import argparse
import json
from pathlib import Path
import sys

from prosaic_runtime.console import Progress
from .engine import Harness
from .workflow import Workflow
from .store import read_json
from .validation import load_validators


def main(argv=None):
    parser = argparse.ArgumentParser(prog='prosaic-harness')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('validate', 'run', 'resume'):
        p = sub.add_parser(command)
        p.add_argument('workflow', type=Path)
        p.add_argument('--checks', type=Path, help='explicitly execute this trusted Python CHECKS file (not sandboxed)')
        if command != 'validate':
            p.add_argument('--run-dir', type=Path, required=True)
            p.add_argument('--events', action='store_true')
        if command == 'run':
            p.add_argument('--input', type=Path, required=True, help='JSON request file')
        elif command == 'resume':
            p.add_argument('--choice', help='named answer to a pending human pause')
            p.add_argument('--retry-interrupted', action='store_true', help='authorize another request when no receipt survived')
            p.add_argument('--response', type=Path, help='JSON payload validated by the pending pause response_schema')
    p = sub.add_parser('status')
    p.add_argument('--run-dir', type=Path, required=True)
    p.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'status':
            state = read_json(args.run_dir / 'run.json')
        else:
            workflow = Workflow.load(args.workflow)
            validators = load_validators(args.checks) if args.checks else {}
            if args.command == 'validate':
                Harness(workflow, '.', validators=validators)
                print(f'Validated {len(workflow.definition["steps"])} steps; fingerprint {workflow.fingerprint}')
                return 0
            with Progress(quiet=args.events) as progress:
                def event(value):
                    if args.events:
                        print(json.dumps(value), flush=True)
                    elif value['event'] in {'started', 'completed', 'tool_started', 'tool_completed',
                                             'step_started', 'accepted', 'validation_failed', 'transition',
                                             'waiting', 'blocked', 'finished'}:
                        progress.write(f'{value.get("step", "")}: {value["event"]}' +
                                       (f' {value["model"]}' if 'model' in value else ''))
                harness = Harness(workflow, args.run_dir, on_event=event, validators=validators)
                if args.command == 'run':
                    state = harness.run(read_json(args.input))
                else:
                    state = harness.resume(choice=args.choice, response=read_json(args.response) if args.response else None,
                                           retry_interrupted=args.retry_interrupted)
        report = {key: state[key] for key in ('status', 'current', 'calls', 'reason', 'outputs')}
        if state['status'] == 'waiting':
            report.update(question=state['question'], choices=state['choices'])
        if getattr(args, 'events', False) or getattr(args, 'json', False):
            print(json.dumps({'event': 'run_status', **report}), flush=True)
        else:
            print(f"{state['status']}: step={state['current']} calls={state['calls']} reason={state['reason']}")
            if state['status'] == 'waiting':
                print(state['question'] + ' Choices: ' + ', '.join(state['choices']))
            print(json.dumps(state['outputs'], indent=2))
        return 0 if state['status'] in {'completed', 'waiting'} else 1
    except KeyboardInterrupt:
        print('Interrupted; resume inspects the pending request before retrying.', file=sys.stderr)
        return 130
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
