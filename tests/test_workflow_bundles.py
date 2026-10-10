"""Retained host material reconstructs only freshly admitted native workflows."""
import json
import hashlib
from dataclasses import FrozenInstanceError, replace

import pytest

from prosaic_harness import WorkflowAdmissionError, Validator
from prosaic_runtime import CustomTool

from test_workflow_factory import factory, graph


def envelope():
    return json.dumps({'definition': graph()})


def test_bundle_reference_reconstructs_public_native_workflow():
    from prosaic_harness import WorkflowBundle, WorkflowReference
    first = WorkflowBundle('service-v1', factory()).prepare_json(envelope())
    reference = WorkflowReference.from_dict(first.reference.to_dict())
    second = WorkflowBundle('service-v1', factory()).reconstruct(first.proposal_json, reference)
    assert second.path is None
    assert second.fingerprint == first.workflow.fingerprint
    assert second.current_fingerprint() == reference.workflow_fingerprint
    assert 'limits' not in json.loads(first.proposal_json)['definition']
    assert 'inline_agents' not in json.loads(first.proposal_json)


@pytest.mark.parametrize('mode,roots', [
    ('off', ()),
    ('required', ()),
    ('off', ('/synthetic/trusted-root',)),
    ('required', ('/synthetic/trusted-root',)),
])
def test_bundle_preserves_supported_sandbox_configuration_identity(mode, roots, monkeypatch):
    from pathlib import Path
    from prosaic_harness import WorkflowBundle
    from prosaic_runtime import CliSandboxConfig
    from test_workflow_factory import config

    def forbidden(*args, **kwargs):
        raise AssertionError('bundle preparation probed a trusted runtime root')

    cfg = config(cli_sandbox=CliSandboxConfig(mode, roots))
    original = factory(cfg=cfg)
    ordinary = original.build(graph())
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'resolve', forbidden)
        patch.setattr(Path, 'exists', forbidden)
        bundle = WorkflowBundle('v1', original)
        saved = bundle.prepare_json(envelope())
        recreated = WorkflowBundle('v1', factory(cfg=cfg)).reconstruct(saved.proposal_json, saved.reference)
    assert saved.workflow.fingerprint == recreated.fingerprint == ordinary.fingerprint
    assert recreated.config.cli_sandbox.mode == mode
    assert recreated.config.cli_sandbox.runtime_roots == roots
    default = WorkflowBundle('v1', factory())
    if mode == 'off' and not roots:
        assert bundle.identity == default.identity
    else:
        assert bundle.identity != default.identity


def test_sandbox_mode_and_each_trusted_root_change_bundle_identity():
    from prosaic_harness import WorkflowBundle
    from prosaic_runtime import CliSandboxConfig
    from test_workflow_factory import config
    identities = {
        WorkflowBundle('v1', factory(cfg=config(cli_sandbox=CliSandboxConfig(mode, roots)))).identity
        for mode, roots in [
            ('off', ()), ('required', ()), ('off', ('/synthetic/first',)),
            ('off', ('/synthetic/second',)), ('required', ('/synthetic/first',)),
            ('required', ('/synthetic/first', '/synthetic/second')),
        ]
    }
    assert len(identities) == 6


def test_canonical_original_envelope_sorts_recursive_keys_and_preserves_absence():
    from prosaic_harness import WorkflowBundle
    value = {'inline_agents': {}, 'definition': {'version': 1, 'start': 'ask', 'steps': {
        'done': {'kind': 'finish'}, 'ask': {'question': 'Potvrdit žluťoučký výsledek?',
                                          'kind': 'pause', 'choices': {'yes': 'done'}}}}}
    expected = ('{"definition":{"start":"ask","steps":{"ask":{"choices":{"yes":"done"},'
                '"kind":"pause","question":"Potvrdit žluťoučký výsledek?"},'
                '"done":{"kind":"finish"}},"version":1},"inline_agents":{}}')
    bundle = WorkflowBundle('service-v1', factory())
    saved = bundle.prepare_json(json.dumps(value, ensure_ascii=False))
    assert saved.proposal_json == expected
    assert saved.reference.proposal_sha256 == hashlib.sha256(expected.encode('utf-8')).hexdigest()
    reordered = json.dumps(json.loads(expected, object_pairs_hook=lambda pairs: dict(reversed(pairs))),
                           ensure_ascii=False)
    assert bundle.reconstruct(reordered, saved.reference).fingerprint == saved.workflow.fingerprint
    assert json.loads(saved.proposal_json) == value


