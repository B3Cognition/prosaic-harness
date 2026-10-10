"""Pure invariants over already resolved workflow inputs."""
from pathlib import Path
import os
import re

from prosaic import validate_artifact_definition
from prosaic_runtime import validate_execution_artifact
from prosaic_runtime.policy import READ_TOOLS, BUILTIN_TOOLS, requested_tools

from .schema_validation import admit_schema
from .errors import GraphAdmissionError, logical_location, logical_alias


STEP_KEYS = {
    'agent': {'kind', 'agent', 'acquisition', 'schema', 'inputs', 'optional_inputs', 'next',
              'max_attempts', 'max_visits', 'tools', 'read_roots', 'require_tools', 'require_reads', 'validators'},
    'gate': {'kind', 'from', 'field', 'equals', 'pass', 'fail', 'max_visits'},
    'check': {'kind', 'from', 'validators', 'pass', 'fail', 'max_visits'},
    'pause': {'kind', 'question', 'choices', 'max_visits', 'requires', 'response_schema', 'validators'},
    'finish': {'kind', 'outcome', 'max_visits', 'requires'},
}
LIMIT_KEYS = {'max_calls', 'max_visits', 'timeout_s', 'max_tokens', 'max_run_s'}
ROOT_KEYS = {'version', 'name', 'start', 'limits', 'steps', 'source', 'runtime', 'evidence'}


def _positive(value, label):
    if type(value) is not int or value <= 0:
        raise ValueError(f'{label} must be a positive integer')


def _strings(value, label, *, unique=False, empty=False):
    if type(value) is not list or any(type(item) is not str or (not empty and not item) for item in value):
        raise ValueError(f'{label} must be a list of names')
    if unique and len(set(value)) != len(value):
        raise ValueError(f'{label} must be unique')


def _lexical_local(root, value):
    if type(value) is not str or '\x00' in value:
        raise ValueError('file paths must be strings')
    path = Path(os.path.normpath(str(root / value)))
    if not path.is_relative_to(root):
        raise ValueError('file path escapes workflow directory')
    return path


