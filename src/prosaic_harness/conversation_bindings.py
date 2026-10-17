"""Pure host admission for graph-free conversation execution.

ALWAYS admit current declarations before effects. NEVER treat hashes or prose
as authority, or discover executables during conversation admission.
"""
from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType

from prosaic_runtime import (ProsaicArtifact, ProsaicRuntime, RunPolicy, TurnLimits,
    InvocationScope, custom_descriptors, validate_custom_tools, tool_journal_descriptor,
    TurnAdmissionError)

from .conversation_errors import ConversationError
from .factory import (_config_payload, _config_from_json, _artifact_snapshot,
                      _artifact_data, admit_workflow, WorkflowPolicy)
from .schema_validation import admit_schema
from .session_codec import encode, decode, owned, digest, reference
from .validation import Validator

_ADMITTED = object()


@dataclass(frozen=True)
class ConversationScope:
    namespace: str
    environment: str
    application: str
    tenant: str
    actor: str
    billing_account: str | None = None
    def __post_init__(self):
        try:
            for f in fields(self):
                value = getattr(self, f.name)
                if f.name == 'billing_account' and value is None:
                    continue
                reference(value)
        except (ValueError, TypeError, UnicodeError):
            raise ConversationError('identityMismatch') from None
    def to_dict(self):
        self.__post_init__()
        return {'namespace': self.namespace, 'environment': self.environment,
            'application': self.application, 'tenant': self.tenant, 'actor': self.actor,
            'billingAccount': self.billing_account}


@dataclass(frozen=True)
class RunAuthorizer:
    identity: str
    version: str
    authorize: object
    def __post_init__(self):
        reference(self.identity)
        reference(self.version)
        if not callable(self.authorize):
            raise ConversationError('bindingMismatch')


@dataclass(frozen=True)
class ConfirmationRule:
    identity: str
    version: str
    admit: object
    def __post_init__(self):
        reference(self.identity)
        reference(self.version)
        if not callable(self.admit):
            raise ConversationError('bindingMismatch')


@dataclass(frozen=True)
class ConversationPolicy:
    max_turns: int = 64
    max_history_bytes: int = 4_194_304
    max_state_bytes: int = 8_388_608
    max_user_bytes: int = 16_384
    max_assistant_bytes: int = 65_536
    max_turn_bytes: int = 131_072
    max_input_bytes: int = 196_608
    max_attempts_per_turn: int = 3
    max_attempts: int = 128
    max_receipt_bytes: int = 8_388_608
    max_total_receipt_bytes: int = 67_108_864
    max_json_depth: int = 64
    max_json_nodes: int = 65_536
    max_public_bytes: int = 262_144
    max_provider_requests: int = 256
    max_tool_calls: int = 256
    context_mode: str = 'fullHistory'
    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == 'context_mode':
                if type(value) is not str or value != 'fullHistory':
                    raise ConversationError('bindingMismatch')
                continue
            minimum = 0 if f.name in {'max_provider_requests', 'max_tool_calls'} else 1
            if type(value) is not int or value < minimum:
                raise ConversationError('bindingMismatch')
        if (self.max_json_depth > 64 or self.max_json_nodes>65536
                or self.max_state_bytes>8388608 or self.max_receipt_bytes>8388608
                or self.max_public_bytes<encoded_answer_bound(self.max_assistant_bytes,self.max_turn_bytes)+8192
                or self.max_receipt_bytes<=self.max_turn_bytes+encoded_answer_bound(self.max_assistant_bytes,self.max_turn_bytes)+8192):
            raise ConversationError('bindingMismatch')
    def to_dict(self):
        self.__post_init__()
        return {f.name: getattr(self, f.name) for f in fields(self)}


def encoded_answer_bound(assistant_bytes,turn_bytes):
    # ensure_ascii=False still escapes control characters up to six bytes each.
    # A successful answer is also contained in the bounded complete turn.
    return min(6*assistant_bytes+2,turn_bytes)


