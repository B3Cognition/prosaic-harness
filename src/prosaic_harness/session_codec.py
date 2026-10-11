"""One finite canonical UTF-8 encoding for all new conversation contracts."""
import hashlib
import json
import math
import unicodedata


def reference(value, maximum=128):
    if (type(value) is not str or not value or len(value.encode('utf-8')) > maximum
            or any(unicodedata.category(c) in {'Cc', 'Cf', 'Cs'} for c in value)):
        raise ValueError('invalid logical reference')
    return value


def encode(value, *, maximum=8_388_608, depth=64, nodes=65_536):
    stack = [(value, 0, frozenset())]
    count = text_bytes = 0
    while stack:
        item, level, ancestors = stack.pop()
        count += 1
        if count > nodes:
            raise ValueError('JSON node limit')
        kind = type(item)
        if kind in (dict, list):
            if level >= depth or id(item) in ancestors or len(item) + count > nodes:
                raise ValueError('JSON structure limit')
            parents = ancestors | {id(item)}
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        raise ValueError('JSON key type')
                    text_bytes += len(key.encode('utf-8'))
                    stack.append((child, level + 1, parents))
            else:
                stack.extend((child, level + 1, parents) for child in item)
        elif kind is str:
            text_bytes += len(item.encode('utf-8'))
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError('nonfinite JSON')
        elif kind is int:
            if item.bit_length() > 4096:
                raise ValueError('JSON integer limit')
        elif kind not in (bool, type(None)):
            raise ValueError('JSON type')
        if text_bytes > maximum:
            raise ValueError('JSON byte limit')
    result = json.dumps(value, ensure_ascii=False, sort_keys=True,
                        separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(result) > maximum:
        raise ValueError('JSON byte limit')
    return result


def unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key')
        value[key] = item
    return value


def decode(content, **limits):
    if type(content) is not bytes or len(content) > limits.get('maximum', 8_388_608):
        raise ValueError('JSON bytes')
    try:
        value = json.loads(content, object_pairs_hook=unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        encode(value, **limits)
        return value
    except (RecursionError, UnicodeError):
        raise ValueError('JSON structure') from None


def owned(value, **limits):
    return decode(encode(value, **limits), **limits)


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def node_count(value):
    # Call only after finite canonical admission; count occurrences, not aliases.
    stack=[value]
    count=0
    while stack:
        child=stack.pop()
        count+=1
        if type(child) is dict: stack.extend(child.values())
        elif type(child) is list: stack.extend(child)
        if count>65_536: raise ValueError('JSON node limit')
    return count
