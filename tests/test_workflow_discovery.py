"""Public discovery must enforce projection, privacy and authoring parity."""
import json

import pytest
from jsonschema import Draft202012Validator

from prosaic_harness import (WorkflowCatalog, WorkflowBindings, WorkflowFactory,
                             WorkflowPolicy, WorkflowAdmissionError, Validator)
from test_workflow_factory import agent, config, factory, graph, tools


def test_describe_intersects_policy_with_bound_assets_and_keeps_prose_private():
    build = factory()
    manifest = build.describe()
    assert set(manifest['agents']) == {'finder'}
    assert manifest['defaultModelTierAllowed'] is True
    assert 'Return structured JSON.' not in json.dumps(manifest)
    assert 'http://localhost:9' not in json.dumps(manifest)
    assert 'Find a synthetic entity' not in json.dumps(manifest)
    manifest['agents'].clear()
    assert set(build.describe()['agents']) == {'finder'}


def metadata_factory(metadata=None, *, policy=None, schema=True):
    return WorkflowFactory(
        catalog=WorkflowCatalog(agents={'finder': agent()}, schemas={'result': schema},
                                public_metadata=metadata),
        bindings=WorkflowBindings(config=config(), custom_tools=tools(),
                                  validators={'verify': Validator('v1', lambda *_: [])}),
        policy=policy or WorkflowPolicy(allowed_agents={'finder', 'reviewer'},
            allowed_schemas={'result', 'absent'}, allowed_tools={'lookup_entity', 'absent'},
            allowed_validators={'verify', 'absent'}, allowed_model_tiers={'fast', 'absent'}))


def test_explicit_public_metadata_is_owned_and_does_not_change_identity():
    metadata = {'agents': {'finder': {'description': 'Public finder'}},
                'tools': {'lookup_entity': {'description': 'Public lookup'}}}
    build = metadata_factory(metadata)
    metadata['agents']['finder']['description'] = 'Changed'
    assert build.describe()['agents']['finder']['description'] == 'Public finder'
    assert build.build(graph()).fingerprint == metadata_factory().build(graph()).fingerprint
    manifest = build.describe(include_schemas=True)
    assert manifest['schemas']['result']['schema'] is True
    assert 'schema' not in build.describe()['schemas']['result']
    assert set(manifest['tools']) == {'lookup_entity'}
    assert set(manifest['validators']) == {'verify'}
    assert manifest['modelTiers'] == ['fast']


@pytest.mark.parametrize('metadata', [
    {'agents': {'unknown': {'description': 'No'}}},
    {'schemas': {'result': {'private': 'No'}}}, {'unknown': {}},
    {'agents': {'finder': {'description': 1}}},
    {'agents': {'finder': {'description': 'é' * 2049}}},
    {'tools': {'unknown': {'description': 'No'}}},
    {'agents': {'finder': {}}},
])
def test_public_metadata_rejects_unknown_or_unbounded_material(metadata):
    with pytest.raises(WorkflowAdmissionError):
        metadata_factory(metadata)


def test_discovery_rejects_cycles_and_oversized_documents_without_truncation():
    cyclic = {}
    cyclic['agents'] = cyclic
    with pytest.raises(WorkflowAdmissionError):
        metadata_factory(cyclic)
    for method in (factory().describe, factory().proposal_schema):
        with pytest.raises(WorkflowAdmissionError) as caught:
            method(maximum_bytes=32)
        assert caught.value.code == 'limit_exceeded'


