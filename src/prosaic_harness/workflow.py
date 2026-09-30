"""Load a small declarative graph; Python owns interpretation and authority."""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
import yaml
from prosaic_runtime import RuntimeConfig
from prosaic_runtime.artifacts import inspect_artifact
from prosaic_runtime.policy import READ_TOOLS, BUILTIN_TOOLS, requested_tools


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError(f'duplicate workflow key: {key}')
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def positive(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(f'{name} must be a positive integer')


def local(root, value):
    if not isinstance(value, str):
        raise ValueError('file paths must be strings')
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError('workflow file path escapes its directory')
    return path


def reject_external_refs(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {'$ref', '$dynamicRef'} and (not isinstance(child, str) or not child.startswith('#')):
                raise ValueError('schemas support internal references only')
            reject_external_refs(child)
    elif isinstance(value, list):
        for child in value:
            reject_external_refs(child)


@dataclass
class Workflow:
    path: Path
    definition: dict
    config: RuntimeConfig
    artifacts: dict
    schemas: dict
    fingerprint: str

    @classmethod
    def load(cls, path, *, executable='prosaic'):
        try:
            return cls._load(path, executable=executable)
        except (yaml.YAMLError, SchemaError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f'invalid workflow definition: {type(exc).__name__}') from exc

    @classmethod
    def _load(cls, path, *, executable):
        path = Path(path).resolve()
        if path.suffix not in {'.yml', '.yaml'}:
            raise ValueError('workflow must use YAML/YML')
        raw = yaml.load(path.read_text(), Loader=UniqueLoader)
        if not isinstance(raw, dict) or set(raw) - {'version', 'name', 'source', 'runtime', 'start', 'limits', 'steps'}:
            raise ValueError('invalid workflow keys')
        if type(raw.get('version')) is not int or raw['version'] != 1:
            raise ValueError('workflow version must be 1')
        steps = raw.get('steps')
        if not isinstance(steps, dict) or not steps or raw.get('start') not in steps:
            raise ValueError('workflow needs steps and a valid start')
        if not all(isinstance(step, dict) for step in steps.values()):
            raise ValueError('every step must be a mapping')
        limits = raw.setdefault('limits', {})
        if not isinstance(limits, dict) or set(limits) - {'max_calls', 'max_visits', 'timeout_s'}:
            raise ValueError('invalid workflow limits')
        limits.setdefault('max_calls', 12)
        limits.setdefault('max_visits', 4)
        limits.setdefault('timeout_s', 180)
        for key in limits:
            positive(limits[key], key)
        root = path.parent
        config = RuntimeConfig.load(local(root, raw['runtime']))
        source = local(root, raw.get('source', '.prosaic'))
        artifacts, schemas = {}, {}
        for name, step in steps.items():
            if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]*', name):
                raise ValueError('step identifiers must be simple names')
            if not isinstance(step, dict):
                raise ValueError(f'invalid step: {name}')
            kind = step.get('kind')
            allowed = {
                'agent': {'kind', 'agent', 'schema', 'inputs', 'optional_inputs', 'next', 'max_attempts', 'max_visits', 'tools', 'read_roots', 'require_tools'},
                'gate': {'kind', 'from', 'field', 'equals', 'pass', 'fail', 'max_visits'},
                'pause': {'kind', 'question', 'choices', 'max_visits'},
                'finish': {'kind', 'outcome', 'max_visits'},
            }
            if kind not in allowed or set(step) - allowed[kind]:
                raise ValueError(f'unsupported step or keys: {name}')
            positive(step.get('max_visits', limits['max_visits']), 'max_visits')
            targets = []
            if kind == 'agent':
                positive(step.get('max_attempts', 2), 'max_attempts')
                targets = [step['next']]
                tools = step.get('tools', [])
                roots = step.get('read_roots', [])
                if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools) or set(tools) - READ_TOOLS:
                    raise ValueError('v0.1 agent steps support read tools only')
                if set(tools) - config.allowed_tools:
                    raise ValueError('step requests tools missing from runtime allowed_tools')
                required = step.get('require_tools', [])
                if not isinstance(required, list) or not all(isinstance(t, str) for t in required) or set(required) - set(tools):
                    raise ValueError('require_tools must be a subset of granted step tools')
                if not isinstance(roots, list) or (tools and not roots):
                    raise ValueError('read tools require explicit read_roots')
                for value in roots:
                    local(root, value)
                for field in ('inputs', 'optional_inputs'):
                    refs = step.get(field, [])
                    if not isinstance(refs, list) or any(ref not in steps or steps[ref].get('kind') != 'agent' for ref in refs):
                        raise ValueError('agent inputs must reference agent steps')
                artifact = inspect_artifact(step['agent'], source, executable=executable)
                if requested_tools(artifact.frontmatter.get('tools')) - BUILTIN_TOOLS:
                    raise ValueError('prose requests unsupported runtime tools')
                if set(required) - requested_tools(artifact.frontmatter.get('tools')):
                    raise ValueError('prose does not request required tools')
                tier = artifact.frontmatter.get('model_tier')
                if tier is not None and tier not in config.routes:
                    raise ValueError(f'no runtime route for tier: {tier}')
                artifacts[name] = artifact
                schema = json.loads(local(root, step['schema']).read_text())
                reject_external_refs(schema)
                Draft202012Validator.check_schema(schema)
                schemas[name] = schema
            elif kind == 'gate':
                if step.get('from') not in steps or steps[step['from']].get('kind') != 'agent':
                    raise ValueError('gate must reference an agent step')
                if not isinstance(step.get('field'), list) or not step['field'] or not all(isinstance(f, str) for f in step['field']):
                    raise ValueError('gate field must be a nonempty list of keys')
                if 'equals' not in step:
                    raise ValueError('gate requires equals')
                targets = [step['pass'], step['fail']]
            elif kind == 'pause':
                if not isinstance(step.get('question'), str) or not step['question']:
                    raise ValueError('pause needs a question')
                if not isinstance(step.get('choices'), dict) or not step['choices'] or not all(isinstance(k, str) and k for k in step['choices']):
                    raise ValueError('pause needs named choices')
                targets = list(step['choices'].values())
            elif step.get('outcome', 'completed') not in {'completed', 'rejected'}:
                raise ValueError('finish outcome must be completed or rejected')
            if any(not isinstance(t, str) or t not in steps for t in targets):
                raise ValueError(f'unknown transition target in {name}')
        fingerprint = digest({'workflow': raw, 'runtime': asdict(config) | {'allowed_tools': sorted(config.allowed_tools)},
                              'schemas': schemas, 'prose': {name: a.digest for name, a in artifacts.items()}})
        return cls(path, raw, config, artifacts, schemas, fingerprint)
