"""Root-isolated schema admission and safe, bounded evaluation diagnostics.

Approved schemas remain trusted host assets: byte/work limits and acyclic static
references do not provide a CPU sandbox for regular expressions or combinators.
Legacy evaluation retains Draft202012Validator's recursive/dialect semantics.
"""
from collections.abc import Mapping
from itertools import islice
from urllib.parse import urljoin, urldefrag, unquote

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from .admission_data import snapshot_json
from .errors import WorkflowAdmissionError


class SchemaEvaluationError(ValueError):
    """The evaluator could not finish; this is not an invalid output instance."""
    code = 'schema_error'

    def __init__(self):
        super().__init__('schema evaluation failed')


_PROFILE_KEYS = frozenset({'version', 'dialect', 'refs', 'maximum_depth',
                           'maximum_nodes', 'maximum_schema_bytes', 'maximum_instance_bytes'})
_DIALECTS = frozenset({'https://json-schema.org/draft/2020-12/schema',
                       'https://json-schema.org/draft/2020-12/schema#'})
_SINGLE_SCHEMAS = ('if', 'items', 'else', 'unevaluatedItems', 'additionalProperties',
                   'not', 'then', 'unevaluatedProperties', 'contains', 'propertyNames', 'contentSchema')
_ARRAY_SCHEMAS = ('oneOf', 'anyOf', 'allOf', 'prefixItems')
_MAPPING_SCHEMAS = ('patternProperties', 'dependentSchemas', 'definitions', 'properties', '$defs')


def _invalid_schema():
    raise WorkflowAdmissionError('invalid_schema') from None


def _check_profile(profile):
    if (not isinstance(profile, Mapping) or set(profile) != _PROFILE_KEYS
            or type(profile['version']) is not int or profile['version'] != 1
            or profile['dialect'] != '2020-12' or profile['refs'] != 'acyclic-local-static'
            or any(type(profile[key]) is not int or profile[key] <= 0
                   for key in _PROFILE_KEYS if key.startswith('maximum_'))):
        _invalid_schema()


def _legacy_admit(schema):
    # Match the released YAML scan, including ref-like fields in literal JSON.
    jobs = [schema]
    seen = set()
    while jobs:
        value = jobs.pop()
        if isinstance(value, (dict, list)):
            if id(value) in seen:
                continue
            seen.add(id(value))
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {'$ref', '$dynamicRef'} and (
                            not isinstance(child, str) or not child.startswith('#')):
                        _invalid_schema()
                jobs.extend(value.values())
            else:
                jobs.extend(value)
    Draft202012Validator.check_schema(schema)
    return schema


def _acyclic(edges):
    """Check containment plus static-reference edges without recursive DFS."""
    colors = {}
    for start in edges:
        if colors.get(start):
            continue
        colors[start] = 1
        jobs = [(start, iter(edges[start]))]
        while jobs:
            node, children = jobs[-1]
            try:
                child = next(children)
            except StopIteration:
                colors[node] = 2
                jobs.pop()
                continue
            if colors.get(child) == 1:
                _invalid_schema()
            if not colors.get(child):
                colors[child] = 1
                jobs.append((child, iter(edges[child])))


def _children(contents):
    """Draft 2020-12 positions, retaining paths even for singleton bool schemas."""
    if type(contents) is not dict:
        return
    for key in _SINGLE_SCHEMAS:
        if key in contents:
            yield (key,), contents[key]
    for key in _ARRAY_SCHEMAS:
        if key in contents:
            for index, child in enumerate(contents[key]):
                yield (key, index), child
    for key in _MAPPING_SCHEMAS:
        if key in contents:
            for name, child in contents[key].items():
                yield (key, name), child


def _reference_position(ref, base, resources, anchors, nodes):
    if ref.startswith('#'):
        uri, fragment = base, ref[1:]
    else:
        uri, fragment = urldefrag(urljoin(base, ref))
    if not fragment:
        return resources.get(uri)
    if not fragment.startswith('/'):
        return anchors.get((uri, fragment))
    position = resources.get(uri)
    if position is None:
        return None
    contents = nodes[position][0]
    for segment in unquote(fragment[1:]).split('/'):
        segment = segment.replace('~1', '/').replace('~0', '~')
        key = int(segment) if type(contents) is list else segment
        contents = contents[key]
        position += (key,)
    return position