def _rule(value, cls):
    if value is None:
        return None
    if type(value) is not cls:
        raise ConversationError('bindingMismatch')
    value.__post_init__()
    return {'identity': value.identity, 'version': value.version}


def _policy(value):
    if type(value) is not RunPolicy:
        raise ConversationError('bindingMismatch')
    # Bound containers before any recursive conversion of mutable aliases.
    raw = {f.name: getattr(value, f.name) for f in fields(value)}
    if type(raw['allowed_tools']) is not frozenset:
        raise ConversationError('bindingMismatch')
    raw['allowed_tools'] = sorted(raw['allowed_tools'])
    for key in ('read_roots', 'write_paths', 'forbidden_roots'):
        if type(raw[key]) is not tuple:
            raise ConversationError('bindingMismatch')
        raw[key] = list(raw[key])
    data = owned(raw)
    value.__post_init__()
    # Preserve pre-feature sealed bytes when the optional Runtime policy is off.
    if data.get('bounded_tool_recovery') is False:
        data.pop('bounded_tool_recovery')
    if any(type(data[key]) is not int or data[key] < 0
           for key in ('max_provider_requests', 'max_tool_calls')):
        raise ConversationError('bindingMismatch')
    return data


def _policy_from(data):
    data = owned(data)
    data['allowed_tools'] = frozenset(data['allowed_tools'])
    for key in ('read_roots', 'write_paths', 'forbidden_roots'):
        data[key] = tuple(data[key])
    return RunPolicy(**data)


def _logical_config(config):
    data = owned(config)
    for endpoint in data['profiles'].values():
        endpoint.pop('api_key_env', None)
        endpoint.pop('api_key_file', None)
        endpoint['features'].pop('provider_transcript_dir', None)
    return data


def _interpretation_schema(schema):
    base = {'type': 'object', 'properties': {
        'sourceMessageId': {'type': 'string', 'minLength': 1, 'maxLength': 128},
        'interactionRef': {'type': 'string', 'minLength': 1, 'maxLength': 128},
        'choice': {'type': ['string', 'null'], 'maxLength': 128},
        'response': {}, 'ambiguous': {'type': 'boolean'}},
        'required': ['sourceMessageId', 'interactionRef', 'ambiguous'], 'additionalProperties': False}
    if schema is None:
        return base
    data = admit_schema(schema, profile=WorkflowPolicy().schema_profile())
    if (type(data) is not dict or data.get('type') != 'object'
            or data.get('additionalProperties') is not False
            or type(data.get('properties')) is not dict
            or set(data['properties']) - set(base['properties'])
            or not set(base['required']).issubset(data.get('required', []))):
        raise ConversationError('bindingMismatch')
    # Admission always applies the fixed closed schema as well as the narrower host schema.
    return {'allOf': [base, data]}


@dataclass(frozen=True, init=False, repr=False)
class WorkflowRegistration:
    _encoded: bytes
    _workflow: object
    _store: object
    _runtime: object
    _validators: object
    _accounting: object
    _context: object
    _authorizer: object
    _confirmation: object
    _admitted: object
    def __init__(self, workflow, *, store, authorizer, runtime=None, validators=None,
                 accounting=None, context=None, review_outputs=(), confirmation_rule=None):
        try:
            if type(authorizer) is not RunAuthorizer or type(review_outputs) is not tuple:
                raise ConversationError('bindingMismatch')
            for value in review_outputs:
                reference(value)
            validation = dict(validators or {})
            for name, validator in validation.items():
                reference(name)
                if type(validator) is not Validator:
                    raise ConversationError('bindingMismatch')
                reference(validator.version)
                if not callable(validator.check):
                    raise ConversationError('bindingMismatch')
            original = admit_workflow(workflow, runtime=runtime, validators=validation or None)
            if validators is None and original is not None:
                validation = dict(original.validators)
            declaration = {'workflow': workflow.fingerprint, 'storeNamespace': reference(store.namespace),
                'authorizer': _rule(authorizer, RunAuthorizer),
                'confirmation': _rule(confirmation_rule, ConfirmationRule),
                'validators': {n: v.version for n, v in validation.items()},
                'reviewOutputs': list(review_outputs)}
            for key, value in {'_encoded': encode(declaration), '_workflow': workflow, '_store': store,
                    '_runtime': runtime, '_validators': MappingProxyType(validation), '_accounting': accounting,
                    '_context': context, '_authorizer': authorizer, '_confirmation': confirmation_rule,
                    '_admitted': _ADMITTED}.items():
                object.__setattr__(self, key, value)
        except ConversationError:
            raise
        except Exception:
            raise ConversationError('bindingMismatch') from None
    def readmit(self):
        try:
            if self._admitted is not _ADMITTED:
                raise ValueError()
            admit_workflow(self._workflow, runtime=self._runtime, validators=dict(self._validators) or None)
            data = decode(self._encoded)
            if (data['workflow'] != self._workflow.fingerprint
                    or data['storeNamespace'] != self._store.namespace
                    or data['authorizer'] != _rule(self._authorizer, RunAuthorizer)
                    or data['confirmation'] != _rule(self._confirmation, ConfirmationRule)
                    or data['validators'] != {n: v.version for n, v in self._validators.items()}):
                raise ValueError()
            return data
        except Exception:
            raise ConversationError('bindingMismatch') from None