@pytest.mark.parametrize('length', [60, 2500])
def test_non_ascii_near_small_transport_cap_reconstructs(length):
    from prosaic_harness import WorkflowBundle
    value = {'definition': {'version': 1, 'start': 'ask', 'steps': {
        'ask': {'kind': 'pause', 'question': 'ž' * length, 'choices': {'yes': 'done'}},
        'done': {'kind': 'finish'}}}}
    original = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    bundle = WorkflowBundle('v1', factory(max_proposal_bytes=len(original.encode('utf-8'))))
    saved = bundle.prepare_json(original)
    assert saved.proposal_json == original
    assert bundle.reconstruct(original, saved.reference).fingerprint == saved.workflow.fingerprint


@pytest.mark.parametrize('change', ['agent', 'schema', 'policy', 'config', 'tool', 'validator'])
def test_unused_private_material_changes_bundle_identity(change):
    from prosaic_harness import WorkflowBundle, WorkflowBindings
    from test_workflow_factory import config, tools
    original = factory()
    original._validators = {'unused': Validator('v1', lambda _: True)}
    original._agents = {**original._agents, 'unused': original._agents['finder']}
    original._schemas = {**original._schemas, 'unused': original._schemas['result']}
    tool = tools()['lookup_entity']
    original._tools = {**original._tools, 'unused': CustomTool(
        'unused', tool.description, tool.parameters, tool.handler, 'v1')}
    saved = WorkflowBundle('service-v1', original).prepare_json(envelope())
    altered = factory()
    altered._agents = dict(original._agents)
    altered._schemas = dict(original._schemas)
    altered._validators = dict(original._validators)
    altered._tools = dict(original._tools)
    if change == 'agent':
        altered._agents['unused'] = json.dumps({'id': 'unused.md', 'type': 'command', 'frontmatter': {}, 'body': 'Changed private content'})
    elif change == 'schema':
        altered._schemas['unused'] = '{"type":"boolean"}'
    elif change == 'policy':
        altered._policy = replace(altered._policy, max_calls=11)
    elif change == 'config':
        altered._config_json = WorkflowBindings(config=replace(config(), default_profile='local', routes={}))._config_json
    elif change == 'tool':
        altered._tools['unused'] = CustomTool('unused', tool.description, tool.parameters, tool.handler, 'v2')
    else:
        altered._validators['unused'] = Validator('v2', lambda _: True)
    changed = WorkflowBundle('service-v1', altered)
    assert changed.identity != saved.reference.bundle_identity
    with pytest.raises(WorkflowAdmissionError) as caught:
        changed.reconstruct(saved.proposal_json, saved.reference)
    assert caught.value.code == 'identity_mismatch'


def test_bundle_freezes_factory_and_excludes_public_display_metadata():
    from prosaic_harness import WorkflowBundle
    mutable = factory()
    bundle = WorkflowBundle('service-v1', mutable)
    saved = bundle.prepare_json(envelope())
    mutable._agents = {}
    mutable._schemas = {}
    mutable._tools = {}
    mutable._policy = replace(mutable._policy, max_calls=1)
    assert bundle.reconstruct(saved.proposal_json, saved.reference).fingerprint == saved.workflow.fingerprint
    equivalent = factory()
    equivalent._public_metadata_json = '{"description":"New display wording"}'
    equivalent._discovery_json = '{"display":"different"}'
    assert WorkflowBundle('service-v1', equivalent).identity == bundle.identity
    for target, field in ((bundle, 'version'), (bundle, 'identity'), (saved, 'proposal_json'), (saved.reference, 'proposal_sha256')):
        with pytest.raises((FrozenInstanceError, AttributeError)):
            setattr(target, field, 'changed')


@pytest.mark.parametrize('field,value,code', [
    ('version', True, 'invalid_definition'), ('version', 2, 'identity_mismatch'),
    ('admissionVersion', 2, 'identity_mismatch'), ('schemaProfile', 2, 'identity_mismatch'),
    ('canonicalization', 'unknown-v1', 'identity_mismatch'),
    ('bundleVersion', '', 'invalid_definition'), ('bundleVersion', 'x' * 129, 'invalid_definition'),
    ('bundleVersion', 'secret\n', 'invalid_definition'),
    ('bundleVersion', 'v2', 'identity_mismatch'),
    ('bundleIdentity', 'a' * 64, 'identity_mismatch'),
    ('proposalSha256', 'b' * 64, 'identity_mismatch'),
    ('workflowFingerprint', 'c' * 64, 'identity_mismatch'),
    ('bundleIdentity', 'A' * 64, 'invalid_definition'),
    ('workflowFingerprint', 'a' * 65, 'invalid_definition'),
    ('schemaProfile', 1.0, 'invalid_definition'),
])
def test_reference_tampering_has_safe_closed_failures(field, value, code):
    from prosaic_harness import WorkflowBundle, WorkflowReference
    bundle = WorkflowBundle('v1', factory())
    saved = bundle.prepare_json(envelope())
    record = saved.reference.to_dict()
    record[field] = value
    with pytest.raises(WorkflowAdmissionError) as caught:
        bundle.reconstruct(saved.proposal_json, WorkflowReference.from_dict(record))
    assert caught.value.code == code


