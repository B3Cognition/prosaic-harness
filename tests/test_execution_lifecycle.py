import threading

import pytest
from prosaic_runtime import Draining, ExecutionLifecycle
from prosaic_harness import Harness
from test_harness import FakeRuntime, setup
from support.conversation_host import conversation_fixture  # noqa: F401


def test_harness_drain_includes_final_checkpoint_and_rejects_resume(tmp_path, monkeypatch):
    runtime = FakeRuntime(['{"approved":true}'])
    runtime.lifecycle = ExecutionLifecycle()
    harness = Harness(setup(tmp_path, monkeypatch), tmp_path/'run', runtime=runtime)
    assert harness.lifecycle is runtime.lifecycle
    save = harness._save
    entered, release = threading.Event(), threading.Event()
    def delayed(state):
        if state['status'] == 'completed':
            entered.set()
            assert release.wait(5)
        return save(state)
    monkeypatch.setattr(harness, '_save', delayed)
    errors = []
    def run():
        try: harness.run({})
        except BaseException as exc: errors.append(exc)
    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(5)
    assert not harness.lifecycle.wait(timeout=.01)
    with pytest.raises(Draining): harness.resume()
    release.set()
    worker.join(5)
    assert not errors and not worker.is_alive()
    assert harness.lifecycle.wait(timeout=1)
    assert harness.status().state['status'] == 'completed'
    # New instance after restart uses stored completion, with no provider retry.
    replay = Harness(harness.workflow, tmp_path/'run', runtime=FakeRuntime([]))
    assert replay.resume()['status'] == 'completed'
    assert not replay.runtime.calls


def test_lifecycle_refuses_mismatched_runtime_scope(tmp_path, monkeypatch):
    runtime = FakeRuntime([])
    runtime.lifecycle = ExecutionLifecycle()
    with pytest.raises(ValueError, match='share'):
        Harness(setup(tmp_path, monkeypatch), tmp_path/'run', runtime=runtime,
                lifecycle=ExecutionLifecycle())


def test_conversation_drain_waits_through_committed_turn_and_lease_cleanup(conversation_fixture):  # noqa: F811
    with conversation_fixture() as fx:
        initial = fx.controller.create()
        fx.queue_text('Saved')
        entered, release = threading.Event(), threading.Event()
        errors = []
        def observe(event):
            if event['event'] == 'turnCommitted':
                entered.set()
                assert release.wait(5)
        def send():
            try:
                fx.controller.send(initial.session_id, message_id='drain', message='Hello',
                    expected_revision=initial.revision, on_event=observe)
            except BaseException as exc: errors.append(exc)
        worker = threading.Thread(target=send)
        worker.start()
        assert entered.wait(5)
        assert not fx.controller.lifecycle.wait(timeout=.01)
        with pytest.raises(Draining):
            fx.controller.send(initial.session_id, message_id='new', message='Hello',
                expected_revision=initial.revision)
        release.set()
        worker.join(5)
        assert not errors and not worker.is_alive()
        assert fx.controller.lifecycle.wait(timeout=1)
        assert fx.fresh_controller().status(initial.session_id).document['answer'] == 'Saved'
        assert fx.provider_calls == 1


def test_default_runtime_uses_supplied_lifecycle(tmp_path, monkeypatch):
    gate = ExecutionLifecycle()
    harness = Harness(setup(tmp_path, monkeypatch), tmp_path/'run', lifecycle=gate)
    assert harness.lifecycle is harness.runtime.lifecycle is gate
    gate.begin()
    with pytest.raises(Draining): harness.run({})
