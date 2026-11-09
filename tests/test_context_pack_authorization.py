import time
import pytest
from prosaic_harness import (ContextPacker,ContextPackBindings,ContextAuthorizer,InputSource,ContextPackError,ContextScope)
from prosaic_harness.context_packs.authorization import ContextUse,ExposureBindings,authorize_context_use
from prosaic_harness.context_packs.codec import digest
from support.context_pack_cases import required_optional_case,scope_case


def case(authorize=lambda use:True):
    spec,snapshot=required_optional_case();packer=ContextPacker();candidates=packer.compose(spec,snapshot)
    pack=packer.select(candidates,0,digest(candidates.variants[0]))
    bindings=ContextPackBindings(specs={'review':spec},sources={'task':InputSource('/task'),'facts':InputSource('/facts')},scope=scope_case(),authorizer=ContextAuthorizer('access','1',authorize))
    return bindings,pack


@pytest.mark.parametrize('purpose',['invocation','deferredRead','historyReuse','validation','retainedRead'])
def test_all_purposes_carry_owned_exact_scope_revision_and_representation(purpose):
    observed=[]
    binding,pack=case(lambda use:observed.append(use.to_dict()) or True)
    use=ContextUse.for_pack(purpose,pack,operation_id='operation',deadline=time.monotonic()+60)
    authorize_context_use(binding,use)
    assert observed[0]['purpose']==purpose
    assert observed[0]['scopeBinding']==scope_case().to_dict()
    assert all(e['sourceRevision']=='v1' for e in observed[0]['exposures']['entries'])
    if purpose=='validation': assert all(e['disclosure']=='validation' for e in observed[0]['exposures']['entries'])
    else: assert any(e['representation']=={'kind':'whole'} and e['disclosure']=='inline' for e in observed[0]['exposures']['entries'])
    assert 'content' not in observed[0]['exposures']['entries'][0]
    assert ContextUse.from_dict(use.to_dict()).identity==use.identity


@pytest.mark.parametrize('verdict',[False,1,'true',{},[True]])
def test_non_boolean_returns_deny_without_diagnostic_leaks(verdict):
    binding,pack=case(lambda use:verdict)
    use=ContextUse.for_pack('invocation',pack,operation_id='operation',deadline=time.monotonic()+60)
    with pytest.raises(ContextPackError,match='contextUseDenied'): authorize_context_use(binding,use)


def test_exception_and_foreign_scope_never_disclose_or_call_a_fallback():
    calls=[]
    def fail(use): calls.append(use); raise ValueError('SECRET-884')
    binding,pack=case(fail)
    use=ContextUse.for_pack('invocation',pack,operation_id='operation',deadline=time.monotonic()+60)
    with pytest.raises(ContextPackError) as error: authorize_context_use(binding,use)
    assert str(error.value)=='contextUseDenied' and len(calls)==1
    foreign=ContextScope('test','sandbox','app','other-tenant','actor')
    packet=use.to_dict();packet['scopeBinding']=foreign.to_dict();packet['exposures']['scopeBinding']=foreign.to_dict()
    with pytest.raises(ContextPackError,match='contextScopeMismatch'): authorize_context_use(binding,ContextUse.from_dict(packet))
    assert len(calls)==1


def test_retained_read_is_independent_of_inference_and_construction_is_pure():
    calls=[]
    binding,pack=case(lambda use:calls.append(use.purpose) or use.purpose=='retainedRead')
    uses=[ContextUse.for_pack(purpose,pack,operation_id='operation',deadline=time.monotonic()+60) for purpose in ('retainedRead','invocation','historyReuse')]
    assert calls==[]
    authorize_context_use(binding,uses[0])
    for use in uses[1:]:
        with pytest.raises(ContextPackError,match='contextUseDenied'): authorize_context_use(binding,use)
    assert calls==['retainedRead','invocation','historyReuse']


def test_exposure_union_retains_history_and_does_not_include_private_validation_contents():
    _,pack=case()
    model=ExposureBindings.from_pack(pack)
    validation=ExposureBindings.from_snapshot(pack.snapshot)
    combined=model.union(model)
    assert combined.to_dict()==model.to_dict()
    assert all(e['disclosure']=='validation' for e in validation.entries)
    assert all(e['disclosure']!='validation' for e in model.entries)
    assert 'task content' not in str(combined.to_dict())


def test_requested_membership_rejects_revision_identity_and_pointer_widening():
    _,pack=case();allowed=ExposureBindings.from_pack(pack)
    for field in ('sourceRevision','sourceIdentity'):
        record=allowed.to_dict();record['entries'][0][field]='foreign'
        assert not allowed.contains(ExposureBindings.from_dict(record))
    assert allowed.contains(allowed)


def test_json_pointer_membership_never_widens_and_allows_actual_child_strings():
    from prosaic_harness import ContextSource,ContextItem,ContextSnapshot,ContextPackSpec,ContextSlot
    import hashlib
    snapshot=ContextSnapshot.from_items([ContextItem('root','facts','v1',{'public':{'title':'visible'},'private':'secret'})],sources=[ContextSource('facts','records','v1','complete')],scope_binding=scope_case())
    spec=ContextPackSpec('discover','1',[ContextSlot('facts',availability='discoverable',representation={'kind':'jsonPointer','pointer':'/public'})])
    packer=ContextPacker();candidates=packer.compose(spec,snapshot);pack=packer.select(candidates,0,digest(candidates.variants[0]))
    allowed=ExposureBindings.from_pack(pack)
    entry=next(e for e in allowed.entries if e['itemId'] is not None)
    for target in ('','/private','/publicity'):
        requested=ExposureBindings(scope_case(),[{**entry,'disclosure':'read','representation':{'kind':'jsonPointer','pointer':target}}])
        assert not allowed.contains(requested)
    requested=ExposureBindings(scope_case(),[{**entry,'disclosure':'read','representation':{'kind':'jsonPointer','pointer':'/public/title'},'contentSha256':hashlib.sha256(b'visible').hexdigest(),'contentBytes':7,'contentKind':'text'}])
    assert allowed.contains(requested)
    assert ContextUse.for_pack('deferredRead',pack,operation_id='read',deadline=time.monotonic()+60,requested=requested).exposures.to_dict()==requested.to_dict()


def test_validation_bindings_cannot_be_mislabeled_as_model_exposure_or_history():
    _,pack=case()
    model=ExposureBindings.from_pack(pack);private=ExposureBindings.from_snapshot(pack.snapshot)
    with pytest.raises(ContextPackError): model.union(private)
    with pytest.raises(ContextPackError): ContextUse('historyReuse',scope=scope_case(),operation_id='history',deadline=time.monotonic()+60,exposures=private)


def test_expired_authorization_never_calls_host_or_changes_exposure():
    calls=[];binding,pack=case(lambda use:calls.append(use) or True)
    use=ContextUse.for_pack('invocation',pack,operation_id='expired',deadline=time.monotonic()-1)
    before=use.exposures.to_dict()
    with pytest.raises(ContextPackError,match='contextUseDenied'): authorize_context_use(binding,use)
    assert calls==[] and use.exposures.to_dict()==before


def test_revocation_rechecks_retained_history_without_erasing_evidence():
    allowed={'current':True}
    binding,pack=case(lambda use:allowed['current'])
    use=ContextUse.for_pack('historyReuse',pack,operation_id='turn-2',deadline=time.monotonic()+60)
    authorize_context_use(binding,use)
    original=pack.to_dict();allowed['current']=False
    with pytest.raises(ContextPackError,match='contextUseDenied'): authorize_context_use(binding,use)
    assert pack.to_dict()==original