def test_reference_rejects_unknown_missing_and_non_plain_values_without_callbacks():
    from prosaic_harness import WorkflowBundle, WorkflowReference
    def forbidden(*args):
        raise AssertionError('host callbacks were invoked during preparation')
    from test_workflow_factory import tools
    tool = tools()['lookup_entity']
    original = factory(allowed_validators={'review'}, registry={'lookup_entity': CustomTool(
        tool.name, tool.description, tool.parameters, forbidden, 'v1', authorize=forbidden)})
    original._validators = {'review': Validator('v1', forbidden)}
    value = graph()
    value['steps']['find']['validators'] = ['review']
    bundle = WorkflowBundle('v1', original)
    saved = bundle.prepare_json(json.dumps({'definition': value}))
    assert bundle.reconstruct(saved.proposal_json, saved.reference).fingerprint == saved.workflow.fingerprint
    for record in ([], None, {'callback': forbidden}, {**saved.reference.to_dict(), 'endpoint': 'secret'},
                   {k: v for k, v in saved.reference.to_dict().items() if k != 'version'}):
        with pytest.raises(WorkflowAdmissionError) as caught:
            WorkflowReference.from_dict(record)
        assert caught.value.code == 'invalid_definition'


@pytest.mark.parametrize('text', ['{}', '{"definition":{},"callback":"secret"}', '{"definition":NaN}', '{"definition":{},"definition":{}}'])
def test_bundle_rejects_malformed_envelopes(text):
    from prosaic_harness import WorkflowBundle
    with pytest.raises(WorkflowAdmissionError) as caught:
        WorkflowBundle('v1', factory()).prepare_json(text)
    assert caught.value.code == 'invalid_definition'


def test_reconstruction_checks_proposal_digest_before_resolving_bindings():
    from prosaic_harness import WorkflowBundle
    bundle = WorkflowBundle('v1', factory())
    saved = bundle.prepare_json(envelope())
    changed = json.loads(saved.proposal_json)
    changed['definition']['steps']['find']['agent'] = 'missing'
    with pytest.raises(WorkflowAdmissionError) as caught:
        bundle.reconstruct(json.dumps(changed), saved.reference)
    assert caught.value.code == 'identity_mismatch'


@pytest.mark.parametrize('version', ['', 'x' * 129, 'ž' * 65, 'a\x00b', '\ud800', 1, None])
def test_bundle_rejects_invalid_version_labels(version):
    from prosaic_harness import WorkflowBundle
    with pytest.raises(WorkflowAdmissionError) as caught:
        WorkflowBundle(version, factory())
    assert caught.value.code == 'invalid_definition'


def test_bundle_rejects_missing_declared_execution_binding():
    from prosaic_harness import WorkflowBundle
    value = graph()
    value['steps']['find']['validators'] = ['missing']
    bundle = WorkflowBundle('v1', factory(allowed_validators={'missing'}))
    with pytest.raises(WorkflowAdmissionError) as caught:
        bundle.prepare_json(json.dumps({'definition': value}))
    assert caught.value.code == 'binding_mismatch'


def test_bundle_rejects_over_transport_and_canonical_byte_caps():
    from prosaic_harness import WorkflowBundle
    text = envelope()
    bundle = WorkflowBundle('v1', factory(max_proposal_bytes=len(text.encode()) - 1))
    with pytest.raises(WorkflowAdmissionError) as caught:
        bundle.prepare_json(text)
    assert caught.value.code == 'limit_exceeded'
    # Canonicalization normalizes a short exponent spelling to a longer finite
    # number. That retained representation must also fit the host transport cap.
    value = {'definition': graph()}
    value['definition']['steps']['find']['next'] = 'test'
    value['definition']['steps']['test'] = {'kind': 'gate', 'from': 'find', 'field': ['found'],
                                           'equals': 1e20, 'pass': 'review', 'fail': 'review'}
    compact = json.dumps(value, separators=(',', ':')).replace('1e+20', '1e20')
    with pytest.raises(WorkflowAdmissionError) as caught:
        WorkflowBundle('v1', factory(max_proposal_bytes=len(compact))).prepare_json(compact)
    assert caught.value.code == 'limit_exceeded'
