"""Public in-memory admission, independent of YAML and physical workspaces."""
from dataclasses import replace
import json

import pytest
import prosaic_harness
from prosaic_runtime import CustomTool, EndpointConfig, ProsaicArtifact, RuntimeConfig


def api():
    names = ('WorkflowCatalog', 'WorkflowBindings', 'WorkflowPolicy', 'WorkflowFactory', 'WorkflowAdmissionError')
    missing = [name for name in names if not hasattr(prosaic_harness, name)]
    assert missing == [], f'missing supported factory API: {missing}'
    return tuple(getattr(prosaic_harness, name) for name in names)


def agent(*, tools=('lookup_entity',), tier='fast', body='Return structured JSON.'):
    fm = {'name': 'finder', 'description': 'Find a synthetic entity', 'tools': list(tools)}
    if tier is not None:
        fm['model_tier'] = tier
    return ProsaicArtifact.from_inspection({'id': 'subagents/finder.md', 'type': 'subagent',
                                         'frontmatter': fm, 'body': body})


def tools():
    schema = {'type': 'object', 'properties': {'query': {'type': 'string'}},
              'required': ['query'], 'additionalProperties': False}
    return {'lookup_entity': CustomTool('lookup_entity', 'Lookup a synthetic entity', schema,
                                      lambda value: {'found': True}, 'v1')}


def config(**changes):
    value = RuntimeConfig({'local': EndpointConfig('http://localhost:9/v1', 'synthetic',
                          features={'streaming': False})}, {'fast': 'local'}, 'local',
                          allowed_tools=frozenset({'lookup_entity'}))
    return replace(value, **changes)


def graph():
    return {'version': 1, 'name': 'synthetic', 'start': 'find', 'steps': {
        'find': {'kind': 'agent', 'agent': 'finder', 'schema': 'result',
                 'tools': ['lookup_entity'], 'require_tools': ['lookup_entity'], 'next': 'review'},
        'review': {'kind': 'pause', 'question': 'Accept the result?',
                   'choices': {'accept': 'done', 'reject': 'rejected'}, 'requires': ['find']},
        'done': {'kind': 'finish', 'requires': ['find']},
        'rejected': {'kind': 'finish', 'outcome': 'rejected'}}}


def factory(*, assets=None, schemas=None, cfg=None, registry=None, **policy_changes):
    Catalog, Bindings, Policy, Factory, _ = api()
    values = dict(allowed_agents=frozenset({'finder', 'reviewer'}),
                  allowed_schemas=frozenset({'result'}), allowed_tools=frozenset({'lookup_entity'}),
                  allowed_validators=frozenset(), allowed_model_tiers=frozenset({'fast'}))
    values.update(policy_changes)
    result = {'type': 'object', 'properties': {'found': {'type': 'boolean'}},
              'required': ['found'], 'additionalProperties': False}
    return Factory(catalog=Catalog(agents=assets or {'finder': agent()}, schemas=schemas or {'result': result}),
                   bindings=Bindings(config=cfg or config(), custom_tools=registry if registry is not None else tools()),
                   policy=Policy(**values))


def test_public_factory_constructs_without_a_physical_path():
    workflow = factory().build(graph())
    assert workflow.path is None
    assert workflow.definition['limits']['max_calls'] == 12
    assert workflow.definition['limits']['max_tokens'] == 32768
    assert workflow.artifacts['find'].id == 'subagents/finder.md'
    assert workflow.tool_descriptors['lookup_entity']['version'] == 'v1'
    assert workflow.current_fingerprint() == workflow.fingerprint


def test_build_json_has_the_same_identity_and_rejects_duplicate_keys():
    build = factory()
    assert build.build_json(json.dumps({'definition': graph()})).fingerprint == build.build(graph()).fingerprint
    Error = api()[-1]
    with pytest.raises(Error):
        build.build_json('{"definition":{},"definition":{}}')


@pytest.mark.parametrize('field,value', [('source', '/private/source'), ('runtime', 'runtime.yml'),
                                        ('evidence', ['secret']), ('resources', ['secret'])])
def test_client_cannot_supply_host_resource_bindings(field, value):
    proposal = graph()
    proposal[field] = value
    with pytest.raises(api()[-1]):
        factory().build(proposal)


@pytest.mark.parametrize('grant', ['write_file', 'read_file', 'unknown_tool'])
def test_dynamic_graph_cannot_grant_filesystem_or_unregistered_tools(grant):
    proposal = graph()
    proposal['steps']['find'].update(tools=[grant], require_tools=[])
    with pytest.raises(api()[-1]):
        factory().build(proposal)


