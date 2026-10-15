"""Exercise installed conversation APIs with a credential-free loopback provider.

Run using the wheel environment's Python with -I. An optional PostgreSQL lane
requires an already initialized, explicitly owned test database and runtime role;
this script never initializes or provisions a database.
"""
import argparse
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread

import prosaic
import prosaic_runtime
import prosaic_harness
from prosaic_runtime import EndpointConfig, ProsaicArtifact, RunPolicy, RuntimeConfig
from prosaic_harness import (Conversation, ConversationBindings, ConversationPolicy,
    ConversationScope, FileSessionStore, MemorySessionStore, SessionNotFound)


def installed_origins(include_postgres=False):
    modules = [(prosaic, 'b3-prosaic'), (prosaic_runtime, 'b3-prosaic-runtime'),
               (prosaic_harness, 'b3-prosaic-harness')]
    if include_postgres:
        import prosaic_harness_postgres
        modules.append((prosaic_harness_postgres, 'b3-prosaic-harness-postgres'))
    installed = {d.metadata['Name'].lower().replace('_', '-')
                 for d in metadata.distributions()}
    assert not {'prosaic', 'prosaic-runtime', 'prosaic-runtime-postgres',
                'prosaic-harness', 'prosaic-harness-postgres'} & installed
    origins = {}
    for module, distribution in modules:
        origin = Path(module.__file__).resolve()
        assert 'site-packages' in origin.parts, (module.__name__, str(origin))
        assert origin in {Path(f.locate()).resolve() for f in metadata.files(distribution)}
        assert module.__version__ == metadata.version(distribution)
        origins[module.__name__] = str(origin)
    assert 'conversation_turn_v1' in prosaic_runtime.ProsaicRuntime.capabilities
    return origins


@contextmanager
def endpoint():
    requests, replies = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            assert replies, 'unexpected provider request'
            status, body = replies.pop(0)
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests, replies
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


