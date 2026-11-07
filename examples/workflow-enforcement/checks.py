"""Application-owned example policy: a second review is scoped to flagged/changed insights."""
import hashlib
from pathlib import Path
import re

from prosaic_harness import Validator

_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z')


def _index(document, field, id_field):
    values = document[field]
    if type(values) is not list or len(values) > 256:
        raise ValueError()
    result = {}
    for item in values:
        if type(item) is not dict or type(item.get(id_field)) is not str or _ID.fullmatch(item[id_field]) is None:
            raise ValueError()
        if item[id_field] in result or type(item.get('text')) is not str or not 1 <= len(item['text']) <= 4096:
            raise ValueError()
        result[item[id_field]] = item['text']
    return result


def review_scope(output, context):
    """Reject unknown scope using accepted data, never a model's claimed changed_ids."""
    try:
        original = _index(context.request, 'insights', 'id')
        findings = _index(output, 'findings', 'insight_id')
        if context.step == 'first_review':
            allowed = set(original)
        elif context.step == 'revised_review':
            flagged = _index(context.artifacts['first_review'], 'findings', 'insight_id')
            if not set(flagged) <= original.keys():
                raise ValueError()
            revised = _index(context.artifacts['revision'], 'insights', 'id')
            changed = {key for key, text in revised.items() if key not in original or text != original[key]}
            allowed = (set(flagged) | changed) & revised.keys()
        else:
            raise ValueError()
        if not set(findings) <= allowed:
            return ['Findings must target current insight IDs that were previously flagged or whose text changed.']
        return []
    except (KeyError, TypeError, ValueError, AttributeError):
        return ['Review scope requires well-formed original insights and accepted first-review/revision dependencies.']


def revision_shape(output, context):
    try:
        _index(output, 'insights', 'id')
        return []
    except (KeyError, TypeError, ValueError):
        return ['The complete revised insight list must have unique nonempty IDs and text.']


CHECKS = {'review_scope': review_scope, 'revision_shape': revision_shape}


def validators():
    # Include actual implementation content, so a code edit cannot silently reuse V1's receipt identity.
    version = 'revision-review-v1:' + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {name: Validator(version, check) for name, check in CHECKS.items()}
