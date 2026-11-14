"""The candidate-only contract runs on the exact installed SDK combination."""
from copy import deepcopy
from importlib import metadata
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
import prosaic
import prosaic.ontology
import prosaic_harness as harness
import prosaic_runtime as runtime
from prosaic_runtime.accounting import MemoryRecorder


def _attachment():
    return {
        'schemaVersion': 1, 'ontologyId': 'release-evidence',
        'concepts': {'receipt': 'Observed verification.', 'candidate': 'Release candidate.',
                     'hidden': 'Restricted concept.', 'unused': 'Unattached concept.'},
        'relations': [{'source': 'receipt', 'predicate': 'verifies', 'target': 'candidate'},
                      {'source': 'hidden', 'predicate': 'describes', 'target': 'candidate'}],
        'agents': {'reviewer': ['candidate'], 'private-reviewer': ['hidden']},
        'tools': {'read_receipt': ['receipt'], 'read_policy': ['hidden']},
    }


def _factory(ontology=None, *, agents=('reviewer',), tools=('read_receipt', 'read_policy'),
             runtime_tools=('read_receipt',), direct=('read_receipt',), delegates=None, handler=None):
    def forbidden(*args):
        pytest.fail('discovery ran a handler')

    schema = {'type': 'object', 'additionalProperties': True}
    parameters = {'type': 'object', 'properties': {'ontology': {'type': 'string'}},
                  'additionalProperties': False}
    registrations = {alias: runtime.CustomTool(alias, 'Read public evidence', parameters,
                                               handler or forbidden, 'v1')
                     for alias in ('read_receipt', 'read_policy')}
    registered_agents = {
        alias: runtime.ProsaicArtifact(f'subagents/{alias}.md', 'subagent',
            {'name': alias, 'description': 'Fixture reviewer', 'tools': []}, 'Review evidence.')
        for alias in ('reviewer', 'private-reviewer')
    }
    config = runtime.RuntimeConfig(
        {'fixture': runtime.EndpointConfig('http://127.0.0.1:1/v1', 'synthetic')},
        {}, 'fixture', allowed_tools=frozenset(runtime_tools))
    return harness.WorkflowFactory(
        catalog=harness.WorkflowCatalog(agents=registered_agents, schemas={'result': schema}, ontology=ontology),
        bindings=harness.WorkflowBindings(config=config, custom_tools=registrations, sub_agents=delegates),
        policy=harness.WorkflowPolicy(allowed_agents=agents, allowed_schemas={'result'}, allowed_tools=tools,
                                     allowed_direct_tools=direct, max_provider_requests_per_invocation=0,
                                     max_tool_calls_per_invocation=1))


def _graph():
    return {'version': 1, 'start': 'read', 'steps': {
        'read': {'kind': 'tool', 'tool': 'read_receipt', 'schema': 'result',
                 'arguments': {'ontology': 'opaque application data'}, 'next': 'finish'},
        'finish': {'kind': 'finish', 'requires': ['read']},
    }}


def test_exact_installed_ontology_sdk():
    expected = [('b3-prosaic', '0.5.1', prosaic), ('b3-prosaic-harness', '0.9.19', harness),
                ('b3-prosaic-runtime', '0.9.25', runtime)]
    for name, version, module in expected:
        distribution = metadata.distribution(name)
        assert distribution.version == version
        assert Path(module.__file__).resolve() == distribution.locate_file(
            f'{module.__name__}/__init__.py').resolve()
    assert Path(prosaic.ontology.__file__).resolve() == metadata.distribution('b3-prosaic').locate_file(
        'prosaic/ontology.py').resolve()


def test_projection_uses_existing_visibility_and_owns_the_result():
    document = _attachment()
    original = deepcopy(document)
    factory = _factory(document)
    document['agents']['reviewer'].clear()
    expected = {**original, 'agents': {'reviewer': ['candidate']}, 'tools': {'read_receipt': ['receipt']},
                'concepts': {name: original['concepts'][name] for name in ('receipt', 'candidate')},
                'relations': original['relations'][:1]}
    ordinary = factory.describe()
    assert 'ontology' not in ordinary
    enriched = factory.describe(include_ontology=True)
    assert enriched.pop('ontology') == expected
    assert enriched == ordinary
    expanded = factory.describe(include_schemas=True, include_ontology=True)
    assert expanded['ontology'] == expected
    expanded['ontology']['relations'].clear()
    assert factory.describe(include_ontology=True)['ontology'] == expected
    assert 'ontology' not in factory.describe(include_schemas=True)
    assert 'ontology' not in _factory(original, agents=(), runtime_tools=(), direct=()).describe(
        include_ontology=True)
    restricted = _factory(original, tools={'read_policy'}, runtime_tools={'read_policy', 'read_receipt'}, direct=())
    assert restricted.describe(include_ontology=True)['ontology']['tools'] == {'read_policy': ['hidden']}
    assert restricted.describe()['allowedDirectTools'] == []
    size = len(json.dumps(ordinary, sort_keys=True).encode())
    assert factory.describe(maximum_bytes=size) == ordinary
    with pytest.raises(harness.WorkflowAdmissionError) as caught:
        factory.describe(include_ontology=True, maximum_bytes=size)
    assert caught.value.code == 'limit_exceeded'


