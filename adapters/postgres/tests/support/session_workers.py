"""Spawn-only store clients with finite, test-owned durable-edge barriers."""
import multiprocessing


def run_worker(dsn, session_id, command, edge, ready, release, channel, revision, operation_timeout_s):
    from prosaic_harness import ConversationScope, StoreError, RevisionConflict
    from prosaic_harness.session_contracts import mark_dispatch, adopt_receipt
    from prosaic_harness_postgres import PostgresSessionStore
    from support.session_documents import document, reserve, receipt
    scope = ConversationScope('conversation-workers', 'sandbox', 'chat', 'tenant', 'actor')
    def barrier(name):
        if name == edge:
            ready.set()
            if not release.wait(30):
                raise TimeoutError('test worker durable-edge bound exceeded')
    try:
        with PostgresSessionStore(dsn, namespace=scope.namespace,
                                  operation_timeout_s=operation_timeout_s) as store:
            store.check_ready()
            if command == 'status':
                snapshot = store.load_session(session_id, scope=scope)
                result = {'revision': snapshot.revision,
                          'turns': len(snapshot.state['turns']),
                          'pending': snapshot.state['pending']}
            else:
                with store.lease(session_id, scope=scope) as lease:
                    if command == 'start':
                        state = document(scope, session_id=session_id)
                        current = store.create_session(session_id, state, lease, scope=scope)
                        barrier('created')
                        state = reserve(state)
                        current = store.save_session(session_id, state, current, lease, scope=scope)
                        barrier('reserved')
                        state = mark_dispatch(state, 'b' * 32)
                        current = store.save_session(session_id, state, current, lease, scope=scope)
                        barrier('dispatched')
                        saved = receipt(state)
                        store.save_receipt(session_id, 'b' * 32, saved, lease, scope=scope)
                        barrier('receipt')
                    else:
                        snapshot = store.load_session(session_id, scope=scope)
                        state, current = snapshot.state, snapshot.revision
                        if command == 'advance':
                            # The caller's actual revision authorizes this transition.
                            if current != revision:
                                raise RevisionConflict()
                            changed = reserve(state)
                            current = store.save_session(session_id, changed, revision, lease, scope=scope)
                            state = changed
                            saved = None
                        else:
                            saved = store.load_receipt(session_id, 'b' * 32, scope=scope)
                    if saved is not None:
                        state = adopt_receipt(state, saved)
                        current = store.save_session(session_id, state, current, lease, scope=scope)
                        barrier('adopted')
                    result = {'revision': current, 'turns': len(state['turns']),
                              'status': state['turns'][-1]['status'] if state['turns'] else 'empty',
                              'receiptAdopted': state['attempts'].get('b' * 32, {}).get('receiptAdopted', False)}
        channel.send(result)
    except BaseException as exc:
        channel.send({'error': exc.code if isinstance(exc, StoreError) else type(exc).__name__,
                      'outcomeUnknown': bool(getattr(exc, 'outcome_unknown', False))})
    finally:
        channel.close()


class SessionWorker:
    def __init__(self, dsn, session_id, command, *, edge=None, revision=None, operation_timeout_s=10):
        ctx = multiprocessing.get_context('spawn')
        self.ready, self.release = ctx.Event(), ctx.Event()
        self.channel, child = ctx.Pipe(duplex=False)
        self.process = ctx.Process(target=run_worker, args=(dsn, session_id, command,
            edge, self.ready, self.release, child, revision, operation_timeout_s))
    def __enter__(self):
        self.process.start()
        return self
    def failure(self):
        return self.channel.recv() if self.channel.poll() else 'worker did not reach expected edge'
    def result(self, *, allow_error=False):
        assert self.channel.poll(15), 'worker exceeded execution bound'
        result = self.channel.recv()
        self.process.join(3)
        assert not self.process.is_alive(), 'worker did not drain'
        assert allow_error or 'error' not in result, result
        return result
    def kill(self):
        if self.process.is_alive():
            self.process.kill()
        self.process.join(3)
        assert not self.process.is_alive()
    def __exit__(self, *args):
        self.kill()
        self.channel.close()
