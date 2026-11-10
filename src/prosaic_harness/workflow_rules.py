"""Workflow rule bindings over the public Runtime rule compiler.

ALWAYS compile trusted registrations and seal used declarations before effects.
NEVER execute guards during admission or infer permission from proposed tags.
"""
from dataclasses import dataclass
from pathlib import Path
import re

from prosaic_runtime import ProsaicRuntime, compile_rules
from prosaic_runtime.rules import artifact_rules, turn_rules

from .conversation_rules import registrations, descriptors, source_options
from .conversation_rules import rule_receipt, validate_rule_receipt
from .session_codec import owned

CAPS = ('max_provider_requests_per_invocation', 'max_tool_calls_per_invocation')
FACT_PROFILE = 'workflow-guard-input-v1'


@dataclass(frozen=True)
class RuleBindings:
    guards: tuple = ()
    project: Path | None = None
    identity: str | None = None
    allowed: frozenset | None = None

    @classmethod
    def create(cls, guards=(), project=None, identity=None, allowed=None):
        if project is None:
            if identity is not None:
                raise ValueError('rule project identity requires a project')
        else:
            if not Path(project).is_absolute() or type(identity) is not str or not identity or len(identity.encode()) > 128:
                raise ValueError('rule project requires an absolute host root and bounded logical identity')
            project = Path(project).resolve()
            source_options(project)
        return cls(registrations(guards), project, identity, allowed)

    def runtime_options(self):
        return {'guards': self.guards, **source_options(self.project)} if self.guards or self.project else {}

    def bundle_material(self):
        return {'guards': descriptors(self.guards), 'project': self.identity} if self.guards or self.project else None


def compiled(workflow):
    bindings = getattr(workflow, '_rule_bindings', RuleBindings())
    result = {}
    for name, artifact in workflow.artifacts.items():
        entries, issues = artifact_rules(artifact)
        rules = compile_rules(entries, bindings.guards, issues=issues,
            required_guards=workflow.config.required_guards, project_root=bindings.project, warn=False)
        if not rules.bindings:
            continue
        step = workflow.definition['steps'][name]
        if (step.get('acquisition') or step.get('require_reads') or '{{args}}' in artifact.body
                or any(getattr(workflow.custom_tools.get(tool), 'terminal', False)
                       for tool in step.get('tools', []))):
            raise ValueError('workflow rules need API turns without acquisition, required read receipts, terminal tools or args interpolation')
        if bindings.allowed is not None and any(b.guard_name not in bindings.allowed for b in rules.bindings):
            raise ValueError('workflow guard is not host permitted')
        limits = workflow.definition['limits']
        if any(type(limits.get(key)) is not int or limits[key] < 0 for key in CAPS):
            raise ValueError('workflow rules require finite explicit invocation caps')
        result[name] = rules
    return result


def material(workflow):
    rules = compiled(workflow)
    if not rules:
        return {}
    bindings = workflow._rule_bindings
    used = {b.guard_name for ruleset in rules.values() for b in ruleset.bindings}
    return {'workflow_rules': {'version': 1, 'facts': FACT_PROFILE,
        'project': bindings.identity,
        'guards': descriptors([g for g in bindings.guards if g.name in used]),
        'steps': {name: value.material() for name, value in rules.items()}}}


def check_runtime(workflow, runtime):
    expected = compiled(workflow)
    if not expected or runtime is None:
        return
    if type(runtime) is not ProsaicRuntime or not {'rule_admission_v1', 'conversation_turn_v1'} <= runtime.capabilities:
        raise ValueError('workflow rules require the supported guarded Runtime')
    for name, rules in expected.items():
        actual = turn_rules(runtime, workflow.artifacts[name], warn=False)
        if (actual.material() != rules.material()
                or descriptors_unique(actual) != descriptors_unique(rules)
                or [b.paths for b in actual.bindings] != [b.paths for b in rules.bindings]):
            raise ValueError('workflow rule binding mismatch')


def descriptors_unique(rules):
    return descriptors(list({b.guard.name: b.guard for b in rules.bindings}.values()))


def dependency_bindings(workflow, step, arguments):
    """Retain the exact accepted bindings that supplied authoritative guard facts."""
    from copy import deepcopy
    definition = workflow.definition['steps'][step]
    selected = arguments['artifact_bindings']
    refs = list(definition.get('inputs', []))
    if step in compiled(workflow):
        refs += [ref for ref in definition.get('optional_inputs', []) if ref in selected]
    return {ref: deepcopy(selected[ref]) for ref in refs}


