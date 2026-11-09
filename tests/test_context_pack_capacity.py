import pytest
from prosaic_harness import (ContextItem,ContextSource,ContextSnapshot,ContextSlot,ContextPackSpec,
    ContextPacker,ContextPackError)
from prosaic_harness.context_packs.capacity import reserve_pack_capacity
from prosaic_harness.context_packs.codec import encode
from support.context_pack_cases import scope_case


def test_actual_duplicate_encoded_values_count_and_one_byte_short_refuses():
    shared={'text':'ž "\\"\n'*10}
    data={'first':shared,'second':shared}
    admitted=reserve_pack_capacity(data,data,max_state_bytes=100000,max_receipt_bytes=100000,
        output_bytes=10,metadata_bytes=10,event_bytes=10,metadata_nodes=10,event_nodes=10)
    assert admitted.receipt_bytes>len(encode(data))
    with pytest.raises(ContextPackError,match='contextSnapshotLimit'):
        reserve_pack_capacity(data,data,max_state_bytes=100000,max_receipt_bytes=admitted.receipt_bytes-1,
            output_bytes=10,metadata_bytes=10,event_bytes=10,metadata_nodes=10,event_nodes=10)
    single=reserve_pack_capacity({'first':shared},{'first':shared},max_state_bytes=100000,max_receipt_bytes=100000,
        output_bytes=10,metadata_bytes=10,event_bytes=10,metadata_nodes=10,event_nodes=10)
    assert admitted.receipt_bytes-single.receipt_bytes==len(encode(data))-len(encode({'first':shared}))


def test_one_node_short_refuses_before_effects():
    base=reserve_pack_capacity({}, {},max_state_bytes=100000,max_receipt_bytes=100000,
        output_bytes=1,metadata_bytes=1,event_bytes=1,metadata_nodes=1,event_nodes=1)
    with pytest.raises(ContextPackError,match='contextSnapshotLimit'):
        reserve_pack_capacity({}, {},max_state_bytes=100000,max_receipt_bytes=100000,max_json_nodes=base.receipt_nodes-1,
            output_bytes=1,metadata_bytes=1,event_bytes=1,metadata_nodes=1,event_nodes=1)


def test_default_workflow_storage_capacity_witness_counts_real_sdk_records():
    import prosaic_runtime as api
    snapshot=ContextSnapshot.from_items([ContextItem(str(i),'facts','v1','fact '+('x'*2048)) for i in range(16)],
        sources=[ContextSource('facts','captured-records','v1','complete')],scope_binding=scope_case())
    spec=ContextPackSpec('capacity','1',[ContextSlot('facts',required=True,item_ids=[str(i) for i in range(8)],min_items=8,max_items=8),
        ContextSlot('facts',item_ids=[str(i) for i in range(8,16)],max_items=8)])
    candidates=ContextPacker().compose(spec,snapshot)
    model={'contextPack':candidates.variants[-1]}
    private={'facts':'p'*65536}
    runtime=api.ProsaicRuntime(api.RuntimeConfig({'local':api.EndpointConfig('http://127.0.0.1:9/v1','synthetic',features={'streaming':False})},{},'local',frozenset()))
    prepared=runtime.prepare_turn(api.ProsaicArtifact('approved','subagent',{},'ALWAYS use facts. NEVER invent evidence.'),message='Review',
        input_data=model,input_profile='capacity-input-v1',authoritative_input_data=private,authoritative_input_profile='capacity-facts-v1',
        policy=api.RunPolicy(max_provider_requests=1,max_tool_calls=0))
    assert len(encode(snapshot.to_dict()))>=32768 and len(encode(private))>=65536 and len(encode(model))>=16384
    # Private originals, guard facts and controller validation are separate
    # owned copies; every occurrence is charged, even when values are equal.
    base={'candidates':candidates.to_dict(),'frozenInput':prepared.export_frozen_input().to_dict(),
        'originalArguments':private,'controllerValidationContext':private}
    reservation=reserve_pack_capacity(base,base,max_state_bytes=4194304,max_receipt_bytes=1048576,
        tool_result_bytes=(24576,24576))
    assert reservation.receipt_bytes<=1048576 and reservation.state_bytes<=4194304
    assert reservation.tool_result_reservation_bytes>=49152


def test_legal_large_field_values_may_still_exceed_aggregate_capacity():
    with pytest.raises(ContextPackError,match='contextSnapshotLimit'):
        reserve_pack_capacity({'captured':'x'*500000},{'captured':'x'*500000},
            max_state_bytes=4194304,max_receipt_bytes=1048576,output_bytes=100000,
            tool_result_bytes=(24576,24576))
