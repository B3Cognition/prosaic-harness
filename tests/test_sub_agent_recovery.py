"""Delegation runs through the ordinary leased Harness conversation."""
from dataclasses import replace
from hashlib import sha256
import json

import pytest

import prosaic_harness as harness
import prosaic_runtime as runtime
from prosaic_runtime.accounting import MemoryRecorder
from support.tool_journal import MemoryJournal
from test_mcp_bindings import contract
from test_workflow_rules_execution import rule_endpoint


def make_chat(config, store, *, allow=lambda *_: True, parent_packs=None):
    scope = harness.ConversationScope('test', 'sandbox', 'app', 'tenant', 'actor', 'payer')
    child = runtime.ProsaicArtifact('reviewer', 'subagent', {'tools': []}, 'Return a review as JSON.')
    specialist = runtime.SubAgentSpecV1('review', 'Review a dependency', child, 'v1',
        runtime.RunPolicy(max_provider_requests=1, max_tool_calls=0, max_reported_tokens=50),
        {'type': 'object', 'properties': {'finding': {'type': 'string'}},
         'required': ['finding'], 'additionalProperties': False})
    pack = harness.ContextPackSpec('review', '1', [harness.ContextSlot('graph', required=True)])
    packs = harness.ContextPackBindings(specs={'review': pack},
        sources={'graph': harness.EvidenceSource('graph.md')}, scope=harness.ContextScope.from_dict(scope.to_dict()),
        authorizer=harness.ContextAuthorizer('packs', 'v1', lambda _: True))
    text = 'Child only dependency'
    delegates = harness.SubAgentBindingsV1(specs=(specialist,), policy=runtime.SubAgentPolicyV1(1, 3, 1, 100),
        pack_bindings=packs, pack_names={'review': 'review'}, revision='v1',
        authorize_launch=lambda *_: True, authorize_result=allow, session_token_allowance=200,
        evidence={'graph.md': {'text': text, 'sha256': sha256(text.encode()).hexdigest()}})
    parent = runtime.ProsaicArtifact('parent', 'subagent', {'name':'parent','description':'Coordinator','tools': ['review']}, 'Return a final answer.')
    bindings = harness.ConversationBindings(parent, version='v1', config=replace(config, allowed_tools=frozenset({'review'})),
        policy=harness.ConversationPolicy(), run_policy=runtime.RunPolicy(allowed_tools=frozenset({'review'}),
            max_provider_requests=3, max_tool_calls=1, max_reported_tokens=100),
        tool_contracts=contract(), sub_agents=delegates, context_packs=parent_packs, operation_namespace='delegation', tool_journal=MemoryJournal())
    recorder = MemoryRecorder(provider_id=config.profiles[config.default_profile].provider)
    context = runtime.ExecutionContext(application_id='app', tenant_id='tenant', actor_id='actor',
                                      billing_account_id=scope.billing_account)
    return harness.Conversation(bindings, store=store, scope=scope, context=context, accounting=recorder)


def test_lost_parent_receipt_ack_adopts_with_endpoints_offline(rule_endpoint, tmp_path):
    assert hasattr(harness, 'SubAgentBindingsV1'), 'Harness delegate binding is missing'
    config, requests, replies = rule_endpoint
    store = harness.MemorySessionStore(namespace='test')
    store.initialize(sub_agents=True)
    chat = make_chat(config, store)
    created = chat.create()
    replies.extend([{'name': 'review', 'input': {'task': 'Check'}}, '{"finding":"Verified"}', 'Accepted'])

    def interrupt(event):
        if event['event'] == 'receiptSaved':
            raise OSError('lost acknowledgment')

    with pytest.raises(OSError, match='lost acknowledgment'):
        chat.send(created.session_id, message_id='one', message='Parent-only text',
                  expected_revision=created.revision, on_event=interrupt)
    assert len(requests) == 3
    assert 'Child only dependency' in json.dumps(requests[1])
    assert 'Parent-only text' not in json.dumps(requests[1])
    fresh = harness.Conversation(chat.bindings, store=store, scope=chat.scope, context=chat.context,
                                 accounting=chat.accounting)
    assert fresh.recover(created.session_id).document['answer'] == 'Accepted'
    assert len(requests) == 3


