"""Untrusted data must be bounded before expansion or serialization."""
import pytest


def helpers():
    from prosaic_harness.admission_data import snapshot_json, parse_bounded_json
    from prosaic_harness.errors import WorkflowAdmissionError
    return snapshot_json, parse_bounded_json, WorkflowAdmissionError


def test_owned_snapshot_accepts_benign_sharing_without_shared_mutation():
    snapshot, _, _ = helpers()
    child = {'items': [1, 'é', True, None]}
    source = [child, child]
    result = snapshot(source, maximum_bytes=200)
    child['items'].append(2)
    result[0]['items'].append(3)
    assert result[1] == {'items': [1, 'é', True, None]}


def test_alias_amplification_rejected_before_expansion():
    snapshot, _, error = helpers()
    value = []
    for _ in range(50):
        value = [value, value]
    with pytest.raises(error) as caught:
        snapshot(value, maximum_bytes=262144)
    assert caught.value.code == 'limit_exceeded'


@pytest.mark.parametrize('value', [float('inf'), float('nan'), {1: 'value'}, {'x': object()}, '\ud800'])
def test_invalid_json_values_are_safe(value):
    snapshot, _, error = helpers()
    with pytest.raises(error) as caught:
        snapshot(value, maximum_bytes=100)
    assert caught.value.code == 'invalid_definition'
    assert 'value' not in str(caught.value)


def test_cycles_are_rejected():
    snapshot, _, error = helpers()
    value = []
    value.append(value)
    with pytest.raises(error):
        snapshot(value, maximum_bytes=100)


def test_exact_encoded_unicode_bytes_and_node_budget():
    snapshot, _, error = helpers()
    assert snapshot('é', maximum_bytes=8) == 'é'
    with pytest.raises(error):
        snapshot('é', maximum_bytes=7)
    assert snapshot([0, 0], maximum_bytes=20, maximum_nodes=3) == [0, 0]
    with pytest.raises(error):
        snapshot([0, 0], maximum_bytes=20, maximum_nodes=2)


def test_ascii_del_is_escaped_in_exact_size():
    snapshot, _, error = helpers()
    with pytest.raises(error):
        snapshot('\x7f', maximum_bytes=7)
    assert snapshot('\x7f', maximum_bytes=8) == '\x7f'


def test_container_depth_boundary():
    snapshot, parse, error = helpers()
    value = []
    for _ in range(63):
        value = [value]
    assert snapshot(value, maximum_bytes=500) == value
    with pytest.raises(error):
        snapshot([value], maximum_bytes=500)
    with pytest.raises(error):
        parse('[' * 5000 + '0' + ']' * 5000, maximum_bytes=20000)


@pytest.mark.parametrize('text', ['{"x":1,"x":2}', '{"x":NaN}', '1e999', '"\\ud800"', b'"\xff"', '\ud800', '{bad'])
def test_raw_parser_errors_are_safe(text):
    _, parse, error = helpers()
    with pytest.raises(error) as caught:
        parse(text, maximum_bytes=100)
    assert caught.value.code == 'invalid_definition'
    assert 'bad' not in str(caught.value)


def test_raw_and_mapping_limits_and_valid_escaped_astral_unicode():
    snapshot, parse, error = helpers()
    assert parse('{"x": [1, true]}', maximum_bytes=100) == {'x': [1, True]}
    assert parse('"\\ud83d\\ude00"', maximum_bytes=14) == '😀'
    with pytest.raises(error):
        parse(b' ' * 101, maximum_bytes=100)
    for bad in (True, 0, -1):
        with pytest.raises(ValueError):
            snapshot({}, maximum_bytes=bad)


def test_error_location_does_not_reveal_untrusted_field_names():
    snapshot, _, error = helpers()
    with pytest.raises(error) as caught:
        snapshot({'secret credential': object()}, maximum_bytes=100)
    assert 'secret' not in str(caught.value)
    assert len(caught.value.location) <= 256


@pytest.mark.parametrize('value,encoded_bytes', [
    ({'x': [True, False, None]}, 26), ('😀', 14), ('\n', 4),
    ('"\\', 6), ({'é': 0}, 13), (-12, 3), (1.25, 4),
])
def test_exact_scalar_key_and_container_encoding_boundaries(value, encoded_bytes):
    snapshot, _, error = helpers()
    assert snapshot(value, maximum_bytes=encoded_bytes) == value
    with pytest.raises(error) as caught:
        snapshot(value, maximum_bytes=encoded_bytes - 1)
    assert caught.value.code == 'limit_exceeded'


def test_limits_apply_before_copying_massive_width_or_string():
    snapshot, _, error = helpers()
    for value in ([0] * 100000, 'x' * 100000):
        with pytest.raises(error) as caught:
            snapshot(value, maximum_bytes=20, maximum_nodes=4)
        assert caught.value.code == 'limit_exceeded'


def test_raw_delimiters_and_escaped_quotes_inside_strings_do_not_count_as_depth():
    _, parse, _ = helpers()
    assert parse('{"x":"[\\\"{]"}', maximum_bytes=100, maximum_depth=1) == {'x': '["{]'}