def validate_resolved_workflow(workflow, *, descriptors, profile=None, native=False):
    """Validate without resolving files, preparing adapters, or executing code.

    Descriptors come from trusted actual registrations, never from a proposed hash.
    The return value is the descriptor subset demanded by resolved prose.
    """
    raw = workflow.definition
    if type(raw) is not dict or set(raw) - ROOT_KEYS or type(raw.get('version')) is not int or raw['version'] != 1:
        raise ValueError('invalid workflow keys or version')
    if native and set(raw) & {'source', 'runtime', 'evidence'}:
        raise ValueError('native workflows cannot introduce filesystem bindings')
    if not native:
        if (not isinstance(workflow.path, Path) or not workflow.path.is_absolute()
                or workflow.path.suffix not in {'.yml', '.yaml'}):
            raise ValueError('legacy workflows require an explicit YAML path; use WorkflowFactory')
        if not isinstance(raw.get('runtime'), str) or not raw['runtime']:
            raise ValueError('legacy workflow requires its runtime binding')
        _lexical_local(workflow.path.parent, raw['runtime'])
        _lexical_local(workflow.path.parent, raw.get('source', '.prosaic'))
    steps = raw.get('steps')
    if type(steps) is not dict or not steps or type(raw.get('start')) is not str or raw['start'] not in steps:
        raise ValueError('workflow needs steps and a valid start')
    if any(type(step) is not dict for step in steps.values()):
        raise ValueError('every step must be a mapping')
    limits = raw.get('limits')
    if type(limits) is not dict or set(limits) - LIMIT_KEYS or {'max_calls', 'max_visits', 'timeout_s'} - limits.keys():
        raise ValueError('workflow needs effective valid limits')
    for key, value in limits.items():
        _positive(value, key)
    evidence = raw.get('evidence', [])
    _strings(evidence, 'evidence', unique=True)
    if len(evidence) > 64 or any(Path(item).is_absolute() or '..' in Path(item).parts for item in evidence):
        raise ValueError('evidence must use at most 64 confined relative files')
    demanded, artifact_steps, schema_steps, acquisition_steps = {}, set(), set(), set()
    for name, step in steps.items():
        if type(name) is not str or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]*', name):
            raise ValueError('step identifiers must be simple names')
        kind = step.get('kind')
        if kind not in STEP_KEYS or set(step) - STEP_KEYS[kind]:
            raise GraphAdmissionError('unsupported step or keys', logical_location(
                'definition', 'steps', logical_alias(name), 'kind' if kind not in STEP_KEYS else '*'))
        if native and set(step) & {'acquisition', 'read_roots', 'require_reads'}:
            raise ValueError('native workflows cannot introduce filesystem bindings')
        _positive(step.get('max_visits', limits['max_visits']), 'max_visits')
        validators = step.get('validators', [])
        _strings(validators, 'validators', unique=True)
        requires = step.get('requires', [])
        _strings(requires, 'requires')
        if any(ref not in steps or steps[ref].get('kind') != 'agent' for ref in requires):
            raise ValueError('requires must reference agent steps')
        targets = []
        if kind == 'agent':
            artifact_steps.add(name)
            schema_steps.add(name)
            _positive(step.get('max_attempts', 2), 'max_attempts')
            if type(step.get('agent')) is not str or not step['agent'] or type(step.get('schema')) is not str or not step['schema']:
                raise ValueError('agent and schema references are required')
            targets = [step.get('next')]
            for field in ('inputs', 'optional_inputs'):
                refs = step.get(field, [])
                _strings(refs, field)
                if any(ref not in steps or steps[ref].get('kind') != 'agent' for ref in refs):
                    raise ValueError('agent inputs must reference agent steps')
            granted = step.get('tools', [])
            _strings(granted, 'tools')
            allowed = set(descriptors) if native else set(descriptors) | READ_TOOLS
            if set(granted) - allowed or set(granted) - workflow.config.allowed_tools:
                raise GraphAdmissionError('agent tool grants need registered permitted implementations',
                    logical_location('definition', 'steps', logical_alias(name), 'tools'))
            required = step.get('require_tools', [])
            _strings(required, 'require_tools')
            if set(required) - set(granted):
                raise ValueError('require_tools must be a subset of granted tools')
            roots = step.get('read_roots', [])
            _strings(roots, 'read_roots', empty=not native)
            if set(granted) & READ_TOOLS and not roots:
                raise ValueError('read tools require explicit read_roots')
            reads = step.get('require_reads', [])
            _strings(reads, 'require_reads')
            if any(path not in evidence for path in reads):
                raise ValueError('require_reads must reference declared evidence')
            if not native:
                root = workflow.path.parent
                resolved_roots = [_lexical_local(root, path) for path in roots]
                if reads and ('read_file' not in granted or any(not any(_lexical_local(root, path).is_relative_to(base)
                        for base in resolved_roots) for path in reads)):
                    raise ValueError('require_reads needs scoped read_file')
            artifact = workflow.artifacts.get(name)
            if artifact is None:
                raise ValueError('resolved artifact is missing')
            canonical = validate_artifact_definition(artifact.type, artifact.frontmatter)
            if not canonical['ok']:
                raise ValueError('invalid canonical artifact')
            acquisition = workflow.acquisitions.get(name)
            if 'acquisition' in step:
                acquisition_steps.add(name)
                if acquisition is None or not reads:
                    raise ValueError('acquisition needs resolved prose and required reads')
                if not validate_artifact_definition(acquisition.type, acquisition.frontmatter)['ok']:
                    raise ValueError('invalid canonical acquisition')
            elif acquisition is not None:
                raise ValueError('undeclared acquisition')
            validate_execution_artifact(artifact, workflow.config, acquisition=acquisition)
            requested = requested_tools(artifact.frontmatter.get('tools'))
            if requested - BUILTIN_TOOLS - descriptors.keys():
                raise ValueError('prose requests unsupported tools')
            if set(required) - requested or (reads and 'read_file' not in requested):
                raise ValueError('prose must request required tools')
            if acquisition is not None and 'read_file' not in requested_tools(acquisition.frontmatter.get('tools')):
                raise ValueError('acquisition must request read_file')
            demanded.update({tool: descriptors[tool] for tool in requested & descriptors.keys()})
        elif kind in {'gate', 'check'}:
            ref = step.get('from')
            if type(ref) is not str or ref not in steps or steps[ref].get('kind') != 'agent':
                raise ValueError('gate/check must reference an agent step')
            if kind == 'gate':
                _strings(step.get('field'), 'gate field', empty=True)
                if not step['field'] or 'equals' not in step:
                    raise ValueError('gate needs field and equals')
            elif not validators:
                raise ValueError('check steps need validators')
            targets = [step.get('pass'), step.get('fail')]
        elif kind == 'pause':
            if type(step.get('question')) is not str or not step['question']:
                raise ValueError('pause needs a question')
            choices = step.get('choices')
            if type(choices) is not dict or not choices or any(type(choice) is not str or not choice for choice in choices):
                raise ValueError('pause needs named choices')
            targets = list(choices.values())
            if 'response_schema' in step:
                if type(step['response_schema']) is not str or not step['response_schema']:
                    raise ValueError('pause needs a schema reference')
                schema_steps.add(name)
            elif validators:
                raise ValueError('pause validators require a response schema')
        elif step.get('outcome', 'completed') not in {'completed', 'rejected'}:
            raise ValueError('invalid finish outcome')
        if any(type(target) is not str or target not in steps for target in targets):
            field = 'next' if kind == 'agent' else 'choices' if kind == 'pause' else (
                'pass' if type(step.get('pass')) is not str or step.get('pass') not in steps else 'fail')
            raise GraphAdmissionError('unknown transition target', logical_location(
                'definition', 'steps', logical_alias(name), field))
    if set(workflow.artifacts) != artifact_steps or set(workflow.schemas) != schema_steps or set(workflow.acquisitions) != acquisition_steps:
        raise ValueError('resolved content does not match graph references')
    for schema in workflow.schemas.values():
        admit_schema(schema, profile=profile)
    return demanded
