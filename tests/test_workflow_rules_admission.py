"""Workflow rule permission, immutable binding and legacy identity contracts."""
import json
from pathlib import Path
import sys

import pytest
import yaml

from prosaic_harness import (Harness, Workflow, WorkflowBindings, WorkflowBundle,
    WorkflowCatalog, WorkflowFactory, WorkflowPolicy, WorkflowAdmissionError)
from prosaic_runtime import Guard, ProsaicArtifact, ProsaicRuntime, Verdict
from test_workflow_factory import config

TAG = '<!-- enforce: review_scope(stage=final, on_violation=retry) -->'
CAPS = {'max_provider_requests_per_invocation': 2, 'max_tool_calls_per_invocation': 0}
SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
          'required': ['ok'], 'additionalProperties': False}


def guard(*, version='review-scope-v1', check=None, name='review_scope', **options):
    return Guard(name, version, ('final',), check or (lambda stage, ctx: Verdict(True)), **options)


def artifact(body=None):
    return ProsaicArtifact.from_inspection({'id': 'subagents/reviewer.md', 'type': 'subagent',
        'frontmatter': {'name': 'reviewer', 'description': 'Review synthetic evidence', 'tools': []},
        'body': body if body is not None else 'ALWAYS check the accepted facts. ' + TAG})


def definition(*, caps=None):
    return {'version': 1, 'name': 'workflow-rules', 'start': 'review',
        **({'limits': caps} if caps is not None else {}), 'steps': {
            'review': {'kind': 'agent', 'agent': 'reviewer', 'schema': 'result', 'next': 'done'},
            'done': {'kind': 'finish', 'requires': ['review']}}}


def factory(*, registered=None, allowed=('review_scope',), body=None, caps=True,
            cfg=None, binding_options=None, policy_options=None):
    values = dict(allowed_agents={'reviewer'}, allowed_schemas={'result'},
                  allowed_guards=set(allowed))
    if caps: values.update(CAPS)
    values.update(policy_options or {})
    return WorkflowFactory(catalog=WorkflowCatalog(agents={'reviewer': artifact(body)}, schemas={'result': SCHEMA}),
        bindings=WorkflowBindings(config=cfg or config(allowed_tools=frozenset()),
            guards=[guard()] if registered is None else registered, **(binding_options or {})),
        policy=WorkflowPolicy(**values))


def yaml_project(tmp_path, *, tagged=True, caps=True):
    root = tmp_path / 'project';(root / '.prosaic/subagents').mkdir(parents=True)
    (root / '.prosaic/subagents/reviewer.md').write_text(
        '---\nname: reviewer\ndescription: Review synthetic evidence\ntools: []\n---\n'
        + ('ALWAYS check the accepted facts. ' + TAG if tagged else 'Return valid JSON only.'))
    (root / 'schema.json').write_text(json.dumps(SCHEMA))
    (root / 'runtime.yml').write_text(yaml.safe_dump({'default_profile': 'local', 'allowed_tools': [],
        'profiles': {'local': {'base_url': 'http://localhost:9/v1', 'model': 'synthetic',
                             'features': {'streaming': False}}}}))
    graph = definition(caps={**{'max_calls': 2, 'max_visits': 1, 'timeout_s': 30}, **(CAPS if caps else {})})
    graph.update(source='.prosaic', runtime='runtime.yml')
    graph['steps']['review'].update(agent='subagents/reviewer.md', schema='schema.json')
    (root / 'workflow.yml').write_text(yaml.safe_dump(graph))
    return root / 'workflow.yml'


def load(path, **options):
    return Workflow.load(path, executable=str(Path(sys.executable).with_name('prosaic')), **options)


def test_native_rules_are_admitted_without_guard_callbacks_or_runtime_construction(monkeypatch):
    calls=[]
    f = factory(registered=[guard(check=lambda *args: calls.append(args) or Verdict(True))])
    def forbidden(*args, **kwargs): raise AssertionError('admission constructed Runtime')
    monkeypatch.setattr(ProsaicRuntime, '__init__', forbidden)
    flow = f.build(definition())
    assert flow.current_fingerprint() == flow.fingerprint and calls == []


@pytest.mark.parametrize('mode', ['unregistered', 'not-allowed', 'missing-caps'])
def test_guarded_native_graph_refuses_missing_host_permission(mode):
    options = {'unregistered': {'registered': []}, 'not-allowed': {'allowed': ()},
               'missing-caps': {'caps': False}}[mode]
    with pytest.raises(WorkflowAdmissionError): factory(**options).build(definition())


def test_proposal_caps_only_lower_explicit_host_caps():
    assert factory().build(definition(caps={'max_provider_requests_per_invocation': 1})).definition['limits']['max_provider_requests_per_invocation'] == 1
    for value in [3, True, -1, None]:
        with pytest.raises(WorkflowAdmissionError):
            factory().build(definition(caps={'max_provider_requests_per_invocation': value}))
    with pytest.raises(WorkflowAdmissionError):
        factory(caps=False).build(definition(caps=CAPS))


@pytest.mark.parametrize('caps', [False, True])
def test_yaml_requires_registered_guards_and_explicit_finite_caps(tmp_path, caps):
    path = yaml_project(tmp_path, caps=caps)
    if not caps:
        with pytest.raises(ValueError): load(path, guards=[guard()])
    else:
        flow = load(path, guards=[guard()])
        assert flow.current_fingerprint() == flow.fingerprint
    with pytest.raises(ValueError): load(path)


