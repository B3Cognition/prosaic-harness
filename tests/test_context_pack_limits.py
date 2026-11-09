import pytest
from prosaic_harness.context_packs import (ContextPacker, ContextPackPolicy, ContextPackError,
    ContextSource, ContextItem, ContextSnapshot, ContextSlot, ContextPackSpec)
from support.context_pack_cases import required_optional_case, scope_case
from prosaic_harness.context_packs.codec import encode


def test_mandatory_and_index_overflow_fail_without_truncation():
    spec,snapshot=required_optional_case()
    with pytest.raises(ContextPackError,match='contextPackLimit'):
        ContextPacker(policy=ContextPackPolicy(max_inline_bytes=20)).compose(spec,snapshot)
    discoverable=ContextPackSpec('p','1',[ContextSlot('facts',availability='discoverable')])
    with pytest.raises(ContextPackError,match='contextPackLimit'):
        ContextPacker(policy=ContextPackPolicy(max_index_bytes=10)).compose(discoverable,snapshot)


def test_oversized_optional_is_skipped_and_next_small_unit_survives():
    snapshot=ContextSnapshot.from_items([ContextItem('task','s','v1','task'),ContextItem('big','s','v1','x'*10000),ContextItem('small','s','v1','small')],sources=[ContextSource('s','source','v1','complete')],scope_binding=scope_case())
    spec=ContextPackSpec('p','1',[ContextSlot('s',item_ids=['task'],required=True),ContextSlot('s',item_ids=['big'],priority=10),ContextSlot('s',item_ids=['small'])])
    result=ContextPacker(policy=ContextPackPolicy(max_inline_bytes=3000)).compose(spec,snapshot)
    assert [i['content'] for i in result.variants[0]['items']]==['task','small']
    assert result.reports[0]['omissions'][0]['reason']=='byteLimit'


def test_variants_end_with_required_base_and_total_bytes_are_bounded():
    spec,snapshot=required_optional_case()
    result=ContextPacker().compose(spec,snapshot)
    assert len(result.variants)==2
    assert [i['content'] for i in result.variants[-1]['items']]==['task content']
    size=sum(len(encode(v)) for v in result.variants)
    with pytest.raises(ContextPackError,match='contextPackLimit'):
        ContextPacker(policy=ContextPackPolicy(max_variant_bytes=size-1)).compose(spec,snapshot)


def test_cooperative_deadline_is_cumulative():
    from prosaic_harness.context_packs import selection
    ticks=iter([0,1,2,3,4,5,6])
    spec,snapshot=required_optional_case()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(selection,'_clock',lambda:next(ticks))
        with pytest.raises(ContextPackError,match='contextPackLimit'):
            ContextPacker(policy=ContextPackPolicy(composition_timeout_ms=250)).compose(spec,snapshot)


def test_grouped_variants_are_bounded_and_never_evict_required_items():
    snapshot=ContextSnapshot.from_items([ContextItem(str(i),'s','v1',str(i)) for i in range(12)],sources=[ContextSource('s','source','v1','complete')],scope_binding=scope_case())
    spec=ContextPackSpec('p','1',[ContextSlot('s',item_ids=['0'],required=True),ContextSlot('s',item_ids=[str(i) for i in range(1,12)],max_items=11)])
    result=ContextPacker(policy=ContextPackPolicy(max_variants=3)).compose(spec,snapshot)
    assert [len(v['items']) for v in result.variants]==[12,6,1]
    assert all(v['items'][0]['content']=='0' for v in result.variants)


def test_text_content_byte_limit_counts_text_separately_from_json_framing():
    snapshot=ContextSnapshot.from_items([ContextItem('root','s','v1','x')],sources=[ContextSource('s','source','v1','complete')],scope_binding=scope_case())
    spec=ContextPackSpec('p','1',[ContextSlot('s',required=True)])
    result=ContextPacker(policy=ContextPackPolicy(max_item_bytes=1)).compose(spec,snapshot)
    assert result.variants[0]['items'][0]['content']=='x'