def facts(step, arguments):
    return owned({'workflow': {**arguments, 'version': 1, 'step': step}})


def proof(step, arguments, context_identity, rules):
    from .workflow import digest
    return {'version': 1, 'facts_sha256': digest(facts(step, arguments)),
        'context_identity': context_identity, 'rules': validate_rule_receipt(rules)}


def maximum_proof(workflow, step, arguments):
    rules = compiled(workflow)[step]
    ids = [b.rule_id for b in rules.bindings]
    return proof(step, arguments, 'f' * 64, {'version': 1, 'fingerprint': rules.rules_fingerprint(),
        **{key: ids for key in ('evaluated', 'violated', 'fixed', 'faulted')}})


def result_with_proof(turn, step, arguments, prepared):
    from dataclasses import replace
    rules = rule_receipt(turn)
    if rules is None:
        raise ValueError('missing guarded Runtime evidence')
    return replace(turn.result, metadata={**turn.result.metadata,
        'workflow_rules_v1': proof(step, arguments, prepared.context_identity, rules)})


def validate_proof(value, workflow, step, arguments, *, success=False):
    from .workflow import digest
    value = owned(value, maximum=262_144, nodes=4096)
    if (type(value) is not dict or value.keys() != {'version', 'facts_sha256', 'context_identity', 'rules'}
            or type(value['version']) is not int or value['version'] != 1
            or value['facts_sha256'] != digest(facts(step, arguments))
            or type(value['context_identity']) is not str or not re.fullmatch('[0-9a-f]{64}', value['context_identity'])):
        raise ValueError('workflow rule proof identity')
    rules = compiled(workflow)[step]
    receipt = validate_rule_receipt(value['rules'])
    ids = {b.rule_id for b in rules.bindings}
    required = {b.rule_id for b in rules.bindings if b.stage in {'before_answer', 'final'}}
    if (receipt['fingerprint'] != rules.rules_fingerprint() or not set(receipt['evaluated']) <= ids
            or success and (not required <= set(receipt['evaluated']) or receipt['faulted'])):
        raise ValueError('workflow rule proof coverage')
    return value


def pack_proof(frame,rules):
    from .workflow import digest
    from .context_packs.codec import digest as input_digest
    from .context_packs.projection import MODEL_PROFILE,AUTHORITATIVE_PROFILE
    frozen=frame.frozen_input.to_dict();projection=frame.projection
    if frame.to_dict()['version']==2:
        from .context_packs.tool_contracts import MODEL_PROFILE
    if projection is None: raise ValueError('workflow pack projection missing')
    views=frozen['inputViews']
    if (views['model']!={'profile':MODEL_PROFILE,'digest':input_digest(frozen['selectedInputData'])}
            or views['authoritative']!={'profile':AUTHORITATIVE_PROFILE,'digest':input_digest(projection['authoritativeInputData'])}):
        raise ValueError('workflow pack input views mismatch')
    return dict(version=2,originalFactsSha256=digest(projection['authoritativeInputData']),inputViews=views,
        packReference=frame.selected_pack_reference,contextIdentity=frozen['contextIdentity'],rules=validate_rule_receipt(rules))


def result_with_pack_proof(turn,frame):
    from dataclasses import replace
    rules=rule_receipt(turn)
    if rules is None: raise ValueError('missing guarded Runtime evidence')
    return replace(turn.result,metadata={**turn.result.metadata,'workflow_rules_v2':pack_proof(frame,rules)})


def validate_pack_proof(value,workflow,step,frame,result,*,success=False):
    from .context_packs.codec import encode
    expected=pack_proof(frame,result['rules'])
    if encode(value)!=encode(expected): raise ValueError('workflow pack proof mismatch')
    rules=compiled(workflow)[step];receipt=validate_rule_receipt(value['rules'])
    ids={b.rule_id for b in rules.bindings}
    required={b.rule_id for b in rules.bindings if b.stage in {'before_answer','final'}}
    if (receipt['fingerprint']!=rules.rules_fingerprint() or set(receipt['evaluated'])-ids
            or success and (required-set(receipt['evaluated']) or receipt['faulted'])):
        raise ValueError('workflow pack proof coverage')
    return value