@pytest.mark.parametrize('category', ['agents', 'tools'])
def test_attachment_rejects_unknown_aliases(category):
    document = _attachment()
    document[category]['unregistered'] = ['receipt']
    with pytest.raises(harness.WorkflowAdmissionError) as caught:
        _factory(document)
    assert caught.value.code == 'unknown_reference'
    assert 'unregistered' not in str(caught.value)


def test_delegate_aliases_keep_the_existing_admission_boundary():
    child = runtime.ProsaicArtifact('delegate', 'subagent', {'tools': []}, 'Review evidence.')
    spec = runtime.SubAgentSpecV1('delegate', 'Delegated review', child, 'v1',
        runtime.RunPolicy(max_provider_requests=1, max_tool_calls=0, max_reported_tokens=5),
        {'type': 'object', 'additionalProperties': False})
    packs = harness.ContextPackBindings(
        specs={'review': harness.ContextPackSpec('review', '1', [harness.ContextSlot('receipt')])},
        sources={'receipt': harness.EvidenceSource('receipt.md')},
        scope=harness.ContextScope.from_dict(harness.ConversationScope(
            'test', 'sandbox', 'app', 'tenant', 'actor', 'payer').to_dict()),
        authorizer=harness.ContextAuthorizer('packs', 'v1', lambda _: True))
    delegates = harness.SubAgentBindingsV1(specs=(spec,), policy=runtime.SubAgentPolicyV1(1, 1, 1, 5),
        pack_bindings=packs, pack_names={'delegate': 'review'},
        revision='v1', authorize_launch=lambda *_: True, authorize_result=lambda *_: True,
        session_token_allowance=5)
    options = dict(tools={'delegate', 'read_receipt'}, runtime_tools={'delegate', 'read_receipt'},
                   delegates=delegates)
    document = _attachment()
    visible = _factory(document, **options).describe(include_ontology=True)
    assert 'delegate' not in visible['tools']
    assert set(visible['ontology']['tools']) == {'read_receipt'}
    document['tools']['delegate'] = ['receipt']
    with pytest.raises(harness.WorkflowAdmissionError) as caught:
        _factory(document, **options)
    assert caught.value.code == 'unknown_reference'


def test_ontology_cannot_be_authored_and_does_not_change_saved_identity(tmp_path):
    requests = []
    def handler(arguments):
        requests.append(arguments)
        return {'status': 'verified'}

    ordinary = _factory(handler=handler)
    attached = _factory(_attachment(), handler=handler)
    graph = _graph()
    proposal = json.dumps({'definition': graph})
    baseline = harness.WorkflowBundle('v1', ordinary)
    saved = baseline.prepare_json(proposal)
    store = harness.FileRunStore(tmp_path / 'runs', namespace='ontology')
    store.initialize()
    account = MemoryRecorder(provider_id='openai-compatible')
    context = runtime.ExecutionContext(application_id='app', tenant_id='tenant', actor_id='actor',
                                       billing_account_id='payer')
    options = dict(store=store, run_id='a' * 32, accounting=account, context=context)
    initial = harness.Harness(saved.workflow, **options).run({})
    assert initial['status'] == 'completed'
    assert requests == [{'ontology': 'opaque application data'}]
    replacement = _attachment()
    replacement['ontologyId'] = 'revised'
    for factory in (attached, _factory(replacement, handler=handler), ordinary):
        assert factory.proposal_schema() == ordinary.proposal_schema()
        bundle = harness.WorkflowBundle('v1', factory)
        prepared = bundle.prepare_json(proposal)
        assert bundle.identity == baseline.identity
        assert prepared.reference == saved.reference
        assert prepared.proposal_json == saved.proposal_json
        reopened = bundle.reconstruct(saved.proposal_json, saved.reference)
        assert reopened.fingerprint == saved.workflow.fingerprint
        assert harness.Harness(reopened, **options).resume() == initial
    assert requests == [{'ontology': 'opaque application data'}]
    invalid = {'definition': {**graph, 'ontology': _attachment()}}
    assert not Draft202012Validator(attached.proposal_schema()).is_valid(invalid)
    for build, value in ((attached.build, invalid['definition']),
                         (attached.build_json, json.dumps(invalid))):
        with pytest.raises(harness.WorkflowAdmissionError):
            build(value)
