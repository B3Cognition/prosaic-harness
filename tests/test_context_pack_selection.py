import pytest
from prosaic_harness.context_packs import (ContextPacker, ContextPackPolicy, ContextPackError,
    ContextSource, ContextItem, ContextSnapshot, ContextSlot, ContextPackSpec)
from prosaic_harness.context_packs.codec import digest
from support.context_pack_cases import two_source_case, required_optional_case, scope_case


def test_equal_revision_and_content_do_not_merge_independent_sources():
    spec, snapshot = two_source_case()
    candidates = ContextPacker().compose(spec, snapshot)
    assert len(candidates.variants[0]['items']) == 2
    assert len({i['citationId'] for i in candidates.variants[0]['items']}) == 2


def test_one_variant_keeps_required_and_omits_optional():
    spec, snapshot = required_optional_case()
    result = ContextPacker(policy=ContextPackPolicy(max_variants=1)).compose(spec, snapshot)
    assert len(result.variants) == 1
    assert result.reports[0]['requiredCoverageComplete'] is True
    assert result.reports[0]['omittedItemCount'] == 1


def collection(*, outcome='complete', ranked=(), contents=None):
    values=contents or {'a':'A','b':'B','c':'C'}
    return ContextSnapshot.from_items([ContextItem(k,'facts','v1',v,labels={'kind':'keep' if k!='c' else 'other','area':'api'}) for k,v in values.items()],sources=[ContextSource('facts','lookup','v1',outcome,ranked_item_ids=ranked)],scope_binding=scope_case())


def test_order_filters_and_cardinality_are_explicit():
    snapshot=collection(ranked=('b','c'))
    spec=ContextPackSpec('p','1',[ContextSlot('facts',max_items=3,labels={'kind':['keep'],'area':['api','web']})])
    result=ContextPacker().compose(spec,snapshot)
    assert [i['content'] for i in result.variants[0]['items']] == ['B','A']
    explicit=ContextPackSpec('p','1',[ContextSlot('facts',max_items=3,item_ids=('a','b'))])
    assert [i['content'] for i in ContextPacker().compose(explicit,snapshot).variants[0]['items']] == ['A','B']
    with pytest.raises(ContextPackError,match='selectionLimit'):
        ContextPacker().compose(ContextPackSpec('p','1',[ContextSlot('facts')]),snapshot)


def test_dedup_retains_slots_and_strictest_required_status():
    spec=ContextPackSpec('p','1',[ContextSlot('facts',item_ids=['a']),ContextSlot('facts',item_ids=['a'],required=True)])
    result=ContextPacker().compose(spec,collection())
    assert len(result.variants)==1
    assert result.variants[0]['items'][0]['slotIndexes']==[0,1]
    assert result.reports[0]['slots'][1]['selectedCount']==1


def test_partial_empty_and_unavailable_captures_do_not_claim_full_coverage():
    spec=ContextPackSpec('p','1',[ContextSlot('facts',required=True,max_items=3)])
    with pytest.raises(ContextPackError,match='requiredContextMissing'): ContextPacker().compose(spec,collection(outcome='partial'))
    partial=ContextPackSpec('p','1',[ContextSlot('facts',required=True,max_items=3,allow_partial=True)])
    result=ContextPacker().compose(partial,collection(outcome='partial'))
    assert result.variants[0]['coverage'][0]['outcome']=='partial'
    for outcome in ('complete','partial','unavailable'):
        snapshot=ContextSnapshot.from_items([],sources=[ContextSource('facts','lookup','v1',outcome)],scope_binding=scope_case())
        zero=ContextPackSpec('p','1',[ContextSlot('facts',required=True,min_items=0)])
        if outcome=='complete':
            assert ContextPacker().compose(zero,snapshot).reports[0]['requiredCoverageComplete'] is True
        else:
            with pytest.raises(ContextPackError,match='requiredContextMissing'): ContextPacker().compose(zero,snapshot)


@pytest.mark.parametrize('task', ['', '   ', {}, [], None])
def test_task_cannot_be_empty(task):
    snapshot=ContextSnapshot.from_items([ContextItem('root','task','v1',task)],sources=[ContextSource('task','assignment','v1','complete')],scope_binding=scope_case())
    spec=ContextPackSpec('p','1',[ContextSlot('task',required=True)],task_source='task')
    with pytest.raises(ContextPackError,match='requiredContextMissing'): ContextPacker().compose(spec,snapshot)