def test_registration_is_not_a_policy_grant():
    with pytest.raises(api()[-1]):
        factory(allowed_tools=frozenset()).build(graph())


def test_omitted_tier_authorizes_default_even_with_empty_explicit_allowlist():
    admitted = factory(assets={'finder': agent(tier=None)}, allowed_model_tiers=frozenset()).build(graph())
    assert admitted.config.default_profile == 'local'
    with pytest.raises(api()[-1]):
        factory(allowed_model_tiers=frozenset()).build(graph())


def test_native_binding_ignores_unrelated_cli_directories_without_mutating_host():
    original = config(tool_directories=('/definitely/missing/cli-tools',))
    workflow = factory(cfg=original).build(graph())
    assert workflow.config.tool_directories == ()
    assert original.tool_directories == ('/definitely/missing/cli-tools',)


def test_input_mutation_cannot_change_catalog_config_or_graph_snapshots():
    original_agent, original_config, proposal = agent(), config(), graph()
    build = factory(assets={'finder': original_agent}, cfg=original_config)
    original_agent.frontmatter['name'] = 'changed'
    original_config.profiles['local'].features['streaming'] = True
    workflow = build.build(proposal)
    proposal['steps']['find']['tools'].clear()
    assert workflow.artifacts['find'].frontmatter['name'] == 'finder'
    assert workflow.config.profiles['local'].features['streaming'] is False
    assert workflow.definition['steps']['find']['tools'] == ['lookup_entity']


def test_unused_host_assets_do_not_change_identity():
    first = factory().build(graph())
    second = factory(assets={'finder': agent(), 'unused': agent(body='Unused content')}).build(graph())
    assert second.fingerprint == first.fingerprint


def test_inline_and_composition_permissions_are_independent():
    build = factory(allow_inline_agents=True)
    proposal = graph()
    proposal['steps']['find']['agent'] = 'fresh'
    inline = {'fresh': {'type': 'subagent', 'frontmatter': {'name': 'fresh', 'description': 'Fresh',
                       'tools': ['lookup_entity']}, 'body': 'Return structured JSON.'}}
    assert build.build(proposal, inline_agents=inline).path is None
    with pytest.raises(api()[-1]):
        factory().build(proposal, inline_agents=inline)
    proposal['steps']['find']['next'] = 'another'
    proposal['steps']['another'] = {**proposal['steps']['find'], 'next': 'review'}
    with pytest.raises(api()[-1]):
        build.build(proposal, inline_agents=inline)
    assert factory(allow_inline_agents=True, allow_agent_composition=True).build(proposal, inline_agents=inline)


def test_unused_or_colliding_inline_agents_fail():
    inline = {'finder': {'type': 'subagent', 'frontmatter': {'name': 'finder', 'description': 'New'}, 'body': 'New'}}
    with pytest.raises(api()[-1]):
        factory(allow_inline_agents=True).build(graph(), inline_agents=inline)
    inline['unused'] = inline.pop('finder')
    with pytest.raises(api()[-1]):
        factory(allow_inline_agents=True).build(graph(), inline_agents=inline)


def test_client_inline_schemas_are_outside_the_mvp_envelope():
    with pytest.raises(api()[-1]):
        factory().build_json(json.dumps({'definition': graph(), 'inline_schemas': {'x': True}}))


def test_graph_and_requested_limits_are_validated():
    proposal = graph()
    proposal['steps']['find']['next'] = 'missing'
    with pytest.raises(api()[-1]):
        factory().build(proposal)
    proposal = graph()
    proposal['limits'] = {'max_calls': 13}
    with pytest.raises(api()[-1]):
        factory().build(proposal)
    proposal['limits'] = {'max_calls': 1}
    assert factory().build(proposal).definition['limits']['max_calls'] == 1


def test_resolved_schema_must_be_unambiguous_and_local():
    for schema in ({'$ref': '#/missing'}, {'$ref': '#'}, {'$ref': 'https://example.invalid/schema'},
                   {'$defs': {'a': {'$anchor': 'same', 'type': 'string'},
                              'b': {'$anchor': 'same', 'type': 'integer'}}, '$ref': '#same'}):
        with pytest.raises(api()[-1]):
            factory(schemas={'result': schema}).build(graph())


