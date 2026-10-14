"""Recovery adopts receipts or frozen selection, never a new omission search."""
import pytest
from prosaic_harness import StoreUnavailable
from support.conversation_host import context_host, conversation_fixture


class Crash(BaseException):
    pass


@pytest.mark.parametrize('kind', ['memory', 'file'])
def test_explicit_retry_gets_fresh_work_without_changing_selection(context_host, kind):
    with context_host(kind=kind, checks=2) as fx:
        def crash(event):
            if event['event'] == 'turnAdmitted': raise Crash()
        with pytest.raises(Crash): fx.send(on_event=crash)
        recovered = fx.controller.recover(fx.session.session_id).document
        assert recovered['status'] == 'needsResolution'
        before = fx.store.load_session(fx.session.session_id, scope=fx.scope).state
        original = next(iter(before['attempts'].values()))
        assert original['contextWork']['candidateChecks'] == 2
        fx.queue_text('done')
        retried = fx.controller.retry_interrupted(fx.session.session_id,
            expected_revision=recovered['revision'], acknowledge_effect_risk=True).document
        assert retried['status'] == 'completed'
        assert fx.provider_calls == 1 and len(fx.counts) == 3
        after = fx.store.load_session(fx.session.session_id, scope=fx.scope).state
        assert len(after['attempts']) == 2
        assert all(attempt['contextSelection'] == original['contextSelection']
                   for attempt in after['attempts'].values())


def test_unknown_checkpoint_ack_retains_reservation_and_fails_without_dispatch(context_host):
    with context_host() as fx:
        fx.store.fail_phase = 'checkpoint'
        with pytest.raises(StoreUnavailable): fx.send()
        assert fx.provider_calls == 0 and len(fx.counts) == 1
        reply = fx.fresh_controller().recover(fx.session.session_id).document
        assert reply['status'] == 'failed'
        assert reply['failureCode'] == 'contextLimit'
        assert fx.provider_calls == 0 and len(fx.counts) == 1


@pytest.mark.parametrize('kind', ['memory', 'file'])
def test_saved_receipt_adoption_never_recounts_or_redispatches(context_host, kind):
    with context_host(kind=kind) as fx:
        fx.queue_text('done')
        def crash(event):
            if event['event'] == 'receiptSaved': raise Crash()
        with pytest.raises(Crash): fx.send(on_event=crash)
        assert fx.provider_calls == 1 and len(fx.counts) == 2
        recovered = fx.fresh_controller().recover(fx.session.session_id).document
        assert recovered['status'] == 'completed'
        assert fx.fresh_controller().recover(fx.session.session_id).document == recovered
        assert fx.provider_calls == 1 and len(fx.counts) == 2


def test_crash_inside_counter_keeps_reserved_slice_for_recovery(context_host):
    def counter(request, number):
        if number == 2: raise Crash()
        return 10
    with context_host(count=counter) as fx:
        with pytest.raises(Crash): fx.send()
        state = fx.store.load_session(fx.session.session_id, scope=fx.scope).state
        attempt = next(iter(state['attempts'].values()))
        assert attempt['contextWork']['reservedActiveMicros'] > 0
        assert attempt['dispatchMarker'] is False
        recovered = fx.fresh_controller().recover(fx.session.session_id).document
        assert recovered['failureCode'] == 'contextLimit'
        assert fx.provider_calls == 0 and len(fx.counts) == 2


def test_crash_before_first_checkpoint_reuses_frozen_omission_without_search(context_host):
    import json
    def counter(request, number):
        text = json.dumps(request)
        return 181 if 'old-marker' in text and 'third-marker' in text else 10
    with context_host(mode='omitOldestTurns', count=counter) as fx:
        for text in ('old-marker', 'recent-marker'):
            fx.queue_text('done')
            fx.send(text)
        def crash(before, after):
            for aid, attempt in after['attempts'].items():
                if aid in before['attempts'] and attempt['contextWork']['reservedActiveMicros'] > 0:
                    fx.store.before_save = None
                    raise Crash()
        fx.store.before_save = crash
        fx.queue_text('done')
        with pytest.raises(Crash): fx.send('third-marker')
        state = fx.store.load_session(fx.session.session_id, scope=fx.scope).state
        aid = state['pending']['invocationId']
        frozen = state['attempts'][aid]['contextSelection']
        counted = len(fx.counts)
        recovered = fx.fresh_controller().recover(fx.session.session_id).document
        assert recovered['status'] == 'completed'
        assert recovered['contextAssembly']['omittedTurnCount'] == 1
        assert len(fx.counts) == counted + 1
        after = fx.store.load_session(fx.session.session_id, scope=fx.scope).state
        assert after['attempts'][aid]['contextSelection'] == frozen
        assert fx.provider_calls == 3


def test_crash_after_counter_before_reconciliation_keeps_full_reserved_slice(context_host):
    with context_host() as fx:
        def crash(before, after):
            for aid, attempt in after['attempts'].items():
                old = before['attempts'].get(aid)
                if (old is not None and old['contextWork']['reservedActiveMicros'] > 0
                        and attempt['contextWork']['reservedActiveMicros'] == 0
                        and attempt['contextWork']['candidateChecks'] == 2):
                    fx.store.before_save = None
                    raise Crash()
        fx.store.before_save = crash
        with pytest.raises(Crash): fx.send()
        assert len(fx.counts) == 2 and fx.provider_calls == 0
        recovered = fx.fresh_controller().recover(fx.session.session_id).document
        assert recovered['failureCode'] == 'contextLimit'
        assert len(fx.counts) == 2 and fx.provider_calls == 0
