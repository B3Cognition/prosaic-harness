"""Receipt-bound host completion; no model text or tool status grants success."""
from prosaic_runtime.terminal import binding, validate_evidence
from prosaic_runtime.terminal import content_digest
from prosaic_runtime.accounting import ResolvedContext, identifier
from prosaic_runtime.policy import requested_tools


def effective_tools(workflow, step_name, policy):
    step = workflow.definition['steps'][step_name]
    if policy is None or step['kind'] != 'agent':
        return frozenset()
    requested = requested_tools(workflow.artifacts[step_name].frontmatter.get('tools'))
    return (policy.allowed_terminal_tools & frozenset(step.get('tools', ())) &
            workflow.config.allowed_tools & requested)


def validate_candidate(workflow, receipt, policy):
    """Return an owned terminal candidate only after matching actual dispatch."""
    enabled = effective_tools(workflow, receipt['step'], policy)
    value = receipt['result']['metadata'].get('terminalCompletion')
    if not enabled:
        if value is not None:
            raise ValueError('terminal completion was not admitted')
        return None
    if value is None:
        raise ValueError('terminal completion is missing')
    import json
    value = validate_evidence(value, output=json.loads(receipt['result']['stdout']), check_output=True)
    if (value['invocationId'] != receipt['id'] or value['runId'] != receipt['run_id']
            or value['stepId'] != receipt['step'] or value['toolName'] not in enabled):
        raise ValueError('terminal invocation mismatch')
    descriptor = workflow.tool_descriptors.get(value['toolName'], {})
    if descriptor.get('terminal') is not True or descriptor.get('version') != value['toolVersion']:
        raise ValueError('terminal registration mismatch')
    matching = [event for event in receipt['events'] if
        event.get('turn') == value['turn'] and event.get('call_id') == value['toolCallId']
        and event.get('event') in {'tool_started', 'tool_completed'}]
    starts = [e for e in matching if e['event'] == 'tool_started']
    ends = [e for e in matching if e['event'] == 'tool_completed']
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError('terminal tool pair mismatch')
    for event in matching:
        if event.get('name') != value['toolName'] or event.get('tool_version') != value['toolVersion']:
            raise ValueError('terminal tool identity mismatch')
    if (starts[0].get('argumentsSha256') != value['argumentsSha256']
            or ends[0].get('terminalCompletion') != binding(value)
            or ends[0].get('status') != 'ok'
            or ends[0].get('tool_outcome', {}).get('code') != 'ok'
            or sum('terminalCompletion' in e for e in receipt['events']) != 1):
        raise ValueError('terminal tool evidence mismatch')
    return value


def failure_evidence(metadata):
    """A bounded failure breadcrumb is never a replacement for a stored artifact."""
    if type(metadata) is not dict:
        return {}
    safe = {}
    budget = metadata.get('invocation_budgets_v1')
    if (type(budget) is dict and set(budget) == {'provider_requests', 'tool_calls',
            'reported_tokens', 'usage_complete'} and type(budget['usage_complete']) is bool
            and all(type(budget[k]) is int and 0 <= budget[k] < 2**256
                for k in ('provider_requests', 'tool_calls', 'reported_tokens'))):
        safe['invocation_budgets_v1'] = dict(budget)
    value = metadata.get('terminalCompletion')
    if type(value) is dict:
        try:
            value = validate_evidence(value, complete=value.get('artifactIncluded') is True)
            value = binding(value)
            value['artifactIncluded'] = False
            safe['terminalCompletion'] = validate_evidence(value, complete=False)
        except (ValueError, TypeError, KeyError, OverflowError):
            pass
    return safe


def accounting_evidence(value, *, compact=False):
    """Retain attribution and either actual IDs or their explicit bounded link."""
    if type(value) is not dict:
        raise ValueError('invalid accounting evidence')
    context = ResolvedContext.from_dict(value['context'])
    result = {'context': context.to_dict()}
    for key in ('namespace', 'environment'):
        item = value.get(key)
        if item is not None:
            identifier(item)
        result[key] = item
    if 'provider_call_ids' in value:
        calls = value['provider_call_ids']
        if type(calls) is not list:
            raise ValueError('invalid accounting call IDs')
        for call in calls:
            identifier(call)
        if compact:
            result['providerCallBinding'] = {'version': 1, 'count': len(calls),
                                              'sha256': content_digest(calls)}
        else:
            result['provider_call_ids'] = list(calls)
    else:
        import re
        link = value.get('providerCallBinding')
        if link is None:
            link = {'version': 1, 'count': None, 'sha256': None}
        if (type(link) is not dict or set(link) != {'version', 'count', 'sha256'}
                or type(link['version']) is not int or link['version'] != 1
                or not (link['count'] is None and link['sha256'] is None or
                    type(link['count']) is int and 0 <= link['count'] < 2**256
                    and type(link['sha256']) is str and re.fullmatch('[0-9a-f]{64}', link['sha256']))):
            raise ValueError('invalid accounting linkage')
        result['providerCallBinding'] = dict(link)
    return result
