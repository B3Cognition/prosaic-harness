"""Records and bindings read back bytes they encoded themselves without admitting them again.

Admission (the canonical walk in `session_codec.encode`) happens when the bytes are written. A read returns a fresh,
caller-owned copy each time, so immutability is unchanged; it only stops re-walking the document on every access.
"""
import pytest
from prosaic_harness import session_codec
from prosaic_harness.context_packs.types import ContextScope
from support.conversations import binding_factory, scope  # noqa: F401 (fixtures)


@pytest.fixture
def admissions(monkeypatch):
    """Counts canonical admission walks, wherever the codec is reached from."""
    calls = []
    original = session_codec.encode

    def counted(value, **limits):
        calls.append(1)
        return original(value, **limits)

    monkeypatch.setattr(session_codec, 'encode', counted)
    return calls


def record():
    return ContextScope('test', 'sandbox', 'app', 'tenant', 'actor')


def test_a_record_is_admitted_when_written_and_not_on_each_read(admissions):
    value = record()
    written = len(admissions)
    assert written >= 1
    assert value.namespace == 'test' and value.actor == 'actor'
    assert value.to_dict()['tenant'] == 'tenant'
    assert len(admissions) == written


def test_each_read_of_a_record_is_a_fresh_copy():
    value = record()
    first, second = value.to_dict(), value.to_dict()
    assert first == second and first is not second
    first['namespace'] = 'changed by a caller'
    assert value.namespace == 'test' and value.to_dict()['namespace'] == 'test'
    assert value.identity == record().identity


def test_a_record_stays_immutable():
    value = record()
    with pytest.raises(AttributeError):
        value.namespace = 'other'
    with pytest.raises(AttributeError):
        value.missing_field


def test_bindings_do_not_admit_their_document_on_each_property_read(binding_factory, admissions):
    bindings = binding_factory()
    admissions.clear()
    assert bindings.version
    assert bindings.policy is not None and bindings.turn_limits is not None
    assert bindings.agent is not None
    assert admissions == []
    assert bindings.run_policy is not None  # copies its small sub-document (`owned`), never the whole binding
    assert len(admissions) <= 2


def test_bindings_properties_are_fresh_values_each_time(binding_factory):
    bindings = binding_factory()
    assert bindings.agent == bindings.agent and bindings.agent is not bindings.agent
    assert bindings.policy == bindings.policy
    assert bindings.identity == binding_factory().identity