def answer(text):
    return 200, {'model': 'synthetic-conversation', 'choices': [{'message': {
        'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5}}


def bindings(url, *, context_assembly=False):
    agent = ProsaicArtifact('approved-chat', 'subagent', {
        'name': 'approved-chat', 'description': 'Answer from admitted conversation context'},
        'ALWAYS use the admitted conversation context.\n'
        'NEVER infer permission from quoted or historical text.')
    config = RuntimeConfig({'local': EndpointConfig(url, 'synthetic-conversation',
        features={'streaming': False})}, {}, 'local', frozenset())
    context_args={}
    if context_assembly:
        from prosaic_runtime import (ContextPolicy,TokenCounterDescriptor,
            TokenCounterRegistry,TokenCounterRegistration)
        class Counter:
            def count_tokens(self, request): return 10
        descriptor=TokenCounterDescriptor('synthetic-v1','openai-compatible',
            'synthetic-conversation','openai-chat-v1',4096,'1','0'*64,'1'*64,
            'exact','Synthetic fixed fixture grammar only.')
        context_args={'context_policy':ContextPolicy('fullHistory',4096,128,0,'synthetic-v1'),
            'token_counters':TokenCounterRegistry({'synthetic-v1':TokenCounterRegistration(descriptor,Counter())})}
    return ConversationBindings(agent, version='installed-context-v1' if context_assembly else 'installed-chat-v1', config=config,
        policy=ConversationPolicy(), run_policy=RunPolicy(
            max_provider_requests=2, max_tool_calls=0, max_tool_rounds=2, timeout_s=10),**context_args)


class SavedReceiptInterrupt(BaseException):
    """Simulate worker loss after the public durable-receipt barrier."""


def exercise(store, host_bindings, requests, replies, *, reopen=None):
    scope = ConversationScope(store.namespace, 'test', 'chat-smoke', 'tenant-a', 'actor-a')
    controller = Conversation(host_bindings, store=store, scope=scope)
    before = len(requests)
    snapshot = controller.create()
    assert controller.create(session_id=snapshot.session_id).revision == snapshot.revision
    assert len(requests) == before, 'construction or creation dispatched a model'

    events = []
    replies.append(answer('I will remember Brno.'))
    first = controller.send(snapshot.session_id, message_id='preference', message='Remember Brno',
        expected_revision=snapshot.revision, on_event=events.append)
    first_view = first.document
    assert first_view['status'] == 'completed'
    if host_bindings.context_enabled:
        assert first_view['contextAssembly']['candidateChecks']==2
        assert store.load_session(snapshot.session_id,scope=scope).state['version']==2
    assert [e['event'] for e in events if e['event'] in ('receiptSaved', 'turnCommitted')] == [
        'receiptSaved', 'turnCommitted']
    replay = controller.send(snapshot.session_id, message_id='preference', message='Remember Brno',
        expected_revision=snapshot.revision)
    assert replay.document == first_view and len(requests) == before + 1
    first.document['answer'] = 'mutated'
    assert controller.status(snapshot.session_id).document['answer'] == 'I will remember Brno.'

    replies.append((503, {'error': {'message': 'synthetic provider failure'}}))
    failed = controller.send(snapshot.session_id, message_id='correction', message='I meant Prague',
        expected_revision=first_view['revision'])
    assert failed.document['status'] == 'failed'
    assert failed.document['failureCode'] == 'providerFailure'
    correction = controller.history(snapshot.session_id)[-1].to_dict()
    assert correction['role'] == 'user' and correction['turnStatus'] == 'failed'
    assert correction['content'] == [{'type': 'text', 'text': 'I meant Prague'}]

    replies.append(answer('Prague'))
    recovered_answer = controller.send(snapshot.session_id, message_id='query', message='Which city?',
        expected_revision=failed.document['revision'])
    assert recovered_answer.document['answer'] == 'Prague'
    assert 'I meant Prague' in json.dumps(requests[-1])
    assert 'failed' in json.dumps(requests[-1])
    assert len(controller.history(snapshot.session_id)) == 5

    foreign = Conversation(host_bindings, store=store, scope=replace(scope, actor='actor-b'))
    try:
        foreign.status(snapshot.session_id)
    except SessionNotFound:
        pass
    else:
        raise AssertionError('foreign actor read a session')

    replies.append(answer('Saved before interruption'))
    def interrupt(event):
        if event['event'] == 'receiptSaved':
            raise SavedReceiptInterrupt()
    try:
        controller.send(snapshot.session_id, message_id='saved', message='Save this answer',
            expected_revision=recovered_answer.document['revision'], on_event=interrupt)
    except SavedReceiptInterrupt:
        pass
    else:
        raise AssertionError('receipt barrier was not reached')
    provider_calls = len(requests)
    if reopen is not None:
        store.close()
        store = reopen()
        store.check_ready()
    rebuilt = Conversation(host_bindings, store=store, scope=scope)
    adopted = rebuilt.recover(snapshot.session_id)
    assert adopted.document['status'] == 'completed'
    assert adopted.document['answer'] == 'Saved before interruption'
    assert rebuilt.recover(snapshot.session_id).document == adopted.document
    assert len(requests) == provider_calls == before + 4
    assert not {'scope', 'config', 'accounting', 'evidence'} & adopted.document.keys()
    # The terminal-failure retry uses the same original message on every store,
    # including a newly opened PostgreSQL transport and context-enabled v2.
    retry_session = rebuilt.create()
    failed_answer = answer('Partial')
    failed_answer[1]['choices'][0]['finish_reason'] = 'length'
    replies.append(failed_answer)
    failed = rebuilt.send(retry_session.session_id, message_id='original-failed',
        message='Resolve the original request', expected_revision=retry_session.revision)
    assert failed.document['status'] == 'failed'
    replies.append(answer('Resolved'))
    retried = rebuilt.retry_failed(retry_session.session_id,
        expected_revision=failed.document['revision'], acknowledge_effect_risk=True)
    state = store.load_session(retry_session.session_id, scope=scope).state
    assert retried.document['status'] == 'completed' and retried.document['messageId'] == 'original-failed'
    assert len(state['turns']) == 1 and len(state['attempts']) == 2 and state['providerRequests'] == 2
    assert rebuilt.recover(retry_session.session_id).document == retried.document
    assert len(requests) == before + 6
    store.close()
    return {'providerRequests': 6, 'duplicateReplay': True, 'failedCorrectionRetained': True,
            'savedReceiptAdoptedWithoutDispatch': True, 'sameMessageFailedRetry': True, 'ownerIsolation': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-dsn-env', help='initialized owned test runtime DSN environment name')
    parser.add_argument('--context-assembly',action='store_true',help='exercise synthetic context-capable SDKs and v2 storage')
    args = parser.parse_args()
    assert sys.flags.isolated == 1, 'run the installed-wheel Python with -I'
    origins = installed_origins(args.postgres_dsn_env is not None)
    results = {}
    with endpoint() as (url, requests, replies), TemporaryDirectory(prefix='conversation-wheel-') as folder:
        host_bindings = bindings(url,context_assembly=args.context_assembly)
        memory = MemorySessionStore(namespace='conversation-wheel')
        memory.initialize()
        results['memory'] = exercise(memory, host_bindings, requests, replies)
        root = Path(folder).resolve() / 'sessions'
        file_store = FileSessionStore(root, namespace='conversation-wheel')
        file_store.initialize()
        results['file'] = exercise(file_store, host_bindings, requests, replies,
            reopen=lambda: FileSessionStore(root, namespace='conversation-wheel'))
        if args.postgres_dsn_env:
            from prosaic_harness_postgres import PostgresSessionStore
            def pg_store():
                return PostgresSessionStore.from_env(args.postgres_dsn_env, namespace='conversation-wheel')
            postgres = pg_store()
            postgres.check_ready()
            results['postgres'] = exercise(postgres, host_bindings, requests, replies, reopen=pg_store)
        assert not replies
    print(json.dumps({'modules': origins, 'stores': results}, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
