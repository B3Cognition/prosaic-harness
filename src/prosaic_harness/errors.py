"""Safe admission errors, independent of parsers and host execution bindings."""
import re


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