def test_utf8_and_pointer_projections_are_exact_and_preserve_unicode():
    snapshot=collection(contents={'a':'žX','b':{'a/b':{'~x':['e\u0301','é']}}})
    spec=ContextPackSpec('p','1',[ContextSlot('facts',item_ids=['a'],required=True,representation={'kind':'utf8Range','start':0,'end':2}),ContextSlot('facts',item_ids=['b'],required=True,representation={'kind':'jsonPointer','pointer':'/a~1b/~0x/0'})])
    result=ContextPacker().compose(spec,snapshot)
    assert [i['content'] for i in result.variants[0]['items']]==['ž','e\u0301']
    bad=ContextPackSpec('p','1',[ContextSlot('facts',item_ids=['a'],representation={'kind':'utf8Range','start':1,'end':2})])
    with pytest.raises(ContextPackError): ContextPacker().compose(bad,snapshot)


def test_select_checks_original_index_and_envelope_digest_and_owns_outputs():
    spec,snapshot=required_optional_case()
    packer=ContextPacker(); candidates=packer.compose(spec,snapshot)
    envelope=candidates.variants[0]
    selected=packer.select(candidates,0,digest(envelope))
    assert selected.reference['envelopeDigest']==digest(envelope)
    envelope['items'].clear()
    assert len(selected.envelope['items'])==2
    with pytest.raises(ContextPackError): packer.select(candidates,True,digest(candidates.variants[0]))
    with pytest.raises(ContextPackError): packer.select(candidates,0,'0'*64)
    assert type(candidates).from_dict(candidates.to_dict()).candidate_identity==candidates.candidate_identity
    assert type(selected).from_dict(selected.to_dict()).pack_identity==selected.pack_identity


def test_composition_has_no_io_or_callbacks_and_safe_report_has_only_counts(monkeypatch):
    spec,snapshot=required_optional_case()
    def forbidden(*a,**k): pytest.fail('composition performed I/O')
    import builtins, urllib.request, subprocess
    monkeypatch.setattr(builtins,'open',forbidden)
    monkeypatch.setattr(urllib.request,'urlopen',forbidden)
    monkeypatch.setattr(subprocess,'run',forbidden)
    result=ContextPacker().compose(spec,snapshot)
    assert result.safe_report(0)=={'selectedItemCount':2,'deferredItemCount':0,'omittedItemCount':0,'requiredCoverageComplete':True,'countingKind':'notCounted'}


def test_discovery_only_advertises_the_declared_representation():
    snapshot=collection(contents={'a':{'public':{'id':'x'},'private':'DO NOT ADVERTISE'}})
    spec=ContextPackSpec('p','1',[ContextSlot('facts',availability='discoverable',representation={'kind':'jsonPointer','pointer':'/public'})])
    result=ContextPacker().compose(spec,snapshot)
    assert result.variants[0]['items']==[]
    assert result.variants[0]['index'][0]['representation']=={'kind':'jsonPointer','pointer':'/public'}
    assert 'DO NOT ADVERTISE' not in str(result.variants)
    assert result.reports[0]['deferredItemCount']==1


def test_snapshot_ranking_changes_selection_without_mutating_spec():
    spec=ContextPackSpec('p','1',[ContextSlot('facts',max_items=3)])
    original=spec.identity
    first=ContextPacker().compose(spec,collection(ranked=['b']))
    second=ContextPacker().compose(spec,collection(ranked=['c']))
    assert spec.identity==original
    assert first.variants[0]['items'][0]['content']=='B'
    assert second.variants[0]['items'][0]['content']=='C'
    assert first.candidate_identity!=second.candidate_identity


def test_forged_selected_projection_is_rejected_even_with_recomputed_hashes():
    from prosaic_harness import PreparedContextPack
    spec,snapshot=required_optional_case()
    candidates=ContextPacker().compose(spec,snapshot)
    value=ContextPacker().select(candidates,0,digest(candidates.variants[0])).to_dict()
    value['envelope']['items'][0]['content']='forged'
    value['reference']['envelopeDigest']=digest(value['envelope'])
    value['reference']['packIdentity']=digest({k:v for k,v in value['reference'].items() if k!='packIdentity'})
    with pytest.raises(ContextPackError,match='contextBindingMismatch'): PreparedContextPack.from_dict(value)