@dataclass(frozen=True, init=False, repr=False)
class ConversationBindings:
    _encoded: bytes
    _config: bytes
    _tools: object
    _journal: object
    _workspace: object
    _workflows: object
    _admitted: object
    _token_counters: object
    def __init__(self, agent, *, version, config, policy, run_policy, turn_limits=None,
                 custom_tools=None, operation_namespace=None, tool_journal=None,
                 workspace=None, workspace_identity=None, interpreter=None,
                 interpretation_policy=None, interpretation_schema=None, workflows=None,
                 context_policy=None, interpretation_context_policy=None, token_counters=None):
        try:
            reference(version)
            if type(policy) is not ConversationPolicy:
                raise ConversationError('bindingMismatch')
            policy.__post_init__()
            config_data = _config_payload(config)
            if config_data['tool_directories']:
                raise ConversationError('capabilityMissing')
            if 'conversation_turn_v1' not in ProsaicRuntime.capabilities:
                raise ConversationError('capabilityMissing')
            if workspace is not None:
                if not isinstance(workspace, (str, Path)) or not Path(workspace).is_absolute():
                    raise ConversationError('bindingMismatch')
                reference(workspace_identity)
                workspace = str(Path(workspace))
            elif workspace_identity is not None:
                raise ConversationError('bindingMismatch')
            InvocationScope('admission', operation_namespace=operation_namespace)
            operation = tool_journal_descriptor(tool_journal)
            if tool_journal is not None and operation_namespace is None:
                raise ConversationError('bindingMismatch')
            shared = {f.name: getattr(policy, f.name) for f in fields(TurnLimits)
                      if hasattr(policy, f.name)}
            # Both retained history and private evidence fit inside their new
            # record framing. Reserve structural capacity before any effects.
            shared['max_json_depth'] = policy.max_json_depth - 8
            shared['max_json_nodes'] = (policy.max_json_nodes - 8192) // 2
            evidence_room=policy.max_receipt_bytes-policy.max_turn_bytes-encoded_answer_bound(
                policy.max_assistant_bytes,policy.max_turn_bytes)-8192
            if context_policy is not None or interpretation_context_policy is not None:
                if 'context_assembly_v1' not in ProsaicRuntime.capabilities:
                    raise ConversationError('capabilityMissing')
                from .session_context import receipt_context_bounds
                evidence_room -= receipt_context_bounds()[0]
                if evidence_room < 1024:
                    raise ConversationError('sessionLimit', 'maxReceiptBytes')
            limits = TurnLimits(**shared,max_evidence_bytes=min(TurnLimits().max_evidence_bytes,evidence_room)) if turn_limits is None else turn_limits
            if type(limits) is not TurnLimits:
                raise ConversationError('bindingMismatch')
            limits.__post_init__()
            if any(getattr(limits, key) != val for key, val in shared.items()):
                raise ConversationError('bindingMismatch')
            if limits.max_evidence_bytes>evidence_room: raise ConversationError('bindingMismatch')
            tools = validate_custom_tools(custom_tools)
            runtime = ProsaicRuntime(_config_from_json(encode(config_data).decode()), custom_tools=tools)
            approved = _artifact_snapshot(agent, maximum_depth=policy.max_json_depth,
                maximum_nodes=policy.max_json_nodes)
            invocation = _policy(run_policy)
            runtime.prepare_turn(approved, message='a', policy=run_policy, limits=limits, workspace=workspace)
            interpreting = None
            if interpreter is not None:
                if policy.max_assistant_bytes<64: raise ConversationError('bindingMismatch')
                interpret_policy = interpretation_policy or RunPolicy(timeout_s=30,
                    max_provider_requests=1, max_tool_calls=0, max_tool_rounds=1,
                    max_input_bytes=policy.max_input_bytes)
                material = _policy(interpret_policy)
                if (material['allowed_tools'] or material['read_roots'] or material['write_paths']
                        or material['forbidden_roots'] or material['initial_tool'] is not None
                        or material['max_tool_calls'] != 0 or material['max_provider_requests'] != 1
                        or material['max_tool_rounds'] != 1 or material['timeout_s'] > 30):
                    raise ConversationError('bindingMismatch')
                interpreting = _artifact_snapshot(interpreter)
                if interpreting.frontmatter.get('tools') not in (None, '', 'none', []):
                    raise ConversationError('bindingMismatch')
                runtime.prepare_turn(interpreting, message='a', policy=interpret_policy, limits=limits)
                interpreting = {'artifact': _artifact_data(interpreting), 'policy': material,
                                'schema': _interpretation_schema(interpretation_schema)}
            elif interpretation_policy is not None or interpretation_schema is not None:
                raise ConversationError('bindingMismatch')
            registered = dict(workflows or {})
            for alias, registration in registered.items():
                reference(alias)
                if type(registration) is not WorkflowRegistration:
                    raise ConversationError('bindingMismatch')
                registration.readmit()
            data = {'version': version, 'config': _logical_config(config_data),
                'artifact': _artifact_data(approved), 'policy': policy.to_dict(),
                'runPolicy': invocation, 'turnLimits': {f.name: getattr(limits, f.name) for f in fields(limits)},
                'tools': custom_descriptors(tools), 'operationNamespace': operation_namespace,
                'toolJournal': operation or None, 'workspaceIdentity': workspace_identity,
                'interpreter': interpreting, 'workflows': {k: v.readmit() for k,v in registered.items()}}
            context_data, owned_counters = _context_material(config, approved,
                ProsaicArtifact.from_inspection(interpreting['artifact']) if interpreting else None,
                context_policy, interpretation_context_policy, token_counters)
            data.update(context_data)
            for key, value in {'_encoded': encode(data), '_config': encode(config_data),
                '_tools': MappingProxyType(tools), '_journal': tool_journal, '_workspace': workspace,
                '_workflows': MappingProxyType(registered), '_admitted': _ADMITTED,
                '_token_counters': owned_counters}.items():
                object.__setattr__(self, key, value)
        except ConversationError:
            raise
        except TurnAdmissionError as exc:
            raise ConversationError('bindingMismatch', exc.limit) from None
        except Exception:
            raise ConversationError('bindingMismatch') from None
    @property
    def version(self):
        return decode(self._encoded)['version']
    @property
    def identity(self):
        return digest(decode(self._encoded))
    @property
    def config(self):
        return _config_from_json(self._config.decode())
    @property
    def policy(self):
        return ConversationPolicy(**decode(self._encoded)['policy'])
    @property
    def run_policy(self):
        return _policy_from(decode(self._encoded)['runPolicy'])
    @property
    def turn_limits(self):
        return TurnLimits(**decode(self._encoded)['turnLimits'])
    @property
    def agent(self):
        return ProsaicArtifact.from_inspection(decode(self._encoded)['artifact'])
    @property
    def tool_journal(self):
        return self._journal
    @property
    def interpretation_policy(self):
        data = decode(self._encoded)['interpreter']
        return _policy_from(data['policy']) if data else None
    @property
    def context_enabled(self):
        data = decode(self._encoded)
        return 'contextPolicy' in data or 'interpretationContextPolicy' in data
    @property
    def context_policy(self):
        document = decode(self._encoded).get('contextPolicy')
        if document is None: return None
        from prosaic_runtime import ContextPolicy
        return ContextPolicy.from_dict(document)
    @property
    def interpretation_context_policy(self):
        document = decode(self._encoded).get('interpretationContextPolicy')
        if document is None: return None
        from prosaic_runtime import ContextPolicy
        return ContextPolicy.from_dict(document)
    @property
    def token_counters(self):
        return self._token_counters
    def readmit(self):
        if 'conversation_turn_v1' not in ProsaicRuntime.capabilities:
            raise ConversationError('capabilityMissing')
        try:
            if self._admitted is not _ADMITTED:
                raise ValueError()
            data = decode(self._encoded)
            if (data['toolJournal'] != (tool_journal_descriptor(self._journal) or None)
                    or data['tools'] != custom_descriptors(validate_custom_tools(self._tools))
                    or data['workflows'] != {k: v.readmit() for k,v in self._workflows.items()}):
                raise ValueError()
            runtime = ProsaicRuntime(self.config, custom_tools=self._tools)
            context_data, _ = _context_material(self.config, self.agent,
                ProsaicArtifact.from_inspection(data['interpreter']['artifact']) if data['interpreter'] else None,
                self.context_policy, self.interpretation_context_policy, self._token_counters)
            expected = {key: value for key, value in data.items() if key in {
                'contextPolicy', 'contextCounter', 'interpretationContextPolicy', 'interpretationContextCounter'}}
            if context_data != expected: raise ValueError('context descriptor drift')
            runtime.prepare_turn(self.agent, message='a', policy=self.run_policy,
                                 limits=self.turn_limits, workspace=self._workspace)
            if data['interpreter']:
                runtime.prepare_turn(ProsaicArtifact.from_inspection(data['interpreter']['artifact']),
                    message='a', policy=self.interpretation_policy, limits=self.turn_limits)
            return data
        except Exception:
            raise ConversationError('bindingMismatch') from None
    def runtime(self):
        self.readmit()
        return ProsaicRuntime(self.config, custom_tools=self._tools)


