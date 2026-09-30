"""Harbor blueprint checks, not generic Harness policy.

Quotes establish provenance, not entailment. A model/human must still assess
whether a paraphrase is supported. Numeric rules cover this fictional dataset.
"""
import math
import re


def catalogue(context):
    sources = {}
    rows = context.request.get('evidence', []) if isinstance(context.request, dict) else []
    rows = list(rows)
    for document in context.evidence.values():
        rows.extend(document['text'].splitlines())
    for row in rows:
        match = re.match(r'^\s*(?:-\s*)?(S\d+):\s*(.*)$', row)
        if match:
            source, text = match.groups()
            if source in sources and sources[source] != text:
                raise ValueError(f'ambiguous source ID {source}')
            sources[source] = text
    return sources


def evidence(output, context):
    sources = catalogue(context)
    issues = []
    for claim in output.get('claims', []):
        source = claim['source_id']
        if source not in sources:
            issues.append(f'unknown source ID {source}')
        elif not claim['quote'].strip() or claim['quote'] not in sources[source]:
            issues.append(f'{source}: supporting quote must be an exact excerpt from that source, not another ID')
    for source in output.get('citations', []):
        if source not in sources:
            issues.append(f'unknown citation {source}')
    # Catch unknown inline IDs too; this does not validate the surrounding claim.
    for field in ('summary', 'rationale', 'facts', 'unknowns', 'conditions'):
        text = output.get(field, '')
        text = ' '.join(text) if isinstance(text, list) else text
        for source in re.findall(r'\bS\d+\b', text):
            if source not in sources:
                issues.append(f'unknown inline source {source}')
    rules = {}
    if '2,400 request attempts' in sources.get('S2', ''):
        rules = {'client_visible_failure_rate': ('S2', 84, 2400), 'timeout_rate': ('S2', 60, 2400),
                 'checklist_completeness': ('S4', 108, 120), 'dashboard_explicit_error_rate': ('S2', 24, 2400)}
    elif '120 requests' in sources.get('S1', '') and 'Three requests timed out' in sources.get('S2', ''):
        rules = {'timeout_rate': ('S2', 3, 120), 'client_visible_failure_rate': ('S2', 3, 120)}
    for calculation in output.get('calculations', []):
        metric = calculation['metric']
        expected = rules.get(metric)
        actual = (calculation['source_id'], calculation['numerator'], calculation['denominator'])
        if expected is None or actual != expected:
            issues.append(f'{metric}: unsupported metric or denominator; preserve checklist sampling and include client-visible timeouts')
        elif not math.isclose(calculation['percentage'], 100 * expected[1] / expected[2], abs_tol=0.001):
            issues.append(f'{metric}: incorrect percentage')
    return issues


CHECKS = {'evidence': evidence}
