"""Pure, bounded public authoring documents derived from host authority.

ALWAYS publish only explicitly public metadata and admitted logical capabilities.
NEVER infer descriptions from private prose or execute registrations or probes.
"""
from dataclasses import fields
import json
import re

from .admission_data import snapshot_json
from .errors import WorkflowAdmissionError
from .graph_admission import STEP_KEYS, LIMIT_KEYS
from prosaic_runtime.policy import requested_tools


ALIAS_PATTERN = r'^[A-Za-z][A-Za-z0-9_-]{0,63}(?![\s\S])'
HOST_BYTES = 8_388_608
CATEGORIES = ('agents', 'schemas', 'tools', 'validators')


def public_metadata(value, *, agents, schemas):
    owned = snapshot_json({} if value is None else value, maximum_bytes=HOST_BYTES,
                          maximum_depth=8, maximum_nodes=1_048_576)
    if type(owned) is not dict or set(owned) - set(CATEGORIES):
        raise WorkflowAdmissionError('invalid_definition')
    for category, entries in owned.items():
        if type(entries) is not dict:
            raise WorkflowAdmissionError('invalid_definition')
        known = agents if category == 'agents' else schemas if category == 'schemas' else None
        for alias, entry in entries.items():
            if (not re.fullmatch(ALIAS_PATTERN, alias) or known is not None and alias not in known
                    or type(entry) is not dict or set(entry) != {'description'}):
                raise WorkflowAdmissionError('invalid_definition')
            if 'description' in entry:
                description = entry['description']
                if type(description) is not str:
                    raise WorkflowAdmissionError('invalid_definition')
                if len(description.encode('utf-8')) > 4096:
                    raise WorkflowAdmissionError('limit_exceeded')
    return json.dumps(owned, sort_keys=True)


def _bounded(value, maximum_bytes):
    if type(maximum_bytes) is not int or maximum_bytes <= 0:
        raise ValueError('maximum_bytes must be a positive integer')
    return snapshot_json(value, maximum_bytes=min(maximum_bytes, HOST_BYTES),
                         maximum_depth=512, maximum_nodes=1_048_576)


def _selection(factory):
    policy = factory._policy
    config = json.loads(factory._config_json)
    selected = {
        'agents': sorted(policy.allowed_agents & factory._agents.keys()),
        'schemas': sorted(policy.allowed_schemas & factory._schemas.keys()),
        'tools': sorted(policy.allowed_tools & factory._tools.keys() & set(config['allowed_tools'])),
        'validators': sorted(policy.allowed_validators & factory._validators.keys()),
    }
    selected['modelTiers'] = sorted(policy.allowed_model_tiers & config['routes'].keys())
    return selected


def describe(factory, *, include_schemas=False, maximum_bytes=262_144):
    if type(include_schemas) is not bool:
        raise ValueError('include_schemas must be a boolean')
    policy = factory._policy
    selected = _selection(factory)
    metadata = json.loads(factory._public_metadata_json)
    registrations = json.loads(factory._discovery_json)
    document = {'version': 1}
    for category in CATEGORIES:
        aliases = selected[category]
        document[category] = {alias: dict(metadata.get(category, {}).get(alias, {})) for alias in aliases}
    for alias in selected['agents']:
        frontmatter = json.loads(factory._agents[alias])['frontmatter']
        try:
            requested = requested_tools(frontmatter.get('tools'))
        except ValueError:
            requested = frozenset()
        document['agents'][alias]['requestedCapabilities'] = {
            'tools': sorted(requested & set(selected['tools']))}
    for alias in selected['tools']:
        tool = registrations['tools'][alias]
        if not include_schemas:
            tool.pop('parameters')
        document['tools'][alias].update(tool)
    for alias in selected['validators']:
        document['validators'][alias].update(registrations['validators'][alias])
    if include_schemas:
        for alias in selected['schemas']:
            document['schemas'][alias]['schema'] = json.loads(factory._schemas[alias])
    document.update(stepKinds=list(STEP_KEYS), allowInlineAgents=policy.allow_inline_agents,
        allowAgentComposition=policy.allow_agent_composition,
        modelTiers=selected['modelTiers'],
        defaultModelTierAllowed=True,
        limits={_camel(item.name): getattr(policy, item.name) for item in fields(policy)
                if not item.name.startswith(('allow_', 'allowed_'))})
    return _bounded(document, maximum_bytes)


def _camel(value):
    head, *rest = value.split('_')
    return head + ''.join(part.capitalize() for part in rest)


def _enum(values):
    values = sorted(values)
    return {'type': 'string', 'enum': values} if values else False


def _names(item, *, unique=False, minimum=0):
    return {'type': 'array', 'items': item, 'minItems': minimum, **({'uniqueItems': True} if unique else {})}


