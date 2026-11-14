"""Host policy and closed receipt material for Runtime turn recovery."""
from dataclasses import dataclass, replace
import json

from prosaic_runtime import ProsaicRuntime, RuntimeAdapter

from .session_codec import owned


@dataclass(frozen=True)
class RecoveryOptions:
    rule_retries: int = 1
    correct_malformed_tool_calls: bool = False

    def __post_init__(self):
        if type(self.rule_retries) is not int or not 0 <= self.rule_retries <= 3:
            raise ValueError('rule_retries must be an integer from 0 to 3')
        if type(self.correct_malformed_tool_calls) is not bool:
            raise ValueError('correct_malformed_tool_calls must be boolean')

    def runtime_options(self):
        return {
            **({'rule_retries': self.rule_retries} if self.rule_retries != 1 else {}),
            **({'correct_malformed_tool_calls': True} if self.correct_malformed_tool_calls else {}),
        }

    def material(self):
        options = self.runtime_options()
        return {'guardedRecoveryV1': {'version': 1, **options}} if options else {}

    def check_runtime(self, runtime):
        if runtime is None:
            return
        if type(runtime) is RuntimeAdapter and not self.runtime_options():
            runtime = runtime.runtime
        if type(runtime) is ProsaicRuntime:
            if (runtime._rule_retries, runtime._correct_malformed_tool_calls) == (
                    self.rule_retries, self.correct_malformed_tool_calls):
                return
        elif not self.runtime_options():
            return
        raise ValueError('workflow recovery options mismatch')


CORRECTIONS = frozenset({
    'batchShape', 'terminalBatch', 'callShape', 'callIdentity',
    'functionShape', 'toolNotGranted', 'argumentsMalformed', 'argumentsTooLarge', 'argumentsSchema',
})
GROUPS = ('rulesDeclined', 'rulesRetried')


def _receipt(retries, declined, retried, corrections):
    return {'version': 1, 'ruleRetriesUsed': retries, 'rulesDeclined': declined,
            'rulesRetried': retried, 'toolRequestCorrections': corrections}


def validate_recovery(value, rules, *, provider_attempts=None, options=None):
    value = owned(value, maximum=262_144, nodes=1024)
    if (type(value) is not dict or value.keys() != _receipt(0, [], [], []).keys()
            or type(value['version']) is not int or value['version'] != 1):
        raise ValueError('guarded recovery receipt fields')
    retries, corrections = value['ruleRetriesUsed'], value['toolRequestCorrections']
    if type(retries) is not int or not 0 <= retries <= 3:
        raise ValueError('guarded recovery retry count')
    if (type(corrections) is not list or len(corrections) > 1
            or any(type(code) is not str or code not in CORRECTIONS for code in corrections)):
        raise ValueError('guarded recovery correction code')
    has_ids = False
    for key in GROUPS:
        ids = value[key]
        if (type(ids) is not list or len(ids) > 256
                or any(type(item) is not str for item in ids) or len(ids) != len(set(ids))
                or not set(ids) <= set(rules['violated'] if rules else ())):
            raise ValueError('guarded recovery rule IDs')
        has_ids |= bool(ids)
    if not (retries or corrections or has_ids):
        raise ValueError('empty guarded recovery receipt')
    if options is not None and (retries > options.rule_retries or (
            corrections and not options.correct_malformed_tool_calls)):
        raise ValueError('guarded recovery exceeds host policy')
    if value['rulesRetried'] and not retries:
        raise ValueError('guarded recovery retry IDs without a retry')
    if provider_attempts is not None and retries + len(corrections) > provider_attempts:
        raise ValueError('guarded recovery exceeds invocation attempts')
    return value


def recovery_receipt(turn, rules):
    value = _receipt(turn.rule_retries_used, list(turn.rules_declined),
                     list(turn.rules_retried), list(turn.tool_request_corrections))
    if any(value[key] for key in value if key != 'version'):
        return validate_recovery(value, rules, provider_attempts=turn.evidence.to_dict()['providerAttempts'])
    return None


def with_recovery(turn, result, rules):
    recovery = recovery_receipt(turn, rules)
    return replace(result, metadata={**result.metadata, 'guarded_recovery_v1': recovery}) if recovery else result


def recovery_bound(ids, options):
    if not ids and not options.correct_malformed_tool_calls:
        return 0
    corrections = [max(CORRECTIONS, key=len)] if options.correct_malformed_tool_calls else []
    return len(json.dumps({'guarded_recovery_v1': _receipt(options.rule_retries, ids, ids, corrections)}))
