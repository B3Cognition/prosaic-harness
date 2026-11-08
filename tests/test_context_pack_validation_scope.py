"""Private validation declares all known origins, independently of model slots."""
import time
import pytest
from prosaic_harness import (ContextPackBindings,ContextAuthorizer,ContextUse,ContextPackError,EvidenceSource,
    ContextPacker,ExposureBindings)
from prosaic_harness.context_packs.sources import capture_sources
from prosaic_harness.context_packs.codec import digest
from test_context_pack_sources import source_case,evidence_case
from test_context_pack_projection import context_case


def test_validation_origins_include_declared_facts_omitted_from_model_pack():
    from prosaic_harness.context_packs.projection import validation_exposures
    spec,arguments,base=source_case();context=context_case(arguments)
    private='PRIVATE-CONSTRAINTS-517'
    import hashlib
    context.evidence['private.md']={'text':private,'sha256':hashlib.sha256(private.encode()).hexdigest()}
    bindings=ContextPackBindings(specs=base.specs,sources={**base.sources,'constraints':EvidenceSource('private.md')},
        scope=base.scope,authorizer=ContextAuthorizer('access','1',lambda use:True))
    private_refs=validation_exposures(bindings,context)
    assert 'constraints' in {e['sourceAlias'] for e in private_refs.entries}
    assert all(e['disclosure']=='validation' for e in private_refs.entries)
    candidates=ContextPacker().compose(spec,capture_sources(spec,arguments,evidence_case(),bindings))
    assert private_refs.contains(ExposureBindings.from_snapshot(candidates.snapshot))
    assert 'PRIVATE-CONSTRAINTS-517' not in str(private_refs.to_dict())


def test_private_use_binds_the_complete_profile_without_inserting_source_bodies():
    _,arguments,bindings=source_case()
    refs=ExposureBindings(bindings.scope,[])
    use=ContextUse('validation',scope=bindings.scope,operation_id='validate',deadline=time.monotonic()+60,
        exposures=refs,validation_input={'profile':'workflow-check-context-v1','digest':digest({'private':'SECRET'})})
    record=use.to_dict()
    assert record['version']==2 and record['validationInput']['profile']=='workflow-check-context-v1'
    assert 'SECRET' not in str(record) and ContextUse.from_dict(record).to_dict()==record
    for purpose in ('invocation','deferredRead','historyReuse'):
        with pytest.raises(ContextPackError): ContextUse(purpose,scope=bindings.scope,operation_id='bad',deadline=time.monotonic()+60,
            exposures=refs,validation_input=record['validationInput'])


def test_private_origin_metadata_is_not_limited_to_model_snapshot_source_count():
    from prosaic_harness import CheckContext,InputSource
    from prosaic_harness.context_packs.projection import validation_exposures
    _,_,base=source_case()
    bindings=ContextPackBindings(specs={},sources={**{f'alias{i}':InputSource('/task') for i in range(25)},
        'absent':InputSource('/not-present')},scope=base.scope,authorizer=ContextAuthorizer('access','1',lambda use:True))
    refs=validation_exposures(bindings,CheckContext('review',{'task':'PRIVATE-BODY-517'},{},{},{}))
    assert {e['sourceAlias'] for e in refs.entries}=={f'alias{i}' for i in range(25)}
    assert 'PRIVATE-BODY-517' not in str(refs.to_dict())