def test_native_workflow_rejects_delegate_proposals_and_adopts_receipt(rule_endpoint, tmp_path, monkeypatch):
    config, requests, replies = rule_endpoint
    memory = harness.MemorySessionStore(namespace='test')
    memory.initialize(sub_agents=True)
    chat = make_chat(config, memory)
    policy = harness.WorkflowPolicy(allowed_agents={'parent'}, allowed_schemas={'result'},
        allowed_tools={'review'}, max_provider_requests_per_invocation=3, max_tool_calls_per_invocation=1,
        max_tokens=200)
    bindings = harness.WorkflowBindings(config=chat.bindings.config, tool_contracts=chat.bindings.tool_contracts,
        sub_agents=chat.bindings.sub_agents, operation_namespace='delegation', tool_journal=MemoryJournal())
    factory = harness.WorkflowFactory(catalog=harness.WorkflowCatalog(
        agents={'parent': chat.bindings.agent}, schemas={'result': {'type': 'object'}}),
        bindings=bindings, policy=policy)
    graph = {'version': 1, 'start': 'review', 'steps': {
        'review': {'kind': 'agent', 'agent': 'parent', 'schema': 'result', 'tools': ['review'], 'next': 'done'},
        'done': {'kind': 'finish'}}}
    assert 'review' not in factory.describe()['tools']
    with pytest.raises(ValueError):
        factory.build_json(json.dumps({'definition': graph}))
    workflow = factory.build(graph)
    store = harness.FileRunStore(tmp_path / 'run', namespace='test')
    store.initialize(sub_agents=True)
    options = dict(store=store, run_id='a' * 32, accounting=chat.accounting, context=chat.context)
    controller = harness.Harness(workflow, **options)
    replies.extend([{'name': 'review', 'input': {'task': 'Check'}}, '{"finding":"Verified"}', '{"ok":true}'])

    def interrupt(*_):
        raise OSError('lost workflow acknowledgment')

    monkeypatch.setattr(controller, '_accept', interrupt)
    with pytest.raises(OSError, match='lost workflow acknowledgment'):
        controller.run({})
    assert len(requests) == 3
    result = harness.Harness(workflow, **options).resume()
    assert result['status'] == 'completed'
    assert result['version'] == 6
    assert len(requests) == 3



def parent_pack(scope):
    spec = harness.ContextPackSpec('parent', '1', [harness.ContextSlot('parent', required=True)])
    return harness.ContextPackBindings(specs={'parent': spec},
        sources={'parent': harness.InputSource('/parent')},
        scope=harness.ContextScope.from_dict(scope.to_dict()),
        authorizer=harness.ContextAuthorizer('packs', 'v1', lambda _: True),
        agent_defaults={'parent': 'parent'})


def test_parent_pack_is_not_inherited_by_child(rule_endpoint):
    from prosaic_harness.context_packs.sources import capture_sources
    config, requests, replies = rule_endpoint
    store = harness.MemorySessionStore(namespace='test')
    store.initialize(sub_agents=True)
    packs = parent_pack(make_chat(config, store).scope)
    chat = make_chat(config, store, parent_packs=packs)
    spec = packs.specs['parent']
    candidates = harness.ContextPacker().compose(spec,
        capture_sources(spec, {'request': {'parent': 'Parent pack sentinel'}}, {}, packs))
    session = chat.create()
    replies.extend([{'name': 'review', 'input': {'task': 'Check'}}, '{"finding":"Verified"}', 'Accepted'])
    reply = chat.send(session.session_id, message_id='one', message='Parent question',
        expected_revision=session.revision, context_pack=candidates)
    assert reply.document['answer'] == 'Accepted'
    assert 'Parent pack sentinel' in json.dumps(requests[0])
    assert 'Parent pack sentinel' not in json.dumps(requests[1])
    assert 'Child only dependency' in json.dumps(requests[1])
