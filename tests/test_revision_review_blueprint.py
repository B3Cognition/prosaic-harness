"""Copyable cross-step checks use real versioned validators, not model authority."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'examples/revision-review'


def checks():
    spec = importlib.util.spec_from_file_location('revision_review_checks', ROOT / 'checks.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def context(*, flagged=('A',), revised=None):
    original = [{'id': 'A', 'text': 'first'}, {'id': 'B', 'text': 'second'}, {'id': 'C', 'text': 'third'}]
    return SimpleNamespace(step='revised_review', request={'insights': original}, artifacts={
        'first_review': {'findings': [{'insight_id': key, 'text': 'review'} for key in flagged]},
        'revision': {'insights': revised if revised is not None else [
            {'id': 'A', 'text': 'first'}, {'id': 'B', 'text': 'edited'}, {'id': 'C', 'text': 'third'},
            {'id': 'D', 'text': 'new'}]},
    })


@pytest.mark.parametrize('target,accepted', [('A', True), ('B', True), ('C', False), ('D', True), ('invented', False)])
def test_final_findings_require_a_flagged_or_changed_current_insight(target, accepted):
    ctx = context(); before = deepcopy(ctx.__dict__)
    result = checks().review_scope({'findings': [{'insight_id': target, 'text': 'finding'}]}, ctx)
    assert (result == []) is accepted
    assert ctx.__dict__ == before


def test_deleted_flagged_insight_is_not_a_current_review_target():
    ctx = context(revised=[{'id': 'B', 'text': 'edited'}])
    assert checks().review_scope({'findings': [{'insight_id': 'A', 'text': 'finding'}]}, ctx)


@pytest.mark.parametrize('missing', ['first_review', 'revision'])
def test_missing_dependency_refuses(missing):
    ctx = context(); del ctx.artifacts[missing]
    assert checks().review_scope({'findings': []}, ctx)


@pytest.mark.parametrize('insights', [[{'id': 'B', 'text': 'x'}, {'id': 'B', 'text': 'y'}],
    [{'id': '', 'text': 'x'}], [{'id': True, 'text': 'x'}], 'not a list'])
def test_malformed_revision_refuses(insights):
    assert checks().review_scope({'findings': []}, context(revised=insights))


def test_model_changed_id_claim_does_not_authorize_untouched_insight():
    ctx = context(); ctx.artifacts['revision']['changed_ids'] = ['C']
    assert checks().review_scope({'findings': [{'insight_id': 'C', 'text': 'finding'}]}, ctx)


def test_first_review_cannot_flag_an_id_not_in_original_input():
    ctx = context(); ctx.step = 'first_review'; ctx.artifacts = {}
    assert checks().review_scope({'findings': [{'insight_id': 'invented', 'text': 'finding'}]}, ctx)


def test_registry_binds_public_validator_and_explicit_content_version():
    from prosaic_harness import Validator
    registry = checks().validators()
    assert all(type(v) is Validator for v in registry.values())
    assert all(v.version.startswith('revision-review-v1:') for v in registry.values())

from test_transport import endpoint, text


def loaded(tmp_path, url):
    import shutil, sys, yaml
    from prosaic_harness import Workflow
    root = tmp_path / 'blueprint'
    shutil.copytree(ROOT, root)
    config = yaml.safe_load((root / 'runtime.yml').read_text())
    config['profiles']['local']['base_url'] = url
    (root / 'runtime.yml').write_text(yaml.safe_dump(config))
    return Workflow.load(root / 'workflow.yml', executable=str(Path(sys.executable).with_name('prosaic')))


def queue_initial(replies):
    replies.extend([text({'findings': [{'insight_id': 'A', 'text': 'flagged'}]}), text({'insights': [
        {'id': 'A', 'text': 'first'}, {'id': 'B', 'text': 'edited'}, {'id': 'C', 'text': 'third'}]})])


def test_real_workflow_refuses_then_repairs_and_resumes_without_repeating_calls(endpoint, tmp_path):
    import json
    from prosaic_harness import Harness
    url, requests, replies = endpoint
    workflow = loaded(tmp_path, url); registry = checks().validators()
    queue_initial(replies)
    replies.extend([text({'findings': [{'insight_id': 'C', 'text': 'unrelated'}]}),
                    text({'findings': [{'insight_id': 'B', 'text': 'changed'}]})])
    harness = Harness(workflow, tmp_path / 'run', validators=registry)
    state = harness.run(context().request)
    assert state['status'] == 'waiting' and len(requests) == 4
    assert state['outputs']['revised_review']['findings'][0]['insight_id'] == 'B'
    assert state['outputs']['first_review'] == {'findings': [{'insight_id': 'A', 'text': 'flagged'}]}
    assert 'previously flagged' in json.dumps(requests[-1])
    assert 'first_review' in json.dumps(requests[-1]) and 'revision' in json.dumps(requests[-1])
    assert harness.resume(choice='accept')['status'] == 'completed'
    assert Harness(workflow, tmp_path / 'run', validators=registry).resume()['status'] == 'completed'
    assert len(requests) == 4


def test_refusal_exhausts_only_final_step_attempts_without_accepting_output(endpoint, tmp_path):
    from prosaic_harness import Harness
    url, requests, replies = endpoint
    queue_initial(replies)
    replies.extend([text({'findings': [{'insight_id': 'C', 'text': 'unrelated'}]})] * 2)
    harness = Harness(loaded(tmp_path, url), tmp_path / 'run', validators=checks().validators())
    state = harness.run(context().request)
    assert state['status'] == 'blocked' and state['reason'] == 'attempt_limit'
    assert 'revised_review' not in state['outputs'] and len(requests) == 4
    assert harness.resume()['reason'] == 'attempt_limit' and len(requests) == 4


def test_changed_validator_refuses_persisted_resume_before_another_request(endpoint, tmp_path):
    from prosaic_harness import Harness, Validator
    url, requests, replies = endpoint
    workflow = loaded(tmp_path, url)
    queue_initial(replies); replies.append(text({'findings': []}))
    registry = checks().validators()
    harness = Harness(workflow, tmp_path / 'run', validators=registry)
    assert harness.run(context().request)['status'] == 'waiting'
    import runpy
    copied_checks = workflow.path.parent / 'checks.py'
    copied_checks.write_text(copied_checks.read_text() + '\n# A new policy revision.\n')
    changed = runpy.run_path(str(copied_checks))['validators']()
    assert all(changed[name].version != value.version for name, value in registry.items())
    with pytest.raises(ValueError):
        Harness(workflow, tmp_path / 'run', validators=changed).resume(choice='accept')
    assert len(requests) == 3


def test_duplicate_revision_ids_stop_before_final_review(endpoint, tmp_path):
    from prosaic_harness import Harness
    url, requests, replies = endpoint
    replies.extend([text({'findings': []}),text({'insights': [
        {'id': 'B', 'text': 'one'}, {'id': 'B', 'text': 'two'}]})])
    state = Harness(loaded(tmp_path, url), tmp_path / 'run', validators=checks().validators()).run(context().request)
    assert state['status'] == 'blocked' and state['reason'] == 'attempt_limit'
    assert len(requests) == 2 and 'revision' not in state['outputs']


def test_replacing_first_review_makes_prior_revision_stale_before_final_dispatch(endpoint, tmp_path):
    import json, sys, yaml
    from prosaic_harness import Harness, Workflow
    url, requests, replies = endpoint
    prepared = loaded(tmp_path, url)
    path = prepared.path
    document = yaml.safe_load(path.read_text())
    document['limits'].update(max_calls=5, max_visits=2)
    document['steps']['first_review'].update(next='route', max_visits=2)
    document['steps']['revision']['next'] = 'first_review'
    document['steps']['route'] = {'kind': 'gate', 'from': 'first_review', 'field': ['repeat'],
                                 'equals': True, 'pass': 'revised_review', 'fail': 'revision', 'max_visits': 2}
    schema_path = path.parent / 'schemas/review.json'
    schema = json.loads(schema_path.read_text()); schema['properties']['repeat'] = {'type': 'boolean'}
    schema_path.write_text(json.dumps(schema)); path.write_text(yaml.safe_dump(document))
    workflow = Workflow.load(path, executable=str(Path(sys.executable).with_name('prosaic')))
    replies.extend([text({'findings': [{'insight_id': 'A', 'text': 'flagged'}], 'repeat': False}),
        text({'insights': [{'id': 'A', 'text': 'edited'}]}),
        text({'findings': [], 'repeat': True})])
    state = Harness(workflow, tmp_path / 'run', validators=checks().validators()).run(context().request)
    assert state['status'] == 'blocked' and state['reason'] == 'stale_artifact'
    assert len(requests) == 3 and 'revised_review' not in state['outputs']
