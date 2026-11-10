from dataclasses import replace
import json
import time
import pytest
import prosaic_runtime as runtime_api
from prosaic_harness import ToolContracts, ContextPackReader
from prosaic_harness.context_packs.tool_contracts import pack_evidence_bindings, public_pack_input
from test_context_pack_reader import reader_case


def adapted(pack, bindings, *, grant=lambda use: True, required=True):
    contracts = ToolContracts('host', '1', evidence_authorizer=runtime_api.EvidenceAuthorizerV1('sources', '1', grant),
        citations=runtime_api.CitationPolicyV1('required') if required else None)
    return pack_evidence_bindings(pack, None, bindings, tool_contracts=contracts,
        scope=runtime_api.InvocationScope('a' * 32, operation_namespace='tenant'), deadline=time.monotonic() + 30)


def test_inline_selected_context_is_citable():
    _, pack, bindings = reader_case(availability='inline')
    adapter = adapted(pack, bindings)
    from prosaic_runtime.tool_evidence import EvidenceRegistryV1
    registry = EvidenceRegistryV1(adapter.runtime_bindings)
    payload = {'messages': [{'role': 'user', 'content': json.dumps(public_pack_input({'contextPack': pack.envelope}))}]}
    ticket = registry.prepare_delivery(payload)
    registry.begin_delivery(ticket, 'request'); registry.confirm_delivery(ticket, 'request')
    citation = pack.envelope['items'][0]['citationId']
    registry.authorize(citation, 'cite')
    sidecar = runtime_api.validate_citations(f'[cite:{citation}]', registry.eligible(), runtime_api.CitationPolicyV1('required'))
    assert sidecar.to_dict()['markers'][0]['evidenceId'] == citation
    assert 'sourceLocator' not in json.dumps(payload) and 'sourceIdentity' not in json.dumps(payload)


def test_index_only_entry_is_not_citable():
    _, pack, bindings = reader_case()
    adapter = adapted(pack, bindings)
    assert adapter.runtime_bindings.retained == ()


def test_event_only_pack_binding_needs_no_evidence_authorizer():
    _,pack,bindings=reader_case(availability='inline')
    adapter=pack_evidence_bindings(pack,None,bindings,tool_contracts=ToolContracts('events','1'),
        scope=runtime_api.InvocationScope('a'*32),deadline=time.monotonic()+30)
    assert adapter.runtime_bindings.evidence_authorizer is None and adapter.runtime_bindings.retained==()


@pytest.mark.parametrize('generic_allowed,pack_allowed', [(True, False), (False, True), (False, False)])
def test_generic_and_pack_authorizers_both_required(generic_allowed, pack_allowed):
    from prosaic_runtime.tool_evidence import EvidenceRegistryV1, EvidenceUseDenied
    _, pack, bindings = reader_case(availability='inline', authorize=lambda use: pack_allowed or use.purpose != 'citation')
    adapter = adapted(pack, bindings, grant=lambda use: generic_allowed or use.purpose != 'cite')
    registry = EvidenceRegistryV1(adapter.runtime_bindings)
    ticket = registry.prepare_delivery(public_pack_input({'contextPack': pack.envelope}))
    registry.begin_delivery(ticket, 'request'); registry.confirm_delivery(ticket, 'request')
    with pytest.raises(EvidenceUseDenied): registry.authorize(pack.envelope['items'][0]['citationId'], 'cite')


def test_unrecognized_citation_purpose_denies():
    from prosaic_runtime.tool_evidence import EvidenceRegistryV1, EvidenceUseDenied
    known = {'invocation', 'deferredRead', 'historyReuse', 'validation', 'retainedRead'}
    _, pack, bindings = reader_case(availability='inline', authorize=lambda use: use.purpose in known)
    adapter = adapted(pack, bindings)
    registry = EvidenceRegistryV1(adapter.runtime_bindings)
    ticket = registry.prepare_delivery(public_pack_input({'contextPack': pack.envelope}))
    registry.begin_delivery(ticket, 'request'); registry.confirm_delivery(ticket, 'request')
    with pytest.raises(EvidenceUseDenied): registry.authorize(pack.envelope['items'][0]['citationId'], 'cite')