def _prepare(schema, profile):
    _check_profile(profile)
    try:
        owned = snapshot_json(schema, maximum_bytes=profile['maximum_schema_bytes'],
                              maximum_depth=profile['maximum_depth'],
                              maximum_nodes=profile['maximum_nodes'])
    except WorkflowAdmissionError as error:
        if error.code == 'limit_exceeded':
            raise
        _invalid_schema()
    Draft202012Validator.check_schema(owned)
    root = DRAFT202012.create_resource(owned)
    root_uri = root.id() or ''
    # Establish ambiguity checks before Registry.crawl can overwrite collisions.
    resources = {root_uri: ()}
    anchors = {}
    nodes = {}
    edges = {}
    jobs = [(root, root_uri, (), True)]
    while jobs:
        resource, base, position, is_root = jobs.pop()
        contents = resource.contents
        if type(contents) is dict:
            if '$schema' in contents and contents['$schema'] not in _DIALECTS:
                _invalid_schema()
            if '$dynamicRef' in contents:
                _invalid_schema()
            declared = resource.id()
            if declared is not None and not is_root:
                base = urldefrag(urljoin(base, declared))[0]
                if base in resources:
                    _invalid_schema()
                resources[base] = position
            for field in ('$anchor', '$dynamicAnchor'):
                if field in contents:
                    key = (base, contents[field])
                    if key in anchors:
                        _invalid_schema()
                    anchors[key] = position
        nodes[position] = (contents, base)
        children = list(_children(contents))
        edges[position] = {position + path for path, child in children}
        jobs.extend((DRAFT202012.create_resource(child), base, position + path, False)
                    for path, child in children)

    # The empty Registry has no retrieval implementation. Each schema root owns
    # its resources; sibling schemas and global metaschemas cannot satisfy refs.
    # Register at the document's initial empty base. Crawling applies its $id
    # once; registering a relative root $id as the initial base would apply it
    # twice and move nested resources/anchors into a different URI scope.
    registry = Registry().with_resource('', root).crawl()
    for position, (contents, base) in nodes.items():
        if type(contents) is dict and '$ref' in contents:
            resolved = registry.resolver(base).lookup(contents['$ref'])
            target = _reference_position(contents['$ref'], base, resources, anchors, nodes)
            # Only declared schema positions are executable under this profile;
            # pointers cannot promote ignored const/enum/examples data to schemas.
            if type(resolved.contents) not in (dict, bool) or target not in nodes:
                _invalid_schema()
            edges[position].add(target)
    _acyclic(edges)
    return owned, registry


def admit_schema(schema, *, profile):
    """Admit a schema, returning an owned snapshot on the versioned native path.

    profile=None preserves released YAML admission/reference behavior without
    new tree caps; the YAML adapter already owns its freshly parsed schema.
    """
    try:
        return _legacy_admit(schema) if profile is None else _prepare(schema, profile)[0]
    except WorkflowAdmissionError:
        raise
    except Exception:
        _invalid_schema()


def _issue(error):
    location = '$'
    for part in error.path:
        location += f'[{part}]' if type(part) is int else '.*'
        if len(location) > 128:
            location = location[:128]
            break
    validator = error.validator
    name = validator if type(validator) is str and validator in Draft202012Validator.VALIDATORS else 'schema'
    return f'{location}: {name} validation failed'[:256]


def evaluate_schema(schema, instance, *, profile=None, max_errors=5):
    """Return safe bounded invalid-instance issues, or raise an evaluator failure.

    Legacy instances receive no newly introduced byte, depth or node caps.
    No format checker, custom resolver, filesystem or remote retrieval is used.
    """
    if type(max_errors) is not int or max_errors <= 0:
        raise ValueError('max_errors must be a positive integer')
    if profile is not None:
        try:
            schema, registry = _prepare(schema, profile)
        except Exception:
            raise SchemaEvaluationError() from None
        # Data-limit admission errors remain distinct from evaluator failures so
        # the engine can persist an output/input limit outcome, not schema_error.
        instance = snapshot_json(instance, maximum_bytes=profile['maximum_instance_bytes'],
                                 maximum_depth=profile['maximum_depth'],
                                 maximum_nodes=profile['maximum_nodes'])
    else:
        registry = Registry()
    try:
        validator = Draft202012Validator(schema, registry=registry)
        return [_issue(error) for error in islice(validator.iter_errors(instance), max_errors)]
    except Exception:
        raise SchemaEvaluationError() from None