@pytest.mark.parametrize('change', ['path', 'record', 'fingerprint', 'definition', 'descriptor'])
def test_native_origin_and_original_seal_cannot_be_repaired_by_hashing(change):
    from pathlib import Path
    from prosaic_harness.factory import admit_workflow

    workflow = factory().build(graph())
    if change == 'path':
        workflow.path = Path('/tmp/invented.yml')
    elif change == 'record':
        del workflow._admission
    elif change == 'fingerprint':
        workflow.fingerprint = 'invented'
    elif change == 'definition':
        workflow.definition['steps']['review']['question'] = 'Changed question'
        workflow.fingerprint = workflow.current_fingerprint()
    else:
        workflow._tool_descriptors.clear()
        workflow.fingerprint = workflow.current_fingerprint()
    with pytest.raises(api()[-1]):
        admit_workflow(workflow)


def test_admission_record_and_request_snapshots_are_independent():
    from dataclasses import FrozenInstanceError
    from prosaic_harness.factory import admit_workflow

    build = factory()
    first, second = build.build(graph()), build.build(graph())
    record = admit_workflow(first)
    assert record.original_seal == first.fingerprint
    with pytest.raises((FrozenInstanceError, AttributeError)):
        record.original_seal = 'changed'
    with pytest.raises(TypeError):
        record.tools['extra'] = tools()['lookup_entity']
    first.config.profiles['local'].features['streaming'] = True
    with pytest.raises(api()[-1]):
        admit_workflow(first)
    assert admit_workflow(second).original_seal == second.fingerprint
    assert build.build(graph()).fingerprint == second.fingerprint


def test_runtime_override_is_standard_matching_and_native_only():
    from prosaic_runtime import ProsaicRuntime
    from prosaic_harness.factory import admit_workflow, _config_from_json

    workflow = factory().build(graph())
    record = admit_workflow(workflow)
    runtime = ProsaicRuntime(_config_from_json(record.config_json), custom_tools=record.tools)
    assert admit_workflow(workflow, runtime=runtime) is record
    runtime.config.profiles['local'].features['streaming'] = True
    with pytest.raises(api()[-1]):
        admit_workflow(workflow, runtime=runtime)
    with pytest.raises(api()[-1]):
        admit_workflow(workflow, runtime=object())
    runtime = ProsaicRuntime(_config_from_json(record.config_json), custom_tools=record.tools)
    runtime._cli_tools['retained'] = object()
    with pytest.raises(api()[-1]):
        admit_workflow(workflow, runtime=runtime)


def test_unused_native_registry_entries_do_not_change_identity_or_override_admission():
    from prosaic_runtime import ProsaicRuntime
    from prosaic_harness.factory import admit_workflow, _config_from_json

    registry = tools()
    registry['unused'] = CustomTool('unused', 'Unused tool',
        {'type': 'object', 'additionalProperties': False}, lambda _: {}, 'v2')
    first = factory().build(graph())
    workflow = factory(registry=registry).build(graph())
    assert workflow.fingerprint == first.fingerprint
    record = admit_workflow(workflow)
    runtime = ProsaicRuntime(_config_from_json(record.config_json), custom_tools=registry)
    assert admit_workflow(workflow, runtime=runtime) is record


def test_validator_binding_versions_are_required_without_executing_callbacks():
    from prosaic_harness import Validator
    from prosaic_harness.factory import admit_workflow

    def forbidden(_):
        raise AssertionError('construction must not execute a validator')

    Catalog, Bindings, Policy, Factory, Error = api()
    proposal = graph()
    proposal['steps']['find']['validators'] = ['guard']
    workflow = Factory(catalog=Catalog(agents={'finder': agent()}, schemas={'result': True}),
        bindings=Bindings(config=config(), custom_tools=tools(), validators={'guard': Validator('v1', forbidden)}),
        policy=Policy(allowed_agents=frozenset({'finder'}), allowed_schemas=frozenset({'result'}),
            allowed_tools=frozenset({'lookup_entity'}), allowed_validators=frozenset({'guard'}),
            allowed_model_tiers=frozenset({'fast'}))).build(proposal)
    assert dict(admit_workflow(workflow).validator_versions) == {'guard': 'v1'}
    with pytest.raises(Error):
        admit_workflow(workflow, validators={})
    with pytest.raises(Error):
        admit_workflow(workflow, validators={'guard': Validator('v2', forbidden)})


@pytest.mark.parametrize('field', ['inputs', 'optional_inputs'])
def test_shared_graph_admission_validates_agent_input_references(field):
    proposal = graph()
    proposal['steps']['find'][field] = ['review']
    with pytest.raises(api()[-1]):
        factory().build(proposal)