def proposal_schema(factory, *, maximum_bytes=262_144):
    manifest = _selection(factory)
    policy = factory._policy
    alias = {'type': 'string', 'pattern': ALIAS_PATTERN}
    reference = {'type': 'string', 'minLength': 1}
    agent_ref = (alias if policy.allow_inline_agents else _enum(manifest['agents']))
    schema_ref = _enum(manifest['schemas'])
    tools = _names(_enum(manifest['tools']))
    validators = _names(_enum(manifest['validators']), unique=True)
    positive = lambda cap: {'type': 'integer', 'minimum': 1, 'maximum': cap}
    shapes = {
        'kind': {}, 'agent': agent_ref, 'schema': schema_ref,
        'inputs': _names(reference), 'optional_inputs': _names(reference), 'next': reference,
        'max_attempts': positive(policy.max_attempts), 'max_visits': positive(policy.max_visits),
        'tools': tools, 'require_tools': tools, 'validators': validators,
        'from': reference, 'field': _names({'type': 'string'}, minimum=1),
        'equals': {}, 'pass': reference, 'fail': reference,
        'question': {'type': 'string', 'minLength': 1},
        'choices': {'type': 'object', 'minProperties': 1,
                    'propertyNames': {'minLength': 1}, 'additionalProperties': reference},
        'requires': _names(reference), 'response_schema': schema_ref,
        'outcome': {'enum': ['completed', 'rejected']},
    }
    required = {'agent': ['agent', 'schema', 'next'], 'gate': ['from', 'field', 'equals', 'pass', 'fail'],
                'check': ['from', 'validators', 'pass', 'fail'], 'pause': ['question', 'choices'], 'finish': []}
    branches = []
    for kind, keys in STEP_KEYS.items():
        properties = {key: shapes[key] for key in sorted(keys - {'acquisition', 'read_roots', 'require_reads'})}
        properties['kind'] = {'const': kind}
        if kind == 'check':
            properties['validators'] = _names(_enum(manifest['validators']), unique=True, minimum=1)
        branch = {'type': 'object', 'additionalProperties': False,
                  'required': ['kind', *required[kind]], 'properties': properties}
        if kind == 'pause':
            branch.update({'if': {'required': ['validators'],
                'properties': {'validators': {'minItems': 1}}}, 'then': {'required': ['response_schema']}})
        branches.append(branch)
    definition_schema = {'type': 'object', 'additionalProperties': False,
        'required': ['version', 'start', 'steps'], 'properties': {
            'version': {'const': 1, 'type': 'integer'}, 'name': {}, 'start': reference,
            'limits': {'type': 'object', 'additionalProperties': False,
                       'properties': {key: positive(getattr(policy, key)) for key in sorted(LIMIT_KEYS)}},
            'steps': {'type': 'object', 'minProperties': 1, 'maxProperties': policy.max_steps,
                      'propertyNames': alias, 'additionalProperties': {'oneOf': branches}},
        }}
    frontmatter = {'type': 'object', 'properties': {
        'model_tier': _enum(manifest['modelTiers']), 'effort': {'enum': ['low', 'medium', 'high']},
        # Prose requests do not grant capabilities. Registration semantics stay
        # in admission; enumerating private requested names would disclose them.
        'tools': {'anyOf': [_names({'type': 'string'}), {'enum': ['', 'none', 'read', 'write']}]},
    }}
    inline_agent = {'type': 'object', 'additionalProperties': False,
        'required': ['type', 'frontmatter', 'body'], 'properties': {
            'type': {'enum': ['subagent', 'command']}, 'frontmatter': frontmatter, 'body': {'type': 'string'},
            'resources': {'type': 'array', 'items': {'type': 'object',
                'required': ['relPath', 'content'], 'properties': {
                    'relPath': {'type': 'string'}, 'content': {'type': 'string'}}}},
        }}
    inline_agent['allOf'] = []
    for kind in ('command', 'subagent'):
        canonical = {'type': {'const': kind}}
        if kind == 'subagent':
            canonical.update(name={'type': 'string', 'minLength': 1},
                             description={'type': 'string', 'minLength': 1})
        condition = {'if': {'properties': {'type': {'const': kind}}},
                     'then': {'properties': {'frontmatter': {'properties': canonical}}}}
        if kind == 'subagent':
            condition['then']['properties']['frontmatter']['required'] = ['name', 'description']
        inline_agent['allOf'].append(condition)
    inline_schema = {'type': 'object', 'propertyNames': alias,
                     'additionalProperties': inline_agent, 'maxProperties': policy.max_agent_steps}
    envelope = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
        '$id': 'urn:prosaic-harness:proposal:v1', 'type': 'object',
        'required': ['definition'], 'additionalProperties': False,
        'properties': {'definition': definition_schema,
            'inline_agents': inline_schema if policy.allow_inline_agents else {'type': 'object', 'maxProperties': 0}}}
    return _bounded(envelope, maximum_bytes)
