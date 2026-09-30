"""Known bad model verdicts cannot bypass deterministic evidence admission."""
from pathlib import Path
import json
import pytest
from prosaic_harness import CheckContext, Harness, Workflow
from prosaic_harness.validation import load_validators
from test_harness import setup, FakeRuntime
from test_validation import edit_flow

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


def context():
    return CheckContext('decision', json.loads((EXAMPLES / 'request.json').read_text()), {}, {}, {})


@pytest.mark.parametrize('claim', [
    {'text': 'Support is confirmed', 'source_id': 'S99', 'quote': 'Confirmed'},
    {'text': 'Evening support is confirmed', 'source_id': 'S9', 'quote': 'Evening support is confirmed.'},
    {'text': '120 checked drafts', 'source_id': 'S2', 'quote': 'Reviewers checked 120 selected daytime drafts.'},
])
def test_unknown_source_invented_quote_and_reassigned_source_are_rejected(claim):
    validator = load_validators(EXAMPLES / 'checks.py')['evidence']
    assert validator.check({'claims': [claim]}, context())


@pytest.mark.parametrize('metric,numerator,denominator,value', [
    ('factual_accuracy', 108, 120, 90),
    ('client_visible_failure_rate', 24, 2400, 1),
    ('client_visible_failure_rate', 66, 2400, 2.75),
])
def test_mislabelled_checklist_and_excluded_timeouts_are_rejected(metric, numerator, denominator, value):
    validator = load_validators(EXAMPLES / 'checks.py')['evidence']
    assert validator.check({'calculations': [{'source_id': 'S4' if metric == 'factual_accuracy' else 'S2',
        'metric': metric, 'numerator': numerator, 'denominator': denominator, 'percentage': value}]}, context())


def test_supported_quote_and_correct_denominator_pass():
    validator = load_validators(EXAMPLES / 'checks.py')['evidence']
    assert validator.check({'claims': [{'text': 'Late delivery is unverified', 'source_id': 'S3',
        'quote': 'delivery to the user is unverified.'}], 'calculations': [{'source_id': 'S2',
        'metric': 'client_visible_failure_rate', 'numerator': 84, 'denominator': 2400, 'percentage': 3.5}]}, context()) == []


def test_bad_final_artifact_rejected_even_when_model_review_passed(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    (tmp_path / 'result.json').write_text('{"type":"object"}')
    def change(d):
        d['steps']['review']['pass'] = 'final_check'
        d['steps']['final_check'] = {'kind': 'check', 'from': 'author', 'validators': ['evidence'],
                                    'pass': 'done', 'fail': 'rejected'}
    bad = {'approved': True, 'claims': [{'text': 'Supported', 'source_id': 'S99', 'quote': 'invented'}]}
    state = Harness(Workflow.load(edit_flow(tmp_path, change)), tmp_path / 'run',
        runtime=FakeRuntime([json.dumps(bad)]), validators=load_validators(EXAMPLES / 'checks.py')).run(context().request)
    assert state['status'] == 'rejected' and state['calls'] == 1
    assert any(e['event'] == 'check_failed' and 'S99' in e['message'] for e in state['history'])
