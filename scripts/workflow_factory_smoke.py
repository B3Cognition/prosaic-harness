"""Verify installed candidate wheels through a synthetic native workflow.

Run with the clean environment's Python:
    /path/to/wheel-env/bin/python -I /absolute/path/to/workflow_factory_smoke.py

No model service, Prosaic executable or Node installation is used. The only HTTP
endpoint is a disposable loopback fixture owned by this process.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import uuid

import prosaic
import prosaic_runtime
import prosaic_harness
from prosaic_runtime import CustomTool, EndpointConfig, ProsaicArtifact, RuntimeConfig
from prosaic_harness import (FileRunStore, Harness, Validator, WorkflowBindings,
                             WorkflowCatalog, WorkflowFactory, WorkflowPolicy,
                             WorkflowBundle, WorkflowReference)


def installed_origins():
    installed = {distribution.metadata['Name'].lower().replace('_', '-')
                 for distribution in metadata.distributions()}
    assert {'b3-prosaic', 'b3-prosaic-runtime', 'b3-prosaic-harness'} <= installed, installed
    assert not {'prosaic', 'prosaic-runtime', 'prosaic-runtime-postgres',
                'prosaic-harness', 'prosaic-harness-postgres'} & installed, installed
    origins = {}
    for module, distribution in ((prosaic, 'b3-prosaic'),
                                 (prosaic_runtime, 'b3-prosaic-runtime'),
                                 (prosaic_harness, 'b3-prosaic-harness')):
        origin = Path(module.__file__).resolve()
        assert 'site-packages' in origin.parts, (module.__name__, str(origin))
        owned = {Path(file.locate()).resolve() for file in metadata.files(distribution)}
        assert origin in owned, (module.__name__, distribution, str(origin))
        assert module.__version__ == metadata.version(distribution)
        origins[module.__name__] = str(origin)
    assert callable(prosaic.validate_artifact_definition)
    assert callable(prosaic_runtime.validate_execution_artifact)
    assert callable(prosaic_runtime.validate_custom_tools)
    assert callable(prosaic_runtime.custom_descriptors)
    assert callable(prosaic_runtime.InvocationScope)
    assert callable(prosaic_runtime.tool_journal_descriptor)
    return origins


def completion(content='', calls=None):
    message = {'content': content}
    if calls:
        message['tool_calls'] = calls
    return {'choices': [{'message': message, 'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': {'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 7}}


@contextmanager
def synthetic_endpoint():
    requests = []
    replies = [
        completion(calls=[{'id': 'lookup-1', 'type': 'function', 'function': {
            'name': 'lookup_item', 'arguments': '{"query":"sample"}'}}]),
        completion('{"entity_id":"sample-1","label":"Synthetic item"}'),
    ]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append({'path': self.path,
                             'body': json.loads(self.rfile.read(int(self.headers['Content-Length'])))})
            status = 200 if replies else 500
            body = json.dumps(replies.pop(0) if replies else {'error': 'unexpected fixture request'}).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests, replies
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        assert not worker.is_alive(), 'fixture server did not stop'


def proposal():
    return {'version': 1, 'name': 'synthetic-selection', 'start': 'find', 'steps': {
        'find': {'kind': 'agent', 'agent': 'finder', 'schema': 'entity',
                 'tools': ['lookup_item'], 'require_tools': ['lookup_item'], 'next': 'review'},
        'review': {'kind': 'pause', 'question': 'Confirm the displayed entity?',
                   'choices': {'accept': 'done', 'reject': 'rejected'}, 'requires': ['find'],
                   'response_schema': 'confirmation', 'validators': ['selection']},
        'done': {'kind': 'finish', 'requires': ['find']},
        'rejected': {'kind': 'finish', 'outcome': 'rejected'},
    }}


def make_factory(endpoint_url, tool_calls):
    def lookup(arguments, context):
        assert context.scope.operation_namespace == 'smoke-domain-v1'
        assert context.scope.step_id == 'find'
        tool_calls.append(arguments)
        return {'entity_id': 'sample-1', 'label': 'Synthetic item'}

    def selection(value, context):
        return ([] if value['response']['entity_id'] == context.artifacts['find']['entity_id']
                else ['Confirm the entity displayed by this run'])

    agent = ProsaicArtifact('subagents/finder.md', 'subagent', {
        'name': 'finder', 'description': 'Find a synthetic entity',
        'model_tier': 'fast', 'tools': ['lookup_item'],
    }, 'ALWAYS use lookup_item to obtain the requested entity.\n'
       'NEVER invent an entity or claim a tool was used without using it.\n'
       'ALWAYS return one JSON object with entity_id and label.\n'
       'NEVER include prose outside the JSON object.')
    schemas = {
        'entity': {'type': 'object', 'properties': {
            'entity_id': {'type': 'string', 'maxLength': 64},
            'label': {'type': 'string', 'maxLength': 128}},
            'required': ['entity_id', 'label'], 'additionalProperties': False},
        'confirmation': {'type': 'object', 'properties': {
            'entity_id': {'type': 'string', 'maxLength': 64}},
            'required': ['entity_id'], 'additionalProperties': False},
    }
    config = RuntimeConfig({'local': EndpointConfig(endpoint_url, 'synthetic-model',
                          features={'streaming': False})}, {'fast': 'local'}, 'local',
                          allowed_tools=frozenset({'lookup_item'}))
    tool = CustomTool('lookup_item', 'Find a synthetic entity', {
        'type': 'object', 'properties': {'query': {'type': 'string', 'maxLength': 128}},
        'required': ['query'], 'additionalProperties': False,
    }, lookup, 'v1', with_context=True)
    return WorkflowFactory(
        catalog=WorkflowCatalog(agents={'finder': agent}, schemas=schemas),
        bindings=WorkflowBindings(config=config, custom_tools={'lookup_item': tool},
                                  validators={'selection': Validator('v1', selection)},
                                  operation_namespace='smoke-domain-v1'),
        policy=WorkflowPolicy(allowed_agents=frozenset({'finder'}),
            allowed_schemas=frozenset({'entity', 'confirmation'}),
            allowed_tools=frozenset({'lookup_item'}), allowed_validators=frozenset({'selection'}),
            allowed_model_tiers=frozenset({'fast'}), max_calls=2, max_tokens=128, max_run_s=60,
            max_provider_requests_per_invocation=2, max_tool_calls_per_invocation=1),
    )


def exercise_factory():
    original_path = os.environ.get('PATH')
    os.environ['PATH'] = ''
    try:
        assert shutil.which('node') is None
        assert shutil.which('prosaic') is None
        tool_calls, events = [], []
        with synthetic_endpoint() as (url, requests, replies), TemporaryDirectory(prefix='workflow-wheel-') as folder:
            store = FileRunStore(Path(folder).resolve() / 'runs', namespace='smoke')
            run_id = uuid.uuid4().hex
            definition = proposal()
            factory = make_factory(url, tool_calls)
            description = factory.describe(include_schemas=True)
            assert description['defaultModelTierAllowed'] is True
            assert description['limits']['maxProviderRequestsPerInvocation'] == 2
            assert description['limitUnits']['maxToolCallsPerInvocation'] == 'perInvocation'
            assert 'lookup_item' in description['tools'] and 'entity' in description['schemas']
            assert factory.proposal_schema()['type'] == 'object'
            bundle = WorkflowBundle('smoke-v1', factory)
            prepared = bundle.prepare_json(json.dumps({'definition': definition}))
            workflow = prepared.workflow
            assert workflow.path is None
            request = workflow.prepare_inputs({'query': 'sample'})
            assert request == {'query': 'sample'}
            harness = Harness(workflow, store=store, run_id=run_id, on_event=events.append)
            state = harness.run(request)
            assert state['status'] == 'waiting', state.get('reason')
            assert state['calls'] == 1 and state['pending'] is None
            assert state['outputs']['find'] == {'entity_id': 'sample-1', 'label': 'Synthetic item'}
            waiting = harness.status()
            interaction = harness.interaction(review_outputs=('find',), include_response_schema=True)
            assert interaction.revision == waiting.revision
            assert interaction.to_dict()['choices'] == ['accept', 'reject']
            assert waiting.revision == harness.status().revision, 'status changed the checkpoint'
            rebuilt = WorkflowBundle('smoke-v1', make_factory(url, tool_calls)).reconstruct(
                prepared.proposal_json, WorkflowReference.from_dict(prepared.reference.to_dict()))
            assert rebuilt.fingerprint == workflow.fingerprint, 'reconstruction changed identity'
            resumed = Harness(rebuilt, store=store, run_id=run_id)
            before_invalid = resumed.status().revision
            try:
                resumed.resume(choice='accept', response={'entity_id': 'other'},
                               expected_revision=before_invalid)
            except ValueError:
                pass
            else:
                raise AssertionError('host selection validator accepted another entity')
            assert resumed.status().revision == before_invalid, 'invalid response wrote a checkpoint'
            completed = resumed.resume(choice='accept', response={'entity_id': 'sample-1'},
                                       expected_revision=before_invalid)
            assert completed['status'] == 'completed'
            assert resumed.resume()['status'] == 'completed'
            assert completed['version'] == 2 and completed['calls'] == 1
            invocation = completed['invocations'][0]
            assert invocation['status'] == 'complete' and invocation['token_usage'] == 14
            receipt = store.load_receipt(run_id, invocation['id'])
            assert receipt['version'] == 1 and receipt['sha256'] == invocation['receipt_sha256']
            assert receipt['result']['metadata']['invocation_budgets_v1'] == {
                'provider_requests': 2, 'tool_calls': 1, 'reported_tokens': 14, 'usage_complete': True}
            assert 'accounting_context' not in completed
            assert tool_calls == [{'query': 'sample'}]
            assert len(requests) == 2 and replies == [], 'resume dispatched another provider call'
            assert all(request['path'] == '/v1/chat/completions' for request in requests)
            assert 'prosaic-workflow-' not in json.dumps([completed, receipt, requests, events])
            store.close()
        return {'status': 'completed', 'harness_invocations': 1, 'provider_requests': 2,
                'native_tool_calls': 1, 'checkpoint_version': 2, 'receipt_version': 1,
                'discovery': True, 'bundle_reconstruction': True,
                'input_preparation': True, 'interaction': True,
                'node_on_path': False, 'prosaic_cli_on_path': False}
    finally:
        if original_path is None:
            os.environ.pop('PATH', None)
        else:
            os.environ['PATH'] = original_path


def main():
    assert sys.flags.isolated == 1, 'run the installed-wheel Python with -I'
    origins = installed_origins()
    print(json.dumps({'modules': origins, **exercise_factory()}, indent=2))


if __name__ == '__main__':
    main()