def test_discovery_never_executes_callbacks_or_probes(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('discovery invoked an execution capability')
    from prosaic_runtime import CustomTool
    tool = CustomTool('lookup_entity', 'Private description',
        {'type': 'object', 'additionalProperties': False}, forbidden, 'v1', authorize=forbidden)
    build = WorkflowFactory(catalog=WorkflowCatalog(agents={'finder': agent()}, schemas={'result': True}),
        bindings=WorkflowBindings(config=config(), custom_tools={'lookup_entity': tool},
            validators={'verify': Validator('v1', forbidden)}),
        policy=WorkflowPolicy(allowed_agents={'finder'}, allowed_schemas={'result'},
            allowed_tools={'lookup_entity'}, allowed_validators={'verify'}))
    monkeypatch.setattr(CustomTool, 'descriptor', property(forbidden))
    monkeypatch.setattr(CustomTool, 'version', property(forbidden), raising=False)
    monkeypatch.setattr(Validator, 'version', property(forbidden), raising=False)
    monkeypatch.setattr('subprocess.run', forbidden)
    assert build.describe()['tools']['lookup_entity']['authorizationRequired'] is True
    Draft202012Validator.check_schema(build.proposal_schema())


def test_proposal_schema_accepts_all_step_kinds_and_empty_gate_properties():
    build = metadata_factory()
    definition = graph()
    definition['steps']['find']['next'] = 'gate'
    definition['steps']['gate'] = {'kind': 'gate', 'from': 'find', 'field': [''],
        'equals': True, 'pass': 'check', 'fail': 'rejected'}
    definition['steps']['check'] = {'kind': 'check', 'from': 'find', 'validators': ['verify'],
        'pass': 'review', 'fail': 'rejected'}
    schema = build.proposal_schema()
    Draft202012Validator.check_schema(schema)
    for envelope in ({'definition': definition}, {'definition': definition, 'inline_agents': {}}):
        Draft202012Validator(schema).validate(envelope)
        build.build_json(json.dumps(envelope))


@pytest.mark.parametrize('change', [
    lambda e: e.update(config={}),
    lambda e: e['definition'].update(runtime='private.yml'),
    lambda e: e['definition']['steps']['find'].update(read_roots=['private']),
    lambda e: e['definition']['steps']['find'].update(extra=True),
    lambda e: e['definition']['steps']['find'].update(schema='absent'),
    lambda e: e['definition']['limits'].update(max_calls=13),
    lambda e: e.update(inline_agents={'new': {'type': 'command', 'frontmatter': {}, 'body': 'x'}}),
])
def test_proposal_schema_rejects_forbidden_structure(change):
    envelope = {'definition': graph()}
    envelope['definition']['limits'] = {}
    change(envelope)
    assert not Draft202012Validator(factory().proposal_schema()).is_valid(envelope)


def test_proposal_schema_retains_mandatory_graph_admission():
    build = factory()
    definition = graph()
    definition['steps']['find']['next'] = 'missing'
    Draft202012Validator(build.proposal_schema()).validate({'definition': definition})
    with pytest.raises(WorkflowAdmissionError):
        build.build(definition)


def test_authorized_inline_and_composed_proposals_match_admission():
    build = factory(allow_inline_agents=True, allow_agent_composition=True)
    definition = graph()
    definition['steps']['find']['next'] = 'second'
    definition['steps']['second'] = {'kind': 'agent', 'agent': 'reply', 'schema': 'result',
                                     'inputs': ['find'], 'next': 'review'}
    for tier in (None, 'fast'):
        fm = {} if tier is None else {'model_tier': tier}
        inline = {'reply': {'type': 'command', 'frontmatter': fm, 'body': 'Return JSON.',
            'resources': [{'relPath': 'notes.md', 'content': 'Public instruction'}]}}
        envelope = {'definition': definition, 'inline_agents': inline}
        Draft202012Validator(build.proposal_schema()).validate(envelope)
        build.build_json(json.dumps(envelope))
    fm['model_tier'] = 'absent'
    assert not Draft202012Validator(build.proposal_schema()).is_valid(envelope)


def test_schema_accepts_empty_pause_validators_without_a_response_schema():
    definition = graph()
    definition['steps']['review']['validators'] = []
    build = factory()
    build.build(definition)
    Draft202012Validator(build.proposal_schema()).validate({'definition': definition})


@pytest.mark.parametrize('inline', [
    {'type': 'subagent', 'frontmatter': {}, 'body': 'x'},
    {'type': 'command', 'frontmatter': {'type': 'subagent'}, 'body': 'x'},
])
def test_inline_structural_schema_enforces_canonical_type_and_required_metadata(inline):
    build = factory(allow_inline_agents=True)
    envelope = {'definition': graph(), 'inline_agents': {'reply': inline}}
    envelope['definition']['steps']['find']['agent'] = 'reply'
    assert not Draft202012Validator(build.proposal_schema()).is_valid(envelope)
    with pytest.raises(WorkflowAdmissionError):
        build.build_json(json.dumps(envelope))


def test_proposal_schema_bounds_do_not_inherit_the_default_description_ceiling():
    # A caller can explicitly authorize a larger semantic document; do not first
    # construct it through describe()'s smaller default byte ceiling.
    aliases = {f'a{index}': agent(tier=None) for index in range(100)}
    metadata = {'agents': {alias: {'description': 'x' * 4096} for alias in aliases}}
    build = WorkflowFactory(catalog=WorkflowCatalog(agents=aliases, schemas={'result': True},
        public_metadata=metadata),
        bindings=WorkflowBindings(config=config()),
        policy=WorkflowPolicy(allowed_agents=set(aliases), allowed_schemas={'result'}))
    schema = build.proposal_schema(maximum_bytes=1_000_000)
    assert 'a99' in schema['properties']['definition']['properties']['steps']['additionalProperties']['oneOf'][0]['properties']['agent']['enum']


def test_native_tool_projection_intersects_runtime_permission():
    from dataclasses import replace
    build = factory(cfg=replace(config(), allowed_tools=frozenset()))
    assert build.describe()['tools'] == {}
    envelope = {'definition': graph()}
    assert not Draft202012Validator(build.proposal_schema()).is_valid(envelope)


def test_alias_property_names_reject_a_final_newline():
    envelope = {'definition': graph()}
    envelope['definition']['steps']['bad\n'] = {'kind': 'finish'}
    assert not Draft202012Validator(factory().proposal_schema()).is_valid(envelope)


def test_public_metadata_aggregate_host_bound_is_enforced():
    aliases = {f'a{index}': agent(tier=None) for index in range(2048)}
    metadata = {'agents': {alias: {'description': 'x' * 4096} for alias in aliases}}
    with pytest.raises(WorkflowAdmissionError) as caught:
        WorkflowCatalog(agents=aliases, public_metadata=metadata)
    assert caught.value.code == 'limit_exceeded'


def test_requested_capabilities_use_only_effective_public_tool_aliases():
    manifest = factory().describe()
    assert manifest['agents']['finder']['requestedCapabilities'] == {'tools': ['lookup_entity']}
    from dataclasses import replace
    assert factory(cfg=replace(config(), allowed_tools=frozenset())).describe()['agents']['finder']['requestedCapabilities'] == {'tools': []}


def test_inline_permission_keeps_denied_catalogue_aliases_private_and_requires_admission():
    build = factory(assets={'finder': agent(), 'reviewer': agent()},
                    allowed_agents={'finder'}, allow_inline_agents=True)
    envelope = {'definition': graph()}
    envelope['definition']['steps']['find']['agent'] = 'reviewer'
    schema = build.proposal_schema()
    assert 'reviewer' not in json.dumps(schema)
    Draft202012Validator(schema).validate(envelope)
    with pytest.raises(WorkflowAdmissionError) as caught:
        build.build_json(json.dumps(envelope))
    assert caught.value.code == 'policy_denied'
    envelope['definition']['steps']['find']['agent'] = 'finder'
    envelope['inline_agents'] = {'finder': {'type': 'command', 'frontmatter': {}, 'body': 'x'}}
    with pytest.raises(WorkflowAdmissionError) as caught:
        build.build_json(json.dumps(envelope))
    assert caught.value.code == 'invalid_artifact'
