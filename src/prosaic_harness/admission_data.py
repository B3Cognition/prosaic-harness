"""Bound plain JSON before copying, encoding, hashing, or recursive consumers."""
import json
import math

from .errors import WorkflowAdmissionError


def _bounds(maximum_bytes, maximum_depth, maximum_nodes):
    if any(type(v) is not int or v <= 0 for v in
           (maximum_bytes, maximum_depth, maximum_nodes)):
        raise ValueError('JSON bounds must be positive integers')


def _fail(code='invalid_definition'):
    raise WorkflowAdmissionError(code) from None


def _string_size(value, remaining):
    """Default json.dumps string size, without allocating an escaped copy."""
    size = 2
    for char in value:
        point = ord(char)
        if 0xD800 <= point <= 0xDFFF:
            _fail()
        size += (2 if char in '\"\\\b\f\n\r\t' else
                 6 if point < 32 or 127 <= point <= 0xFFFF else
                 12 if point > 0xFFFF else 1)
        if size > remaining:
            _fail('limit_exceeded')
    return size


def _preflight(value, maximum_bytes, maximum_depth, maximum_nodes):
    size = nodes = 0
    active = set()
    jobs = [('value', value, 0)]

    def add(amount):
        nonlocal size
        size += amount
        if size > maximum_bytes:
            _fail('limit_exceeded')

    while jobs:
        job = jobs.pop()
        if job[0] == 'items':
            _, identity, iterator, level, mapping, index = job
            try:
                item = next(iterator)
            except StopIteration:
                active.remove(identity)
                continue
            if index:
                add(2)  # comma and space
            if mapping:
                key, child = item
                if type(key) is not str:
                    _fail()
                add(_string_size(key, maximum_bytes - size))
                add(2)  # colon and space
            else:
                child = item
            jobs.append(('items', identity, iterator, level, mapping, index + 1))
            jobs.append(('value', child, level))
            continue
        _, child, level = job
        nodes += 1
        if nodes > maximum_nodes:
            _fail('limit_exceeded')
        kind = type(child)
        if kind in (dict, list):
            identity = id(child)
            if identity in active:
                _fail()
            level += 1
            if level > maximum_depth:
                _fail('limit_exceeded')
            add(2)
            active.add(identity)
            jobs.append(('items', identity, iter(child.items() if kind is dict else child),
                         level, kind is dict, 0))
        elif kind is str:
            add(_string_size(child, maximum_bytes - size))
        elif child is None:
            add(4)
        elif kind is bool:
            add(4 if child else 5)
        elif kind is int:
            if child.bit_length() > maximum_bytes * 4:
                _fail('limit_exceeded')
            add(len(str(child)))
        elif kind is float and math.isfinite(child):
            add(len(json.dumps(child)))
        else:
            _fail()


def _clone(value):
    """Expand admitted sharing into independently owned containers, iteratively."""
    root = [None]
    jobs = [('value', value, root, 0)]
    while jobs:
        job = jobs.pop()
        if job[0] == 'items':
            _, iterator, destination, mapping = job
            try:
                item = next(iterator)
            except StopIteration:
                continue
            jobs.append(job)
            if mapping:
                key, child = item
            else:
                key, child = len(destination), item
                destination.append(None)
            jobs.append(('value', child, destination, key))
            continue
        _, child, parent, key = job
        if type(child) in (dict, list):
            destination = {} if type(child) is dict else []
            parent[key] = destination
            jobs.append(('items', iter(child.items() if type(child) is dict else child),
                         destination, type(child) is dict))
        else:
            parent[key] = child
    return root[0]


def snapshot_json(value, *, maximum_bytes, maximum_depth=64, maximum_nodes=65536):
    """Return owned finite JSON, bounded by expanded values and default encoding.

    Container depth includes the root container. Nodes count every expanded JSON
    value, including containers, but not object keys. Benign sharing is accepted;
    cycles and amplification are rejected before making a copy.
    """
    _bounds(maximum_bytes, maximum_depth, maximum_nodes)
    try:
        _preflight(value, maximum_bytes, maximum_depth, maximum_nodes)
        return _clone(value)
    except WorkflowAdmissionError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError, RuntimeError):
        _fail()


def _raw_depth(text, maximum_depth):
    level = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            level += 1
            if level > maximum_depth:
                _fail('limit_exceeded')
        elif char in ']}':
            level -= 1


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            _fail()
        result[key] = value
    return result


def parse_bounded_json(text, *, maximum_bytes, maximum_depth=64, maximum_nodes=65536,
                       maximum_snapshot_bytes=None):
    """Decode strict UTF-8 JSON with transport bounds before the JSON decoder."""
    _bounds(maximum_bytes, maximum_depth, maximum_nodes)
    snapshot_bytes = maximum_bytes if maximum_snapshot_bytes is None else maximum_snapshot_bytes
    _bounds(snapshot_bytes, maximum_depth, maximum_nodes)
    try:
        if type(text) is bytes:
            if len(text) > maximum_bytes:
                _fail('limit_exceeded')
            text = text.decode('utf-8')
        elif type(text) is str:
            # UTF-8 transport size, without first allocating a potentially huge copy.
            size = 0
            for char in text:
                point = ord(char)
                if 0xD800 <= point <= 0xDFFF:
                    _fail()
                size += 1 if point < 128 else 2 if point < 2048 else 3 if point < 65536 else 4
                if size > maximum_bytes:
                    _fail('limit_exceeded')
        else:
            _fail()
        _raw_depth(text, maximum_depth)
        decoded = json.loads(text, object_pairs_hook=_pairs,
                             parse_constant=lambda _: _fail())
        return snapshot_json(decoded, maximum_bytes=snapshot_bytes,
                             maximum_depth=maximum_depth, maximum_nodes=maximum_nodes)
    except WorkflowAdmissionError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        _fail()
