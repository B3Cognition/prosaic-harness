"""Host guard declarations and bounded, private rule receipt metadata.

ALWAYS bind trusted registrations before dispatch. NEVER serialize executable
guards or accept model-provided declarations as host policy.
"""
import re
from pathlib import Path

from .session_codec import owned, encode
from .guarded_recovery import recovery_bound

MAX_RULE_RECEIPT_BYTES = 262_144
_GROUPS = ('evaluated', 'violated', 'fixed', 'faulted')


def source_options(project):
    if project is None:
        return {}
    source = Path(project) / '.prosaic'
    if source.resolve().parent != Path(project):
        raise ValueError('rule project source escapes its declared root')
    return {'source': source}


def registrations(guards):
    """Validate and own guard declarations; callables remain trusted host objects."""
    if guards is None:
        return ()
    if type(guards) not in (list, tuple) or len(guards) > 256:
        raise ValueError('guard registrations')
    if not guards:
        return ()
    from prosaic_runtime import Guard
    result, names = [], set()
    for guard in guards:
        if type(guard) is not Guard or guard.name in names:
            raise ValueError('guard registration')
        names.add(guard.name)
        result.append(Guard(guard.name, guard.version, guard.stages, guard.check,
            fixes=guard.fixes, echo_values=guard.echo_values,
            settings_schema=guard.settings_schema, path_settings=guard.path_settings,
            **({'input_access':guard.input_access} if getattr(guard,'input_access','shared')!='shared' else {})))
    return tuple(result)


def descriptors(guards):
    """Complete logical declarations, ordered independently of registry input."""
    return owned([{'name': g.name, 'version': g.version, 'stages': list(g.stages),
        'settingsSchema': g.settings_schema, 'pathSettings': list(g.path_settings),
        'fixes': g.fixes, 'echoValues': g.echo_values,
        **({'inputAccess':g.input_access} if getattr(g,'input_access','shared')!='shared' else {})}
        for g in sorted(registrations(guards), key=lambda g: g.name)])


def requires_rule_support(inspection):
    """Detect inert metadata before a legacy Runtime converter can discard it."""
    if inspection.get('rules') or inspection.get('ruleIssues'):
        return True
    from prosaic import parse_rules
    texts = [(inspection['body'], inspection['id'])]
    texts += [(resource['content'], resource['relPath']) for resource in inspection.get('resources', [])
        if resource['relPath'].lower().endswith('.md')]
    return any(parsed['rules'] or parsed['issues'] for text, name in texts
        for parsed in (parse_rules(text, name),))


def validate_rule_receipt(value):
    """Closed versioned extension: ids and a hash only, never prose or reasons."""
    value = owned(value, maximum=MAX_RULE_RECEIPT_BYTES, nodes=2048)
    if type(value) is not dict or value.keys() != {'version', *_GROUPS, 'fingerprint'}:
        raise ValueError('rule receipt fields')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('rule receipt version')
    for key in _GROUPS:
        group = value[key]
        if (type(group) is not list or len(group) > 256 or
                any(type(item) is not str or not item for item in group) or len(set(group)) != len(group)):
            raise ValueError('rule receipt ids')
    if any(not set(value[key]) <= set(value['evaluated']) for key in _GROUPS[1:]):
        raise ValueError('unevaluated rule outcome')
    if not set(value['fixed']) <= set(value['violated']):
        raise ValueError('unviolated rule outcome')
    fingerprint = value['fingerprint']
    if fingerprint is None:
        if any(value[key] for key in _GROUPS):
            raise ValueError('missing rule fingerprint')
    elif type(fingerprint) is not str or not re.fullmatch('[0-9a-f]{64}', fingerprint):
        raise ValueError('rule fingerprint')
    return value


def rule_receipt(result):
    groups = {key: list(getattr(result, 'rules_' + key, ())) for key in _GROUPS}
    fingerprint = getattr(result, 'rules_fingerprint', None)
    if not any(groups.values()) and fingerprint is None:
        return None
    return validate_rule_receipt({'version': 1, **groups, 'fingerprint': fingerprint})


def receipt_bound(runtime, artifact, recovery=None):
    """Reserve the worst rule extension before provider spend, including all outcomes."""
    if 'rule_admission_v1' not in runtime.capabilities:
        return 0
    coverage = runtime.rule_coverage(artifact)
    ids = coverage['registered'] + coverage['unregistered']
    if not ids:
        return recovery_bound([], recovery) if recovery is not None else 0
    largest = validate_rule_receipt({'version': 1, **dict.fromkeys(_GROUPS, ids), 'fingerprint': 'f'*64})
    size = len(encode({'rules': largest}))
    return size + recovery_bound(ids, recovery) + 1 if recovery is not None else size
