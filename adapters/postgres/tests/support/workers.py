"""Spawn-only public SDK workers; durable-edge stops are test wrappers only."""
import multiprocessing


class EdgeStore:
    def __init__(self, store, edge, ready, release):
        self.store, self.edge, self.ready, self.release = store, edge, ready, release

    def __getattr__(self, name):
        return getattr(self.store, name)

    def _wait(self, edge):
        if edge == self.edge:
            self.ready.set()
            if not self.release.wait(30):
                raise TimeoutError('test worker durable-edge bound exceeded')

    def create_run(self, run_id, state, lease):
        result = self.store.create_run(run_id, state, lease)
        self._wait('initial')
        return result

    def save_run(self, run_id, state, expected_revision, lease):
        result = self.store.save_run(run_id, state, expected_revision, lease)
        if state['pending'] is not None:
            self._wait('pending')
        elif state['status'] == 'completed':
            self._wait('completed')
        elif any(e['event'] == 'human_decision' for e in state['history']):
            self._wait('decision')
        elif state['current'] == 'approval' and state['status'] == 'running':
            self._wait('transition')
        return result

    def save_receipt(self, *args):
        result = self.store.save_receipt(*args)
        self._wait('receipt')
        return result


def run_worker(dsn, flow_path, run_id, command, edge, ready, release, channel, choice, revision, retry):
    from prosaic_harness import Harness, Workflow, StoreError
    from prosaic_harness_postgres import PostgresRunStore
    try:
        with PostgresRunStore(dsn, namespace='workers', operation_timeout_s=2) as store:
            h = Harness(Workflow.load(flow_path), store=EdgeStore(store, edge, ready, release), run_id=run_id)
            if command == 'start':
                result = h.run({'task': 'synthetic'})
                if edge == 'completed':
                    result = h.resume(choice='approve', expected_revision=h.status().revision)
            elif command == 'status':
                snapshot = h.status()
                result = {'state': snapshot.state, 'revision': snapshot.revision}
            else:
                result = h.resume(choice=choice, expected_revision=revision, retry_interrupted=retry)
        channel.send(result)
    except BaseException as exc:
        # No driver details, DSN or private model response in failed test output.
        channel.send({'error': exc.code if isinstance(exc, StoreError) else type(exc).__name__})
    finally:
        channel.close()


class Worker:
    def __init__(self, dsn, flow_path, run_id, command, *, edge=None, choice=None, revision=None, retry=False):
        ctx = multiprocessing.get_context('spawn')
        self.ready, self.release = ctx.Event(), ctx.Event()
        self.channel, child = ctx.Pipe(duplex=False)
        self.process = ctx.Process(target=run_worker, args=(dsn, str(flow_path), run_id, command,
            edge, self.ready, self.release, child, choice, revision, retry))

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
        # Never touch an Event after killing a waiter: its condition semaphore
        # may have been interrupted while held. All durable-edge workers are
        # deliberately killed; completed workers have already joined.
        self.kill()
        self.channel.close()
