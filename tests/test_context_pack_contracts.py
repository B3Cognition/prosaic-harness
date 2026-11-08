import hashlib
import pytest
from prosaic_harness.context_packs import (
    ContextScope, ContextSource, ContextItem, ContextSnapshot, ContextSlot, ContextPackSpec,
    ContextPackPolicy, ContextPackError, InputSource, EvidenceSource, ArtifactSource)
from prosaic_harness.context_packs.codec import decode
from support.context_pack_cases import scope_case, snapshot_case, spec_case


def test_snapshot_owns_nested_values():
    data = {'records': [{'id': 'a'}]}
    item = ContextItem('root', 'lookup', 'v1', data, labels={'service': 'api'})
    snapshot = ContextSnapshot.from_items([item], sources=[ContextSource('lookup', 'service-lookup', 'v1', 'complete')], scope_binding=scope_case())
    identity = snapshot.identity
    data['records'].clear()
    copy = snapshot.to_dict()
    copy['items'][0]['content']['records'].clear()
    assert snapshot.items[0].content == {'records': [{'id': 'a'}]}
    assert snapshot.identity == identity
    with pytest.raises((AttributeError, TypeError)):
        snapshot._encoded = b'{}'


def test_empty_capture_requires_source_outcome():
    with pytest.raises(ContextPackError):
        ContextSnapshot.from_items([], sources=[], scope_binding=scope_case())
    for outcome in ('complete', 'partial', 'unavailable'):
        snapshot = ContextSnapshot.from_items([], sources=[ContextSource('lookup', 'query', 'v1', outcome)], scope_binding=scope_case())
        assert snapshot.sources[0].outcome == outcome and snapshot.items == ()
    with pytest.raises(ContextPackError):
        ContextSnapshot.from_items([ContextItem('root', 'lookup', 'v2', 'x')], sources=[ContextSource('lookup', 'query', 'v1', 'complete')], scope_binding=scope_case())


def test_all_policy_defaults():
    from dataclasses import asdict
    assert asdict(ContextPackPolicy()) == dict(max_source_aliases=16, max_slots=32,
        max_captured_items=128, max_item_bytes=262144, max_total_content_bytes=2097152,
        max_snapshot_bytes=3145728, max_inline_bytes=49152, max_index_bytes=8192,
        max_variants=8, max_variant_bytes=524288, max_labels_per_item=16,
        max_json_depth=32, max_json_nodes=16384, composition_timeout_ms=250)
    for value in (True, 0, -1, 1.5):
        with pytest.raises(ContextPackError): ContextPackPolicy(max_slots=value)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), '\ud800', {1: 'bad'}, object()])
def test_records_are_closed_finite_utf8(value):
    with pytest.raises(ContextPackError): ContextItem('root', 'task', 'v1', value)


def test_cycles_duplicates_and_unknown_fields_are_rejected():
    cycle = []; cycle.append(cycle)
    with pytest.raises(ContextPackError): ContextItem('root', 'task', 'v1', cycle)
    with pytest.raises(ContextPackError): decode(b'{"version":1,"version":2}')
    with pytest.raises(ContextPackError): ContextItem.from_dict({**snapshot_case().items[0].to_dict(), 'unexpected': True})
    with pytest.raises(ContextPackError): ContextScope('test', 'sandbox', 'app', 'tenant', 'a\n')
    with pytest.raises(ContextPackError): ContextItem('root', 'task', 'v1', 'x', label='ž'*65)
    with pytest.raises(ContextPackError): ContextSlot('task', required=True, min_items=True)
    with pytest.raises(ContextPackError): ContextSlot.from_dict({**ContextSlot('task').to_dict(), 'minItems': None})


def test_task_slot_is_nonempty_input():
    assert spec_case().task_source == 'task'
    for slot in (ContextSlot('task'), ContextSlot('task', required=True, min_items=0),
                 ContextSlot('task', required=True, max_items=2),
                 ContextSlot('task', required=True, representation={'kind':'jsonPointer', 'pointer':'/task'})):
        with pytest.raises(ContextPackError): ContextPackSpec('review', 'v1', [slot], task_source='task')
    assert InputSource('/task').pointer == '/task'
    assert ArtifactSource('lookup').step == 'lookup'
    assert EvidenceSource('requirements.md').path == 'requirements.md'


@pytest.mark.parametrize('pointer', ['/a~1b/~0c', '', '/0'])
def test_json_pointer_escapes(pointer):
    assert InputSource(pointer).pointer == pointer


@pytest.mark.parametrize('pointer', ['a', '/a~', '/a~2'])
def test_invalid_json_pointer(pointer):
    with pytest.raises(ContextPackError): InputSource(pointer)


def test_cardinality_and_representation_bounds():
    assert ContextSlot('task', required=True).min_items == 1
    assert ContextSlot('task').min_items == 0
    assert ContextSlot('task').max_items == 1
    assert ContextSlot('task', required=True, min_items=0).min_items == 0
    for options in ({'min_items': 1}, {'min_items': 2, 'max_items': 1, 'required': True},
                    {'required': True, 'availability': 'discoverable'},
                    {'representation': {'kind':'utf8Range', 'start':True, 'end':2}}):
        with pytest.raises(ContextPackError): ContextSlot('task', **options)


def test_record_roundtrip_preserves_identity():
    for record in (scope_case(), snapshot_case(), spec_case(), ContextSource('task','assignment','v1','complete'), ContextSlot('task'), ContextItem('root','task','v1','ž')):
        copy = type(record).from_dict(record.to_dict())
        assert copy.to_dict() == record.to_dict()
        assert copy.identity == record.identity
    item = ContextItem('root', 'task', 'v1', 'ž')
    assert item.content_sha256 == hashlib.sha256('ž'.encode()).hexdigest()


def test_decoding_requires_utf8_and_records_cannot_gain_mutable_fields():
    with pytest.raises(ContextPackError): decode('{"x":1}'.encode('utf-16'))
    with pytest.raises((AttributeError, TypeError)):
        snapshot_case().injected = {'mutable': True}


def test_exports_are_public_and_source_metadata_is_bounded():
    import prosaic_harness as api
    assert api.ContextItem is ContextItem
    with pytest.raises(ContextPackError):
        ContextSource('task', 'assignment', 'v1', 'complete', ranked_item_ids=['a']*129)
    source = ContextSource('task', 'assignment', 'v1', 'complete', ranked_item_ids=['absent'])
    with pytest.raises(ContextPackError): ContextSnapshot.from_items([], sources=[source], scope_binding=scope_case())
