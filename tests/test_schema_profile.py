"""A root-isolated profile validates schema structure and controlled evaluation."""
import pytest

PROFILE = {'version': 1, 'dialect': '2020-12', 'refs': 'acyclic-local-static',
           'maximum_depth': 64, 'maximum_nodes': 65536,
           'maximum_schema_bytes': 65536, 'maximum_instance_bytes': 100000}


def helpers():
    from prosaic_harness.schema_validation import admit_schema, evaluate_schema, SchemaEvaluationError
    from prosaic_harness.errors import WorkflowAdmissionError
    return admit_schema, evaluate_schema, SchemaEvaluationError, WorkflowAdmissionError


def test_static_defs_anchor_and_nested_resource_resolution():
    admit, evaluate, _, _ = helpers()
    schema = {'$id': 'https://local.test/root', '$defs': {
        'number': {'$anchor': 'number', 'type': 'integer'},
        'child': {'$id': 'child', '$defs': {'word': {'type': 'string'}},
                  '$ref': '#/$defs/word'}},
        'type': 'object', 'properties': {'n': {'$ref': '#number'}, 's': {'$ref': 'child'}}}
    assert admit(schema, profile=PROFILE) == schema
    assert evaluate(schema, {'n': 1, 's': 'word'}, profile=PROFILE) == []
    assert evaluate(schema, {'n': 'secret', 's': 1}, profile=PROFILE)


def test_ref_like_literal_data_is_not_a_schema():
    admit, evaluate, _, _ = helpers()
    literal = {'$ref': 'https://external.test/', '$dynamicRef': '#bad', '$schema': 'unknown'}
    schema = {'const': literal, 'examples': [literal], 'enum': [literal]}
    assert admit(schema, profile=PROFILE) == schema
    assert evaluate(schema, literal, profile=PROFILE) == []


@pytest.mark.parametrize('schema', [
    {'$ref': '#/missing'}, {'$ref': '#'},
    {'$defs': {'a': {'$ref': '#/$defs/b'}, 'b': {'$ref': '#/$defs/a'}}},
    {'$ref': 'https://external.test/root'}, {'$dynamicRef': '#item'},
    {'$schema': 'http://json-schema.org/draft-07/schema#'},
    {'$defs': {'bad': {'$schema': 'urn:unknown'}}},
    {'$defs': {'a': {'$anchor': 'dup'}, 'b': {'$anchor': 'dup'}}},
    {'$id': 'https://local.test/root', '$defs': {'a': {'$id': 'dup'}, 'b': {'$id': './dup'}}},
    {'$defs': {'a': 42}, '$ref': '#/$defs/a'},
    {'const': {'type': 'integer'}, '$ref': '#/const'},
])
def test_rejects_invalid_unresolvable_ambiguous_or_cyclic_profile(schema):
    admit, _, _, error = helpers()
    with pytest.raises(error) as caught:
        admit(schema, profile=PROFILE)
    assert caught.value.code == 'invalid_schema'


def test_identical_anchor_names_in_distinct_resources_are_allowed():
    admit, evaluate, _, _ = helpers()
    schema = {'$defs': {'a': {'$id': 'a', '$anchor': 'item', 'type': 'string'},
                        'b': {'$id': 'b', '$anchor': 'item', 'type': 'integer'}}, '$ref': 'b#item'}
    admit(schema, profile=PROFILE)
    assert evaluate(schema, 1, profile=PROFILE) == []


def test_bounded_errors_never_include_values_or_schema_contents():
    _, evaluate, _, _ = helpers()
    schema = {'type': 'array', 'items': {'enum': ['classified schema secret']}}
    issues = evaluate(schema, ['classified instance secret'] * 30, profile=PROFILE, max_errors=2)
    assert len(issues) == 2
    assert all(len(issue) <= 256 and 'classified' not in issue for issue in issues)


def test_profile_instance_failure_is_distinct_from_invalid_instance():
    _, evaluate, _, data_error = helpers()
    assert evaluate({'type': 'integer'}, 'bad', profile=PROFILE)
    with pytest.raises(data_error) as caught:
        evaluate(True, 'x' * 100001, profile=PROFILE)
    assert caught.value.code == 'limit_exceeded'
    value = 0
    for _ in range(70):
        value = [value]
    with pytest.raises(data_error):
        evaluate(True, value, profile=PROFILE)
    assert evaluate(True, value) == []


def test_legacy_productive_recursion_and_controlled_resolver_failure():
    _, evaluate, failure, _ = helpers()
    schema = {'type': 'object', 'properties': {'child': {'$ref': '#'}}}
    value = {}
    for _ in range(70):
        value = {'child': value}
    assert evaluate(schema, value) == []
    with pytest.raises(failure):
        evaluate({'$ref': '#/missing'}, {})
    with pytest.raises(failure):
        evaluate({'$ref': '#'}, {})


def test_legacy_admission_keeps_ref_like_data_rejection_and_productive_refs():
    admit, _, _, error = helpers()
    schema = {'type': 'object', 'properties': {'child': {'$ref': '#'}}}
    assert admit(schema, profile=None) == schema
    with pytest.raises(error):
        admit({'const': {'$ref': 'https://external.test/'}}, profile=None)