def test_native_construction_never_resolves_paths_or_discovers_cli(monkeypatch):
    from pathlib import Path
    import prosaic_runtime.runtime as runtime_module

    def forbidden(*args, **kwargs):
        raise AssertionError('native construction has no filesystem preparation')

    monkeypatch.setattr(Path, 'resolve', forbidden)
    monkeypatch.setattr(runtime_module, 'load_cli_tools', forbidden)
    assert factory(cfg=config(tool_directories=('/missing',))).build(graph()).snapshot() == {}


@pytest.mark.parametrize('field,value', [('max_calls', True), ('max_json_depth', 0),
    ('max_receipt_bytes', 8388609), ('max_output_bytes', 100001)])
def test_policy_bounds_reject_invalid_or_storage_incompatible_values(field, value):
    with pytest.raises((ValueError, api()[-1])):
        api()[2](**{field: value})


def test_policy_is_complete_and_schema_evaluation_profile_uses_instance_bounds():
    policy = api()[2](max_human_response_bytes=10, max_output_bytes=20)
    assert policy.schema_profile()['maximum_instance_bytes'] == 20
    assert policy.schema_profile(human=True)['maximum_instance_bytes'] == 10
    first = factory().build(graph())
    second = factory(max_human_response_bytes=10).build(graph())
    assert first.fingerprint != second.fingerprint


def test_raw_pathless_workflow_does_not_gain_legacy_privileges():
    from prosaic_harness import Workflow
    from prosaic_harness.factory import admit_workflow

    native = factory().build(graph())
    raw = Workflow(None, native.definition, native.config, native.artifacts,
                   native.schemas, native.fingerprint, custom_tools=native.custom_tools,
                   _tool_descriptors=native.tool_descriptors)
    with pytest.raises(api()[-1]):
        admit_workflow(raw)


@pytest.mark.parametrize('argument', ['agents', 'schemas'])
def test_catalog_rejects_empty_nonmapping_inputs(argument):
    with pytest.raises(api()[-1]):
        api()[0](**{argument: []})


def test_empty_inline_agent_list_is_not_a_mapping_envelope():
    with pytest.raises(api()[-1]):
        factory().build(graph(), inline_agents=[])


def test_explicit_json_inline_agents_null_is_not_an_omitted_mapping():
    with pytest.raises(api()[-1]):
        factory().build_json(json.dumps({'definition': graph(), 'inline_agents': None}))


def test_bindings_validate_endpoint_feature_shape_before_any_graph():
    invalid = config()
    object.__setattr__(invalid.profiles['local'], 'features', [])
    with pytest.raises(api()[-1]):
        api()[1](config=invalid)


def test_catalog_dag_amplification_is_bounded_before_encoding():
    shared = []
    for _ in range(50):
        shared = [shared, shared]
    with pytest.raises(api()[-1]) as error:
        api()[0](schemas={'result': {'examples': shared}})
    assert error.value.code == 'limit_exceeded'


def test_host_aliases_are_logical_and_bounded():
    for alias in ('/private/finder', 'subagents/finder.md', 'a' * 65):
        with pytest.raises(api()[-1]):
            api()[0](agents={alias: agent()})


def test_effective_grants_require_host_runtime_and_prose():
    with pytest.raises(api()[-1]):
        factory(cfg=config(allowed_tools=frozenset())).build(graph())
    with pytest.raises(api()[-1]):
        factory(assets={'finder': agent(tools=())}).build(graph())


def test_known_ungranted_builtin_prose_requests_stay_inert():
    proposal = graph()
    proposal['steps']['find'].update(tools=[], require_tools=[])
    workflow = factory(assets={'finder': agent(tools=('read_file',))}).build(proposal)
    assert workflow.tool_descriptors == {}


def test_inline_agent_cannot_choose_its_artifact_identity_or_execution_kind():
    proposal = graph()
    proposal['steps']['find']['agent'] = 'fresh'
    for data in (
        {'id': 'approved', 'type': 'subagent', 'frontmatter': {'name': 'n', 'description': 'd'}, 'body': ''},
        {'type': 'rule', 'frontmatter': {}, 'body': ''},
        {'type': 'subagent', 'frontmatter': {'type': 'rule', 'name': 'n', 'description': 'd'}, 'body': ''},
    ):
        with pytest.raises(api()[-1]):
            factory(allow_inline_agents=True).build(proposal, inline_agents={'fresh': data})


