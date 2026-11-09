"""Closed pack data uses the controller's existing canonical UTF-8 codec."""
from .. import session_codec


CODES = frozenset({'invalidContextPack', 'contextScopeMismatch', 'contextBindingMismatch',
    'requiredContextMissing', 'selectionLimit', 'contextSnapshotLimit', 'contextPackLimit',
    'contextCapabilityMissing', 'contextUseDenied', 'contextSnapshotUnavailable'})


class ContextPackError(ValueError):
    def __init__(self, code='invalidContextPack'):
        if type(code) is not str or code not in CODES:
            raise ValueError('invalid context error code')
        self.code = code
        super().__init__(code)


def encode(value, **limits):
    try:
        return session_codec.encode(value, **limits)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ContextPackError() from None


def decode(content, **limits):
    try:
        if type(content) is not bytes:
            raise ValueError('JSON bytes')
        content.decode('utf-8', errors='strict')
        return session_codec.decode(content, **limits)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ContextPackError() from None


def digest(value):
    import hashlib
    return hashlib.sha256(encode(value)).hexdigest()


def reference(value, maximum=128):
    try:
        return session_codec.reference(value, maximum)
    except (ValueError, TypeError, UnicodeError):
        raise ContextPackError() from None


def closed(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ContextPackError()


def integer(value, minimum=0, maximum=2**63-1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContextPackError()
    return value


def pointer(value):
    if type(value) is not str or (value and not value.startswith('/')):
        raise ContextPackError()
    encode(value, maximum=8192)
    import re
    if re.search(r'~(?![01])', value):
        raise ContextPackError()
    return value


def locator(value, *, representation=False):
    if value is None or value == 'whole':
        return {'kind': 'whole'}
    if type(value) is not dict or type(value.get('kind')) is not str:
        raise ContextPackError()
    kind = value['kind']
    if kind == 'whole':
        closed(value, {'kind'})
    elif kind == 'utf8Range':
        closed(value, {'kind', 'start', 'end'})
        integer(value['start']); integer(value['end'], value['start'])
    elif kind == 'jsonPointer':
        closed(value, {'kind', 'pointer'})
        pointer(value['pointer'])
    elif kind == 'record' and not representation:
        closed(value, {'kind', 'id'})
        reference(value['id'])
    else:
        raise ContextPackError()
    return decode(encode(value, maximum=8192))
