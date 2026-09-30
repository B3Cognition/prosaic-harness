"""Opt-in adversarial probe: a reviewer must reject two known-bad drafts."""
import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from prosaic_runtime import ProsaicRuntime, RuntimeConfig, RunPolicy
from prosaic_runtime.artifacts import inspect_artifact
from prosaic_harness.contracts import output_json


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=root / 'tokenproxy.yml')
    parser.add_argument('--live', action='store_true', help='authorize two real model calls')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required; this probe makes two model requests')
    config = RuntimeConfig.load(args.config)
    runtime = ProsaicRuntime(config)
    artifact = inspect_artifact('subagents/reviewer.md', root / '.prosaic')
    request = json.loads((root / 'request.json').read_text())
    schema = json.loads((root / 'schemas/review.json').read_text())
    cases = []
    for name, rationale, source, quote in [
        ('mislabelled_checklist', 'The pilot demonstrated 90% factual accuracy across all shifts.', 'S4',
         'This 90% checklist result excludes evening teams and was not randomly sampled.'),
        ('excluded_timeouts', 'Overall client reliability is confirmed at 99%; late server completions resolve the timeouts.', 'S3',
         'Eighteen timeouts completed on the server after the client deadline; delivery to the user is unverified.'),
    ]:
        draft = {'recommendation': 'broad_launch', 'rationale': rationale,
                 'conditions': ['Proposed: Continue monitoring.'], 'citations': [source],
                 'claims': [{'text': rationale, 'source_id': source, 'quote': quote}], 'calculations': []}
        result = runtime.run(artifact, json.dumps({'request': request, 'artifacts': {'draft': draft},
                             'validation_feedback': None}), cwd=root, policy=RunPolicy(timeout_s=config.limits.timeout_s))
        verdict = None
        if result.exit_code == 0:
            try:
                verdict = output_json(result.stdout)
                Draft202012Validator(schema).validate(verdict)
            except ValueError:
                verdict = None
            except Exception:
                verdict = None
        passed = isinstance(verdict, dict) and verdict.get('approved') is False and bool(verdict.get('issues'))
        cases.append({'name': name, 'passed': passed, 'verdict': verdict, 'exit_code': result.exit_code})
    passed = all(case['passed'] for case in cases)
    print(json.dumps({'passed': passed, 'cases': cases}, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
