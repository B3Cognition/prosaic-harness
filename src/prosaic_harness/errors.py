"""Safe admission errors, independent of parsers and host execution bindings."""
import re
from types import MappingProxyType
from jsonschema import Draft202012Validator


_FIELDS = frozenset({'definition', 'inline_agents', 'version', 'name', 'start', 'steps',
    'limits', 'kind', 'agent', 'schema', 'response_schema', 'resources', 'acquisition',
    'read_roots', 'require_reads', 'inputs', 'optional_inputs', 'next', 'max_attempts',
    'max_visits', 'max_calls', 'timeout_s', 'max_tokens', 'max_run_s', 'tools',
    'require_tools', 'validators', 'from', 'field', 'equals', 'pass', 'fail',
    'question', 'choices', 'requires', 'outcome', 'frontmatter', 'body', 'model_tier'})


class _LogicalAlias(str):
    pass


def logical_alias(value):
    """Mark a validated graph/catalogue alias; arbitrary property keys stay opaque."""
    if type(value) is str and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', value):
        return _LogicalAlias(value)
    return '*'


def logical_location(*parts):
    """Build a trusted logical path without copying client property/parser text."""
    path = '$'
    for part in parts:
        if type(part) is int and part >= 0:
            fragment = f'[{part}]' if part < 1_048_576 else '[*]'
        elif isinstance(part, _LogicalAlias) or type(part) is str and part in _FIELDS:
            fragment = '.' + part
        else:
            fragment = '.*'
        if len(path) + len(fragment) > 256:
            break
        path += fragment
    return path


class GraphAdmissionError(ValueError):
    """Internal diagnostic retaining legacy ValueError text and a trusted field."""
    def __init__(self, message, location):
        self.location = location
        super().__init__(message)


class WorkflowAdmissionError(ValueError):
    """A stable code and bounded field location, without source data or causes."""

    CODES = frozenset({'invalid_definition', 'invalid_artifact', 'invalid_schema',
                       'unknown_reference', 'policy_denied', 'limit_exceeded',
                       'resource_not_bound', 'binding_mismatch', 'identity_mismatch'})

    def __init__(self, code, location='$'):
        if code not in self.CODES:
            raise ValueError('unknown admission error code')
        self.code = code
        # Locations are supplied by trusted adapters, never parser exception text.
        self.location = ''.join(c for c in str(location)[:256]
                                if c.isascii() and (c.isalnum() or c in '$._[]-*')) or '$'
        super().__init__(f'{self.code} at {self.location}')


class HumanResponseError(ValueError):
    """Safe response diagnostics; product-validator prose is never public."""
    MESSAGES = {
        'expected_revision_required': 'expected_revision is required for this response',
        'invalid_choice': 'choice is not declared by the pending pause',
        'response_requires_choice': 'response requires a declared choice',
        'response_not_allowed': 'pause has no response schema',
        'response_limit': 'human response exceeds its data limit',
        'response_schema_invalid': 'human response failed schema validation',
        'response_validation_failed': 'human response failed validation',
        'no_pending_choice': 'run has no pending human choice',
        'completed_run': 'completed run has no pending choice',
    }
    CODES = frozenset(MESSAGES)
    ISSUE_CODES = frozenset(Draft202012Validator.VALIDATORS) | {'schema'}

    def __init__(self, code, issues=()):
        if code not in self.CODES:
            raise ValueError('unknown human response error code')
        self.code = code
        safe = []
        for issue in issues[:5]:
            name, location = issue.get('code'), issue.get('location')
            safe.append(MappingProxyType({
                'code': name if type(name) is str and name in self.ISSUE_CODES else 'schema',
                'location': location if type(location) is str and len(location) <= 128
                    and re.fullmatch(r'\$(?:(?:\.\*)|(?:\[\d+\]))*', location) else '$'}))
        self.issues = tuple(safe)
        super().__init__(self.MESSAGES[code])

    def to_dict(self):
        return {'code': self.code, 'issues': [dict(issue) for issue in self.issues]}


def response_schema_issues(errors):
    """Translate the schema evaluator's safe, structural diagnostics only."""
    issues = []
    for error in errors[:5]:
        match = re.fullmatch(r'(\$(?:(?:\.\*)|(?:\[\d+\]))*): ([A-Za-z][A-Za-z0-9]*) validation failed', error)
        issues.append({'code': match[2] if match else 'schema',
                       'location': match[1] if match else '$'})
    return issues