@pytest.mark.parametrize('change', ['version', 'schema', 'settings', 'root'])
def test_used_guard_and_logical_project_declarations_change_identity(change, tmp_path):
    first = factory().build(definition())
    if change == 'version': modified = factory(registered=[guard(version='v2')])
    elif change == 'schema': modified = factory(registered=[guard(settings_schema={
        'type': 'object', 'properties': {'enabled': {'type': 'boolean'}}, 'additionalProperties': False})])
    elif change == 'settings': modified = factory(body=('ALWAYS check. ' + TAG).replace('stage=final', 'stage=final, unused=true'))
    else: modified = factory(binding_options={'rule_project': tmp_path, 'rule_project_identity': 'project-v1'})
    if change == 'settings':
        with pytest.raises(WorkflowAdmissionError): modified.build(definition())
    else: assert modified.build(definition()).fingerprint != first.fingerprint


def test_required_floor_cannot_be_removed_or_weakened():
    cfg = config(allowed_tools=frozenset(), required_guards={'review_scope': 'fail'})
    with pytest.raises(WorkflowAdmissionError): factory(cfg=cfg).build(definition())
    with pytest.raises(WorkflowAdmissionError): factory(cfg=cfg, body='Return JSON.').build(definition())


def test_injected_runtime_with_different_guard_version_refuses_before_state(tmp_path):
    flow = factory().build(definition())
    runtime = ProsaicRuntime(flow.config, guards=[guard(version='other')])
    with pytest.raises(ValueError): Harness(flow, tmp_path / 'run', runtime=runtime)
    assert not (tmp_path / 'run/run.json').exists()


def test_guarded_bundle_freezes_registrations_and_refuses_new_guard_version():
    bundle = WorkflowBundle('guarded-v1', factory())
    prepared = bundle.prepare_json(json.dumps({'definition': definition()}))
    rebuilt = WorkflowBundle('guarded-v1', factory()).reconstruct(prepared.proposal_json, prepared.reference)
    assert rebuilt.fingerprint == prepared.workflow.fingerprint
    with pytest.raises(WorkflowAdmissionError):
        WorkflowBundle('guarded-v1', factory(registered=[guard(version='v2')])).reconstruct(
            prepared.proposal_json, prepared.reference)


def test_default_and_unused_guard_registrations_preserve_untagged_identity():
    ordinary = factory(body='Return JSON.', registered=[], allowed=(), caps=False).build(definition())
    unused = factory(body='Return JSON.', allowed=(), caps=False).build(definition())
    assert ordinary.fingerprint == unused.fingerprint


def test_released_untagged_workflow_and_bundle_goldens():
    from test_workflow_factory import factory as legacy_factory, graph
    f = legacy_factory()
    assert f.build(graph()).fingerprint == 'ac9913171a763a653b8de7e23403aa8e68314db7e07bad6a9e0d5578bd54e624'
    assert WorkflowBundle('legacy-v1', f).identity == '289d2c28dad4966d331f4fe1f08c24d2c3a79d5303eeb1b48cf55da7db8c6182'


@pytest.mark.parametrize('body', [
    'ALWAYS check. <!-- enforce: missing(stage=final, on_violation=fail) -->',
    'ALWAYS check. <!-- enforce: review_scope(stage=unknown, on_violation=retry) -->',
    'ALWAYS check {{args}}. ' + TAG,
])
def test_malformed_unbound_and_unsupported_guarded_prose_refuses(body):
    with pytest.raises(WorkflowAdmissionError): factory(body=body).build(definition())


@pytest.mark.parametrize('cap', [0, 1, 2])
def test_nonnegative_explicit_caps_are_admitted(cap):
    f = factory(policy_options={'max_provider_requests_per_invocation': cap})
    assert f.build(definition()).definition['limits']['max_provider_requests_per_invocation'] == cap



def test_released_yaml_and_prompt_goldens(tmp_path):
    import hashlib
    flow=load(yaml_project(tmp_path,tagged=False,caps=False))
    assert flow.fingerprint=='2372997aa333113e9df3a7ed07a44bbcfdb3fa8270250c9f52b427e939fac021'
    arguments='{"request":{"golden":"untagged"}}'
    assert hashlib.sha256(flow.artifacts['review'].render(arguments).encode()).hexdigest()=='8a320dcba720b96535cdda43349701a615a53bb6295cb5d28e1bd40da33f9b18'
    from test_workflow_factory import factory as legacy_factory, graph
    native=legacy_factory().build(graph())
    assert hashlib.sha256(native.artifacts['find'].render(arguments).encode()).hexdigest()=='9d6af4c547341aa1312346202e715e42c936352e786678e813a49ecc864670d3'


def test_prose_only_annotations_with_host_caps_keep_released_native_identity():
    from test_workflow_factory import factory as legacy_factory, graph, agent
    flow=legacy_factory(assets={'finder':agent(body='ALWAYS be warm. <!-- prose-only: tone is judged by people -->')},
        max_provider_requests_per_invocation=2,max_tool_calls_per_invocation=0).build(graph())
    # Independently captured from the installed released0.9.11 wheel.
    assert flow.fingerprint=='1b1aa6af34014723818e7f234b202da460413a9ebc90f986dd3f78aab00b4475'
    assert not set(CAPS) & flow.definition['limits'].keys()