def _context_material(config, agent, interpreter, ordinary, interpreting, registry):
    if ordinary is None and interpreting is None:
        return {}, None
    if 'context_assembly_v1' not in ProsaicRuntime.capabilities:
        raise ConversationError('capabilityMissing')
    from prosaic_runtime import ContextPolicy, TokenCounterRegistry
    if type(registry) is not TokenCounterRegistry:
        raise ConversationError('bindingMismatch')
    data, registrations = {}, {}
    for purpose, policy, artifact in (('context', ordinary, agent),
            ('interpretationContext', interpreting, interpreter)):
        if policy is None: continue
        if type(policy) is not ContextPolicy or artifact is None:
            raise ConversationError('bindingMismatch')
        policy = ContextPolicy.from_dict(policy.to_dict())
        tier = artifact.frontmatter.get('model_tier')
        profile = config.routes[tier] if tier is not None else config.default_profile
        endpoint = config.profiles[profile]
        if any(name in endpoint.features for name in ('max_completion_tokens', 'max_output_tokens')):
            raise ConversationError('capabilityMissing')
        entry = registry.resolve(policy.counter_identity)
        descriptor = entry.descriptor
        if ((descriptor.provider, descriptor.model) != (endpoint.provider, endpoint.model)
                or policy.context_window_tokens > descriptor.context_capacity_tokens):
            raise ConversationError('bindingMismatch')
        data[purpose + 'Policy'] = policy.to_dict()
        data[purpose + 'Counter'] = descriptor.to_dict()
        registrations[policy.counter_identity] = entry
    return data, TokenCounterRegistry(registrations)
