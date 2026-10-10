"""Owned native workflow construction and mandatory resolved admission.

ALWAYS keep authority in host policy and bindings. NEVER execute proposal code,
resolve client paths, or treat a supplied fingerprint as admission evidence.
"""
from collections.abc import Mapping
from dataclasses import dataclass, fields
import json
import re
import unicodedata
from types import MappingProxyType

from prosaic import validate_artifact_definition
from prosaic_runtime import (CliSandboxConfig, EndpointConfig, ProsaicArtifact,
                             ProsaicRuntime, RunLimits, RuntimeConfig,
                             custom_descriptors, validate_custom_tools,
                             validate_execution_artifact)
from prosaic_runtime.policy import BUILTIN_TOOLS, requested_tools

from .admission_data import parse_bounded_json, snapshot_json
from .errors import WorkflowAdmissionError
from .graph_admission import validate_resolved_workflow
from .schema_validation import admit_schema
from .validation import Validator
from .workflow import Workflow, digest, runtime_identity


_STORAGE_BYTES = 8_388_608
_HOST_DEPTH = 512
_HOST_NODES = 1_048_576
_ALIAS = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')


def _fail(code, location='$'):
    raise WorkflowAdmissionError(code, location) from None


def _encode(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


def _host_snapshot(value):
    return snapshot_json(value, maximum_bytes=_STORAGE_BYTES,
                         maximum_depth=_HOST_DEPTH, maximum_nodes=_HOST_NODES)


def _alias(value):
    if type(value) is not str or not _ALIAS.fullmatch(value):
        _fail('invalid_definition')


def _config_payload(config, *, native=False):
    """Inspect bounded standard configuration before any recursive conversion."""
    if (type(config) is not RuntimeConfig or type(config.profiles) is not dict
            or type(config.routes) is not dict or type(config.limits) is not RunLimits
            or type(config.cli_sandbox) is not CliSandboxConfig
            or type(config.allowed_tools) is not frozenset
            or any(type(name) is not str or not name for name in config.allowed_tools)
            or type(config.tool_directories) is not tuple
            or any(type(path) is not str or not path for path in config.tool_directories)
            or type(config.cli_sandbox.runtime_roots) is not tuple):
        _fail('binding_mismatch')
    profiles = {}
    for name, endpoint in config.profiles.items():
        if (type(name) is not str or not name or type(endpoint) is not EndpointConfig
                or type(endpoint.features) is not dict):
            _fail('binding_mismatch')
        profiles[name] = {item.name: getattr(endpoint, item.name) for item in fields(EndpointConfig)}
    value = {'profiles': profiles, 'routes': config.routes,
             'default_profile': config.default_profile,
             'allowed_tools': sorted(config.allowed_tools),
             'limits': {item.name: getattr(config.limits, item.name) for item in fields(RunLimits)},
             'tool_directories': [] if native else list(config.tool_directories),
             'cli_sandbox': {'mode': config.cli_sandbox.mode,
                             'runtime_roots': list(config.cli_sandbox.runtime_roots)}}
    try:
        owned = _host_snapshot(value)
        # Constructors recheck shallowly frozen dataclasses after caller mutation.
        _config_from_json(_encode(owned))
        return owned
    except Exception:
        _fail('binding_mismatch')


def _config_from_json(config_json):
    """Reconstruct a fresh execution config from the owned immutable record."""
    value = json.loads(config_json)
    return RuntimeConfig(
        profiles={name: EndpointConfig(**endpoint) for name, endpoint in value['profiles'].items()},
        routes=value['routes'], default_profile=value['default_profile'],
        allowed_tools=frozenset(value['allowed_tools']), limits=RunLimits(**value['limits']),
        tool_directories=tuple(value['tool_directories']),
        cli_sandbox=CliSandboxConfig(value['cli_sandbox']['mode'],
                                    tuple(value['cli_sandbox']['runtime_roots'])))


def _artifact_data(artifact):
    if isinstance(artifact, ProsaicArtifact):
        return {'id': artifact.id, 'type': artifact.type, 'frontmatter': artifact.frontmatter,
                'body': artifact.body, 'resources': list(artifact.resources)}
    if type(artifact) is dict:
        return artifact
    _fail('invalid_artifact')


def _artifact_snapshot(artifact, *, maximum_bytes=_STORAGE_BYTES, maximum_depth=_HOST_DEPTH,
                       maximum_nodes=_HOST_NODES, inline_id=None):
    try:
        if isinstance(artifact, ProsaicArtifact):
            if type(artifact.resources) not in (tuple, list):
                _fail('invalid_artifact')
            if len(artifact.resources) > maximum_nodes:
                _fail('limit_exceeded')
        data = _artifact_data(artifact)
        if inline_id is not None:
            if set(data) - {'type', 'frontmatter', 'body', 'resources'}:
                _fail('invalid_artifact')
            data = {'id': inline_id, **data}
        owned = snapshot_json(data, maximum_bytes=maximum_bytes, maximum_depth=maximum_depth,
                              maximum_nodes=maximum_nodes)
        result = ProsaicArtifact.from_inspection(owned)
        if not validate_artifact_definition(result.type, result.frontmatter)['ok']:
            _fail('invalid_artifact')
        return result
    except WorkflowAdmissionError:
        raise
    except Exception:
        _fail('invalid_artifact')


class WorkflowCatalog:
    """Host-approved content, captured independently of caller-owned containers."""
    def __init__(self, *, agents=None, schemas=None):
        agents = {} if agents is None else agents
        schemas = {} if schemas is None else schemas
        if not isinstance(agents, Mapping) or not isinstance(schemas, Mapping):
            _fail('invalid_definition')
        agent_values, schema_values = {}, {}
        for alias, artifact in agents.items():
            _alias(alias)
            agent_values[alias] = _encode(_artifact_data(_artifact_snapshot(artifact)))
        for alias, schema in schemas.items():
            _alias(alias)
            schema_values[alias] = _encode(_host_snapshot(schema))
        self._agents = MappingProxyType(agent_values)
        self._schemas = MappingProxyType(schema_values)


class WorkflowBindings:
    """Native effective configuration and trusted registrations, without probes."""
    def __init__(self, *, config, custom_tools=None, validators=None):
        self._config_json = _encode(_config_payload(config, native=True))
        try:
            self._tools = MappingProxyType(validate_custom_tools(custom_tools))
            values = dict(validators or {})
            for name, validator in values.items():
                _alias(name)
                if type(validator) is not Validator:
                    _fail('binding_mismatch')
            _host_snapshot({name: validator.version for name, validator in values.items()})
            self._validators = MappingProxyType(values)
        except WorkflowAdmissionError:
            raise
        except Exception:
            _fail('binding_mismatch')


@dataclass(frozen=True)
class WorkflowPolicy:
    allowed_agents: frozenset = frozenset()
    allowed_schemas: frozenset = frozenset()
    allowed_tools: frozenset = frozenset()
    allowed_validators: frozenset = frozenset()
    allowed_model_tiers: frozenset = frozenset()
    allow_agent_composition: bool = False
    allow_inline_agents: bool = False
    max_steps: int = 64
    max_agent_steps: int = 32
    max_proposal_bytes: int = 262144
    max_json_depth: int = 64
    max_json_nodes: int = 65536
    max_artifact_bytes: int = 524288
    max_schema_bytes: int = 65536
    max_total_schema_bytes: int = 524288
    max_calls: int = 12
    max_visits: int = 4
    max_attempts: int = 2
    timeout_s: int = 180
    max_tokens: int = 32768
    max_run_s: int = 1800
    max_run_input_bytes: int = 65536
    max_human_response_bytes: int = 65536
    max_invocation_bytes: int = 262144
    max_output_bytes: int = 100000
    max_event_bytes: int = 65536
    max_metadata_bytes: int = 65536
    max_receipt_bytes: int = 1048576
    max_state_bytes: int = 4194304

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name.startswith('allowed_'):
                if type(value) not in (frozenset, set, tuple, list):
                    _fail('invalid_definition')
                for name in value:
                    if item.name == 'allowed_model_tiers':
                        # Runtime routes are host names, not catalogue aliases.
                        if (type(name) is not str or not 1 <= len(name) <= 64
                                or any(unicodedata.category(char) in {'Cc', 'Cf', 'Cs'} for char in name)):
                            _fail('invalid_definition')
                    else:
                        _alias(name)
                object.__setattr__(self, item.name, frozenset(value))
            elif item.name.startswith('allow_'):
                if type(value) is not bool:
                    _fail('invalid_definition')
            elif type(value) is not int or value <= 0:
                _fail('invalid_definition')
            elif item.name.endswith('_bytes') and value > _STORAGE_BYTES:
                _fail('limit_exceeded')
        if self.max_output_bytes > 100000:
            _fail('limit_exceeded')

    def _identity(self):
        return {item.name: sorted(getattr(self, item.name)) if item.name.startswith('allowed_')
                else getattr(self, item.name) for item in fields(self)}

    def schema_profile(self, human=False):
        return {'version': 1, 'dialect': '2020-12', 'refs': 'acyclic-local-static',
                'maximum_depth': self.max_json_depth, 'maximum_nodes': self.max_json_nodes,
                'maximum_schema_bytes': self.max_schema_bytes,
                'maximum_instance_bytes': self.max_human_response_bytes if human else self.max_output_bytes}


@dataclass(frozen=True)
class _AdmissionRecord:
    original_seal: str
    config_json: str
    policy: WorkflowPolicy
    tools: Mapping
    validators: Mapping
    validator_versions: Mapping
    content_json: str


def _identity_payload(workflow, policy):
    # ALWAYS bound mutable execution objects before digest/asdict consumers.
    definition = snapshot_json(workflow.definition,
        maximum_bytes=min(_STORAGE_BYTES, policy.max_proposal_bytes + 4096),
        maximum_depth=policy.max_json_depth, maximum_nodes=policy.max_json_nodes)
    expected_schemas = {name for name, step in definition.get('steps', {}).items()
                        if type(step) is dict and (step.get('kind') == 'agent'
                            or step.get('kind') == 'pause' and 'response_schema' in step)}
    if (type(workflow.schemas) is not dict or len(workflow.schemas) > policy.max_steps
            or set(workflow.schemas) != expected_schemas):
        _fail('identity_mismatch')
    for name in workflow.schemas:
        _alias(name)
    # Depth and node budgets apply per resolved root. The internal map has only
    # bounded, normalized step keys; the aggregate byte budget counts bodies.
    schemas = {}
    total_schema_bytes = 0
    for name, schema in workflow.schemas.items():
        remaining = policy.max_total_schema_bytes - total_schema_bytes
        if remaining <= 0:
            _fail('limit_exceeded')
        owned = snapshot_json(schema, maximum_bytes=min(policy.max_schema_bytes, remaining),
                              maximum_depth=policy.max_json_depth,
                              maximum_nodes=policy.max_json_nodes)
        total_schema_bytes += len(_encode(owned).encode())
        schemas[name] = owned
    artifacts = {}
    total = 0
    for name, artifact in workflow.artifacts.items():
        owned = _artifact_snapshot(artifact, maximum_bytes=policy.max_artifact_bytes,
                                  maximum_depth=policy.max_json_depth,
                                  maximum_nodes=policy.max_json_nodes)
        total += len(_encode(_artifact_data(owned)).encode())
        if total > policy.max_artifact_bytes:
            _fail('limit_exceeded')
        artifacts[name] = owned.digest
    config = _config_from_json(_encode(_config_payload(workflow.config)))
    descriptors = snapshot_json(workflow.tool_descriptors, maximum_bytes=_STORAGE_BYTES,
                                maximum_depth=policy.max_json_depth, maximum_nodes=policy.max_json_nodes)
    return {'workflow': definition, 'runtime': runtime_identity(config),
            'schemas': schemas, 'prose': artifacts,
            **({'custom_tools': descriptors} if descriptors else {}),
            'admission': {'version': 1, 'profile': 1, 'policy': policy._identity()}}


class _NativeWorkflow(Workflow):
    """Fixed native origin survives missing records and caller path mutation."""
    @property
    def tool_descriptors(self):
        record = getattr(self, '_admission', None)
        policy = record.policy if type(record) is _AdmissionRecord else None
        return snapshot_json(self._tool_descriptors, maximum_bytes=_STORAGE_BYTES,
                             maximum_depth=policy.max_json_depth if policy else 64,
                             maximum_nodes=policy.max_json_nodes if policy else 65536)

    def current_fingerprint(self):
        record = getattr(self, '_admission', None)
        if type(record) is not _AdmissionRecord:
            _fail('identity_mismatch')
        return digest(_identity_payload(self, record.policy))

    def snapshot(self):
        return {}


def _policy_graph(workflow, policy, *, inline_names=frozenset()):
    steps = workflow.definition['steps']
    if len(steps) > policy.max_steps:
        _fail('limit_exceeded')
    count = sum(step.get('kind') == 'agent' for step in steps.values())
    if count > policy.max_agent_steps:
        _fail('limit_exceeded')
    if count > 1 and not policy.allow_agent_composition:
        _fail('policy_denied')
    for name, step in steps.items():
        _alias(name)
        if step.get('max_visits', workflow.definition['limits']['max_visits']) > policy.max_visits:
            _fail('limit_exceeded')
        for validator in step.get('validators', []):
            if validator not in policy.allowed_validators:
                _fail('policy_denied')
        if step.get('kind') == 'agent':
            if step['agent'] not in policy.allowed_agents and step['agent'] not in inline_names:
                _fail('policy_denied')
            if step['schema'] not in policy.allowed_schemas:
                _fail('policy_denied')
            if set(step.get('tools', [])) - policy.allowed_tools:
                _fail('policy_denied')
            if step.get('max_attempts', policy.max_attempts) > policy.max_attempts:
                _fail('limit_exceeded')
            tier = workflow.artifacts[name].frontmatter.get('model_tier')
            if tier is not None and tier not in policy.allowed_model_tiers:
                _fail('policy_denied')
        elif 'response_schema' in step and step['response_schema'] not in policy.allowed_schemas:
            _fail('policy_denied')


class WorkflowFactory:
    def __init__(self, *, catalog, bindings, policy):
        if (type(catalog) is not WorkflowCatalog or type(bindings) is not WorkflowBindings
                or type(policy) is not WorkflowPolicy):
            _fail('binding_mismatch')
        self._agents = MappingProxyType(dict(catalog._agents))
        self._schemas = MappingProxyType(dict(catalog._schemas))
        self._config_json = bindings._config_json
        self._tools = MappingProxyType(dict(bindings._tools))
        self._validators = MappingProxyType(dict(bindings._validators))
        self._policy = policy

    def build_json(self, text):
        envelope = parse_bounded_json(text, maximum_bytes=self._policy.max_proposal_bytes,
            maximum_depth=self._policy.max_json_depth, maximum_nodes=self._policy.max_json_nodes)
        if type(envelope) is not dict or set(envelope) - {'definition', 'inline_agents'} or 'definition' not in envelope:
            _fail('invalid_definition')
        if 'inline_agents' in envelope and type(envelope['inline_agents']) is not dict:
            _fail('invalid_definition')
        return self.build(envelope['definition'], inline_agents=envelope.get('inline_agents'))

    def build(self, definition, *, inline_agents=None):
        policy = self._policy
        envelope = snapshot_json({'definition': definition,
                                  'inline_agents': {} if inline_agents is None else inline_agents},
            maximum_bytes=policy.max_proposal_bytes, maximum_depth=policy.max_json_depth,
            maximum_nodes=policy.max_json_nodes)
        try:
            return self._build(envelope['definition'], envelope['inline_agents'])
        except WorkflowAdmissionError:
            raise
        except Exception:
            _fail('invalid_definition')

    def _build(self, definition, inline_agents):
        policy = self._policy
        if type(definition) is not dict or type(inline_agents) is not dict:
            _fail('invalid_definition')
        if 'resources' in definition:
            _fail('resource_not_bound')
        if set(definition) - {'version', 'name', 'start', 'limits', 'steps'}:
            _fail('invalid_definition')
        if inline_agents and not policy.allow_inline_agents:
            _fail('policy_denied')
        if set(inline_agents) & self._agents.keys():
            _fail('invalid_artifact')
        for alias in inline_agents:
            _alias(alias)
        steps = definition.get('steps')
        if type(steps) is not dict or any(type(step) is not dict for step in steps.values()):
            _fail('invalid_definition')
        if len(steps) > policy.max_steps:
            _fail('limit_exceeded')
        count = sum(step.get('kind') == 'agent' for step in steps.values())
        if count > policy.max_agent_steps:
            _fail('limit_exceeded')
        if count > 1 and not policy.allow_agent_composition:
            _fail('policy_denied')
        limits = definition.setdefault('limits', {})
        if type(limits) is not dict:
            _fail('invalid_definition')
        for name in ('max_calls', 'max_visits', 'timeout_s', 'max_tokens', 'max_run_s'):
            cap = getattr(policy, name)
            value = limits.setdefault(name, cap)
            if type(value) is not int or value <= 0:
                _fail('invalid_definition')
            if value > cap:
                _fail('limit_exceeded')
        config = _config_from_json(self._config_json)
        artifacts, schemas, used_inline = {}, {}, set()
        schema_total = artifact_total = 0
        for name, step in steps.items():
            if 'resources' in step:
                _fail('resource_not_bound')
            if set(step) & {'acquisition', 'read_roots', 'require_reads'}:
                _fail('resource_not_bound')
            if step.get('kind') == 'agent':
                alias = step.get('agent')
                _alias(alias)
                if alias in inline_agents:
                    data = inline_agents[alias]
                    if type(data) is not dict:
                        _fail('invalid_artifact')
                    if artifact_total + len(_encode({'id': alias, **data})) > policy.max_artifact_bytes:
                        _fail('limit_exceeded')
                    artifact = _artifact_snapshot(data, maximum_bytes=policy.max_artifact_bytes,
                        maximum_depth=policy.max_json_depth, maximum_nodes=policy.max_json_nodes,
                        inline_id=alias)
                    used_inline.add(alias)
                elif alias in self._agents:
                    if artifact_total + len(self._agents[alias]) > policy.max_artifact_bytes:
                        _fail('limit_exceeded')
                    artifact = _artifact_snapshot(json.loads(self._agents[alias]),
                        maximum_bytes=policy.max_artifact_bytes, maximum_depth=policy.max_json_depth,
                        maximum_nodes=policy.max_json_nodes)
                else:
                    _fail('unknown_reference')
                artifact_total += len(_encode(_artifact_data(artifact)))
                if artifact_total > policy.max_artifact_bytes:
                    _fail('limit_exceeded')
                try:
                    validate_execution_artifact(artifact, config)
                    if requested_tools(artifact.frontmatter.get('tools')) - BUILTIN_TOOLS - self._tools.keys():
                        _fail('invalid_artifact')
                except WorkflowAdmissionError:
                    raise
                except Exception:
                    _fail('invalid_artifact')
                artifacts[name] = artifact
                step.setdefault('max_attempts', policy.max_attempts)
            schema_alias = step.get('schema') if step.get('kind') == 'agent' else step.get('response_schema')
            if schema_alias is not None:
                _alias(schema_alias)
                if schema_alias not in self._schemas:
                    _fail('unknown_reference')
                schema = admit_schema(json.loads(self._schemas[schema_alias]), profile=policy.schema_profile())
                schema_total += len(_encode(schema).encode())
                if schema_total > policy.max_total_schema_bytes:
                    _fail('limit_exceeded')
                schemas[name] = schema
        if set(inline_agents) != used_inline:
            _fail('invalid_artifact')
        needed = {validator for step in steps.values() for validator in step.get('validators', [])}
        if needed - self._validators.keys():
            _fail('binding_mismatch')
        workflow = _NativeWorkflow(None, definition, config, artifacts, schemas, '',
                                   custom_tools=self._tools)
        descriptors = custom_descriptors(self._tools)
        demanded = validate_resolved_workflow(workflow, descriptors=descriptors,
                                               profile=policy.schema_profile(), native=True)
        _policy_graph(workflow, policy, inline_names=frozenset(used_inline))
        workflow._tool_descriptors = demanded
        payload = _identity_payload(workflow, policy)
        seal = digest(payload)
        workflow.fingerprint = seal
        workflow._admission = _AdmissionRecord(seal, self._config_json, policy, self._tools,
            MappingProxyType({name: self._validators[name] for name in needed}),
            MappingProxyType({name: self._validators[name].version for name in sorted(needed)}),
            _encode(payload))
        return workflow


def _check_adapter(workflow, runtime, descriptors, *, native):
    if runtime is None:
        return
    if native and (type(runtime) is not ProsaicRuntime or runtime.cli_tool_names):
        _fail('binding_mismatch')
    actual_config = getattr(runtime, 'config', None)
    if native or isinstance(actual_config, RuntimeConfig):
        if _encode(_config_payload(actual_config)) != _encode(_config_payload(workflow.config)):
            _fail('binding_mismatch')
    if descriptors:
        if 'custom_tools_v1' not in getattr(runtime, 'capabilities', ()):
            _fail('binding_mismatch')
        actual = getattr(runtime, 'tool_descriptors', {})
        if any(actual.get(name) != expected for name, expected in descriptors.items()):
            _fail('binding_mismatch')


def admit_workflow(workflow, *, runtime=None, validators=None):
    """Readmit current content without repairing identity or invoking callbacks."""
    try:
        if isinstance(workflow, _NativeWorkflow):
            record = getattr(workflow, '_admission', None)
            if type(record) is not _AdmissionRecord or workflow.path is not None or workflow.acquisitions:
                _fail('identity_mismatch')
            current = _identity_payload(workflow, record.policy)
            if (workflow.fingerprint != record.original_seal or digest(current) != record.original_seal
                    or _encode(current) != record.content_json
                    or _encode(_config_payload(workflow.config)) != record.config_json):
                _fail('identity_mismatch')
            demanded = validate_resolved_workflow(workflow, descriptors=custom_descriptors(record.tools),
                profile=record.policy.schema_profile(), native=True)
            if demanded != workflow.tool_descriptors:
                _fail('binding_mismatch')
            _check_adapter(workflow, runtime, demanded, native=True)
            selected = record.validators if validators is None else validators
            if any(type(selected.get(name)) is not Validator or selected[name].version != version
                   for name, version in record.validator_versions.items()):
                _fail('binding_mismatch')
            return record
        if not isinstance(workflow, Workflow):
            _fail('invalid_definition')
        registered = custom_descriptors(validate_custom_tools(workflow.custom_tools))
        registered.update(getattr(workflow, '_registered_descriptors', {}))
        if runtime is not None:
            registered.update(getattr(runtime, 'tool_descriptors', {}))
        demanded = validate_resolved_workflow(workflow, descriptors=registered, profile=None, native=False)
        if demanded != workflow.tool_descriptors:
            _fail('binding_mismatch')
        if workflow.current_fingerprint() != workflow.fingerprint:
            _fail('identity_mismatch')
        _check_adapter(workflow, runtime, demanded, native=False)
        return None
    except WorkflowAdmissionError:
        raise
    except Exception:
        _fail('invalid_definition')