def test_new_evaluation_rechecks_profile_and_uses_isolated_registry():
    _, evaluate, failure, _ = helpers()
    with pytest.raises(failure):
        evaluate({'$ref': 'https://external.test/schema'}, {}, profile=PROFILE)
    with pytest.raises(failure):
        evaluate(True, {}, profile={**PROFILE, 'dialect': 'unknown'})


def test_boolean_schemas_and_owned_schema_snapshot():
    admit, evaluate, _, _ = helpers()
    assert admit(False, profile=PROFILE) is False
    assert evaluate(True, {}, profile=PROFILE) == []
    assert evaluate(False, {}, profile=PROFILE)
    schema = {'type': 'object', 'properties': {'n': {'type': 'integer'}}}
    owned = admit(schema, profile=PROFILE)
    schema['properties']['n']['type'] = 'string'
    assert evaluate(owned, {'n': 1}, profile=PROFILE) == []


def test_unused_nested_resources_and_dynamic_anchors_cannot_collide():
    admit, _, _, error = helpers()
    for schema in (
        {'$id': 'https://local.test/root', '$defs': {'unused': {'$id': 'https://local.test/root'}}},
        {'$anchor': 'dup', '$defs': {'unused': {'$dynamicAnchor': 'dup'}}},
    ):
        with pytest.raises(error):
            admit(schema, profile=PROFILE)


def test_missing_anchor_and_pointer_into_non_schema_are_rejected():
    admit, _, _, error = helpers()
    for schema in ({'$ref': '#absent'}, {'type': 'integer', '$ref': '#/type'}):
        with pytest.raises(error):
            admit(schema, profile=PROFILE)


def test_legacy_nested_dialect_still_selects_its_existing_validator():
    admit, evaluate, _, error = helpers()
    schema = {'type': 'object', 'properties': {'child': {
        '$schema': 'http://json-schema.org/draft-07/schema#', 'type': 'object',
        'unevaluatedProperties': False}}}
    admit(schema, profile=None)
    assert evaluate(schema, {'child': {'extra': 1}}) == []
    with pytest.raises(error):
        admit(schema, profile=PROFILE)


def test_evaluation_stops_after_the_required_number_of_errors():
    _, evaluate, _, _ = helpers()
    # The evaluator must not enumerate the remaining array items after one error.
    class NeverEnumerateAll(list):
        def __getitem__(self, key):
            return self if isinstance(key, slice) else super().__getitem__(key)

        def __iter__(self):
            yield 'bad'
            raise AssertionError('unneeded evaluation')
    assert len(evaluate({'type': 'array', 'items': {'type': 'integer'}},
                        NeverEnumerateAll(['bad']), max_errors=1)) == 1


def test_human_context_bytes_and_nonfinite_instance_failure():
    _, evaluate, _, data_error = helpers()
    with pytest.raises(data_error):
        evaluate(True, 'x' * 65536, profile={**PROFILE, 'maximum_instance_bytes': 65536})
    with pytest.raises(data_error):
        evaluate(True, {'n': float('inf')}, profile=PROFILE)


def test_root_does_not_import_another_root_resources_or_metaschemas(monkeypatch):
    import urllib.request
    admit, evaluate, failure, error = helpers()
    def forbidden(*args, **kwargs):
        raise AssertionError('network retrieval')
    monkeypatch.setattr(urllib.request, 'urlopen', forbidden)
    admit({'$id': 'https://local.test/a', '$anchor': 'entry', 'type': 'integer'}, profile=PROFILE)
    for ref in ('https://local.test/a#entry', 'https://json-schema.org/draft/2020-12/schema'):
        with pytest.raises(error):
            admit({'$ref': ref}, profile=PROFILE)
        with pytest.raises(failure):
            evaluate({'$ref': ref}, {}, profile=PROFILE)


def test_boolean_literal_target_is_not_confused_with_boolean_schema_position():
    admit, _, _, error = helpers()
    schema = {'const': True, 'properties': {'unused': True}, '$ref': '#/const'}
    with pytest.raises(error):
        admit(schema, profile=PROFILE)


def test_boolean_defs_refs_and_pointer_escapes_are_admitted():
    admit, evaluate, _, _ = helpers()
    schema = {'$defs': {'a/b~c': True}, '$ref': '#/$defs/a~1b~0c'}
    admit(schema, profile=PROFILE)
    assert evaluate(schema, {}, profile=PROFILE) == []
    other = {'$defs': {'no': False}, '$ref': '#/$defs/no'}
    admit(other, profile=PROFILE)
    assert evaluate(other, {}, profile=PROFILE)


def test_relative_root_resource_id_is_applied_once():
    admit, evaluate, _, _ = helpers()
    schema = {'$id': 'folder/root', '$defs': {
        'number': {'$id': 'number', 'type': 'integer'}}, '$ref': 'number'}
    admit(schema, profile=PROFILE)
    assert evaluate(schema, 1, profile=PROFILE) == []
    anchored = {'$id': 'folder/root', '$defs': {'word': {'$anchor': 'word', 'type': 'string'}},
                '$ref': '#word'}
    admit(anchored, profile=PROFILE)
    assert evaluate(anchored, 'text', profile=PROFILE) == []