def test_partial_read_cannot_cite_parent():
    from prosaic_runtime.tools import execute_custom_tool
    from prosaic_runtime.tool_evidence import EvidenceRegistryV1
    from prosaic_runtime.tool_event_contract import tool_contract_session
    _, pack, bindings = reader_case('captured public and private tail')
    reader = ContextPackReader(tool_contracts=True)
    adapter = adapted(pack, bindings, required=False)
    scope = adapter.runtime_bindings.scope
    citation = pack.envelope['index'][0]['citationId']
    registry = EvidenceRegistryV1(adapter.runtime_bindings)
    with reader.activate(scope, pack, bindings, deadline=time.monotonic() + 30, evidence_capture=adapter.capture_read), tool_contract_session(adapter.runtime_bindings, registry):
        raw = execute_custom_tool(reader.as_tool(), json.dumps({'citationId': citation, 'start': 0, 'end': 8}),
            check_boundary=lambda: None, scope=scope, deadline=time.monotonic() + 30)
        frame = registry.stage(reader.as_tool(), raw, raw, call_id='call', call_index=0, arguments_sha256='a' * 64)
        ticket = registry.prepare_delivery(frame)
        registry.begin_delivery(ticket, 'request'); registry.confirm_delivery(ticket, 'request')
    assert frame['result']['data']['content'] == 'captured'
    reference = frame['result']['evidence'][0]['id']
    assert reference.startswith('ev_') and registry.eligible().ids == (reference,) and citation not in registry.eligible().ids
    assert registry.to_dict()['records'][0]['sourceKey'] == citation
    assert 'sourceLocator' not in json.dumps(frame) and 'private tail' not in json.dumps(frame)


def test_private_authoritative_facts_never_become_sources():
    _, pack, bindings = reader_case(availability='inline')
    adapter = adapted(pack, bindings)
    assert len(adapter.runtime_bindings.retained) == len(pack.envelope['items'])
    assert all(item.evidence_id not in [entry['citationId'] for entry in pack.envelope['index']] for item in adapter.runtime_bindings.retained)


def test_enabled_frame_preserves_public_projection_and_private_origins():
    from prosaic_harness import ContextPacker
    from prosaic_harness.context_packs.records import ContextPackInvocation
    from prosaic_harness.context_packs.tool_contracts import CONVERSATION_PROFILE
    _, pack, bindings = reader_case(availability='inline')
    adapter = adapted(pack, bindings)
    candidates = ContextPacker().compose(pack.spec, pack.snapshot)
    runtime = runtime_api.ProsaicRuntime(runtime_api.RuntimeConfig({'local': runtime_api.EndpointConfig(
        'http://127.0.0.1:9/v1', 'fixture', features={'streaming': False})}, {}, 'local', frozenset()))
    agent = runtime_api.ProsaicArtifact('approved', 'subagent', {}, 'Use selected context.')
    prepared = runtime.prepare_turn(agent, message='Review', input_data=public_pack_input({'contextPack': pack.envelope}),
        input_profile=CONVERSATION_PROFILE, policy=runtime_api.RunPolicy(max_provider_requests=1, max_tool_calls=0),
        tool_contract_bindings=adapter.runtime_bindings)
    frame = ContextPackInvocation.from_prepared('a' * 32, candidates, pack, prepared, runtime_input_mapping=[0])
    assert frame.to_dict()['version'] == 2
    assert ContextPackInvocation.from_dict(frame.to_dict()).to_dict() == frame.to_dict()
    assert 'sourceLocator' not in json.dumps(frame.frozen_input.to_dict()['selectedInputData'])
    assert 'sourceLocator' in json.dumps(frame.prepared_pack.envelope)