def test_aggregate_artifact_budget_precedes_another_catalog_decode(monkeypatch):
    import prosaic_harness.factory as factory_module

    build = factory(assets={'finder': agent(body='x' * 1000)},
                    allow_agent_composition=True, max_artifact_bytes=1500)
    proposal = graph()
    proposal['steps']['find']['next'] = 'another'
    proposal['steps']['another'] = {**proposal['steps']['find'], 'next': 'review'}
    original = factory_module.json.loads
    decoded = 0

    def guarded_decode(text, *args, **kwargs):
        nonlocal decoded
        if text == build._agents['finder']:
            decoded += 1
            if decoded > 1:
                raise AssertionError('budget exhausted before copying another artifact')
        return original(text, *args, **kwargs)

    monkeypatch.setattr(factory_module.json, 'loads', guarded_decode)
    with pytest.raises(api()[-1]) as error:
        build.build(proposal)
    assert error.value.code == 'limit_exceeded'


def test_mutable_descriptors_are_bounded_before_legacy_deepcopy(monkeypatch):
    import prosaic_harness.workflow as workflow_module

    workflow = factory().build(graph())
    shared = []
    for _ in range(50):
        shared = [shared, shared]
    workflow._tool_descriptors['hidden'] = shared

    def forbidden(_):
        raise AssertionError('unadmitted descriptors must not reach deepcopy')

    monkeypatch.setattr(workflow_module, 'deepcopy', forbidden)
    with pytest.raises(api()[-1]) as error:
        workflow.tool_descriptors
    assert error.value.code == 'limit_exceeded'


@pytest.mark.parametrize('tier', ['tenant/fast', '租户/fast'])
def test_explicit_tier_allowlist_uses_host_runtime_route_names(tier):
    workflow = factory(cfg=config(routes={tier: 'local'}),
        assets={'finder': agent(tier=tier)}, allowed_model_tiers=frozenset({tier})).build(graph())
    assert workflow.artifacts['find'].frontmatter['model_tier'] == tier
    assert workflow.current_fingerprint() == workflow.fingerprint


@pytest.mark.parametrize('tier', ['', 'x' * 65, 'fast\nroute', 'fast\x00route', 'fast\u202eroute'])
def test_model_tier_names_reject_empty_oversize_and_unicode_controls(tier):
    with pytest.raises(api()[-1]):
        api()[2](allowed_model_tiers=frozenset({tier}))


def test_total_schema_body_budget_excludes_internal_step_mapping_overhead():
    from prosaic_harness.factory import admit_workflow

    workflow = factory(schemas={'result': True}, max_schema_bytes=4,
                       max_total_schema_bytes=4).build(graph())
    assert workflow.schemas['find'] is True
    assert admit_workflow(workflow).original_seal == workflow.current_fingerprint()
    with pytest.raises(api()[-1]) as error:
        factory(schemas={'result': False}, max_schema_bytes=4,
                max_total_schema_bytes=4).build(graph())
    assert error.value.code == 'limit_exceeded'


def test_unknown_schema_step_cannot_expand_identity_wrapper_budget():
    from prosaic_harness.factory import admit_workflow

    workflow = factory(schemas={'result': True}).build(graph())
    workflow.schemas['unknown'] = True
    with pytest.raises(api()[-1]):
        admit_workflow(workflow)


def test_schema_node_budget_is_per_resolved_root_not_the_internal_map():
    from prosaic_harness.factory import admit_workflow

    proposal = graph()
    previous = 'find'
    for index in range(8):
        name = f'agent{index}'
        proposal['steps'][previous]['next'] = name
        proposal['steps'][name] = {**proposal['steps']['find'], 'next': 'review'}
        previous = name
    schema = {'enum': [0] * 8000}
    workflow = factory(schemas={'result': schema}, allow_agent_composition=True).build(proposal)
    assert len(workflow.schemas) == 9
    assert admit_workflow(workflow).original_seal == workflow.current_fingerprint()


def test_typed_resource_cardinality_is_rejected_before_snapshot_or_copy(monkeypatch):
    import prosaic_harness.factory as factory_module

    artifact = replace(agent(), resources=({'relPath': 'embedded.md', 'content': 'body'},) * 3)
    def forbidden(*args, **kwargs):
        raise AssertionError('oversize resource tuple must be checked first')
    monkeypatch.setattr(factory_module, 'snapshot_json', forbidden)
    with pytest.raises(api()[-1]) as error:
        factory_module._artifact_snapshot(artifact, maximum_nodes=2)
    assert error.value.code == 'limit_exceeded'


def test_native_bindings_bound_validator_versions_without_running_checks():
    from prosaic_harness import Validator

    def forbidden(*args):
        raise AssertionError('validator setup must not execute callbacks')
    with pytest.raises(api()[-1]) as error:
        api()[1](config=config(), validators={'guard': Validator('v' * 8388609, forbidden)})
    assert error.value.code == 'limit_exceeded'
