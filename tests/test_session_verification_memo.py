"""A session verified once is not verified again for the same canonical content.

The memo is keyed by the sha256 of the canonical encoding of the whole document, so any change, including a
change that keeps a stale seal, is a different key and is verified in full. Only successes are kept.
"""

import pytest
from prosaic_harness import StoreCorrupt
from prosaic_harness import session_contracts
from prosaic_harness.session_contracts import mark_dispatch, new_session, reserve_attempt, seal, verify_session
from support.conversations import binding_factory, scope  # noqa: F401 (fixtures)

SID = 'a' * 32
AID = 'b' * 32


@pytest.fixture
def state(scope, binding_factory):
    session_contracts.clear_verified_sessions()
    return new_session(SID, scope, binding_factory())


@pytest.fixture
def full_checks(monkeypatch):
    """Counts full verifications: `_bounds` runs once at the end of every one that succeeds."""
    calls = []
    original = session_contracts._bounds

    def counted(state, **options):
        calls.append(1)
        return original(state, **options)

    monkeypatch.setattr(session_contracts, '_bounds', counted)
    return calls


def running(state):
    pending = reserve_attempt(state, message_id='message', message='Hello', invocation_id=AID,
        context_identity='1' * 64, encoding_version='conversation-turn-v1', input_bytes=500,
        provider_allowance=2, tool_allowance=0)
    return mark_dispatch(pending, AID)


def test_same_content_is_verified_once_and_returned_as_a_fresh_copy(state, full_checks):
    document = running(state)
    session_contracts.clear_verified_sessions()
    full_checks.clear()
    first = verify_session(document)
    again = verify_session(dict(document))  # another object, the same content
    assert full_checks == [1]
    assert first == again == document
    assert first is not again and first is not document
    first['turns'][0]['message'] = 'changed by a caller'
    assert verify_session(document)['turns'][0]['message'] == 'Hello'  # the memo is not shared state


def test_changed_content_is_verified_in_full(state, full_checks):
    document = running(state)
    verify_session(document)
    full_checks.clear()
    changed = seal(document | {'bindingVersion': 'v2'})
    assert verify_session(changed)['bindingVersion'] == 'v2'
    assert full_checks == [1]


def test_a_stale_seal_is_refused_after_the_original_was_verified(state):
    document = running(state)
    verify_session(document)
    hostile = {**document, 'bindingVersion': 'v2'}  # the old seal kept
    with pytest.raises(StoreCorrupt):
        verify_session(hostile)


def test_failures_are_not_remembered(state, monkeypatch):
    document = running(state)
    hostile = {**document, 'bindingVersion': 'v2'}
    attempts = []
    original = session_contracts.verify_seal

    def counted(value):
        attempts.append(1)
        return original(value)

    monkeypatch.setattr(session_contracts, 'verify_seal', counted)
    for _ in range(2):
        with pytest.raises(StoreCorrupt):
            verify_session(hostile)
    assert len(attempts) == 2


def test_non_json_input_is_refused_as_before(state):
    with pytest.raises(StoreCorrupt):
        verify_session({**state, 'turns': ({},)})  # a tuple is not JSON
    with pytest.raises(StoreCorrupt):
        verify_session('not a session')


def test_the_memo_is_bounded_by_bytes(state, monkeypatch, full_checks):
    document = running(state)
    monkeypatch.setattr(session_contracts, 'VERIFIED_SESSION_BYTES', 1)  # holds no entry
    session_contracts.clear_verified_sessions()
    full_checks.clear()
    verify_session(document)
    verify_session(document)
    assert full_checks == [1, 1]


def test_the_oldest_entry_leaves_first(state, monkeypatch, full_checks):
    first, second = state, running(state)
    size = len(session_contracts.encode(second))
    monkeypatch.setattr(session_contracts, 'VERIFIED_SESSION_BYTES', size + len(session_contracts.encode(first)) - 1)
    session_contracts.clear_verified_sessions()
    verify_session(first)
    verify_session(second)  # the budget holds one of them: `first` leaves
    full_checks.clear()
    verify_session(second)
    assert full_checks == []
    verify_session(first)
    assert full_checks == [1]
