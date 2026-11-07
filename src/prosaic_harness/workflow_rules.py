"""Workflow rule bindings over the public Runtime rule compiler.

ALWAYS compile trusted registrations and seal used declarations before effects.
NEVER execute guards during admission or infer permission from proposed tags.
"""
from dataclasses import dataclass
from pathlib import Path

from prosaic_runtime import ProsaicRuntime, compile_rules
from prosaic_runtime.rules import artifact_rules, turn_rules

from .conversation_rules import registrations, descriptors, source_options

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
        if (step.get('acquisition') or '{{args}}' in artifact.body
                or any(getattr(workflow.custom_tools.get(tool), 'terminal', False)
                       for tool in step.get('tools', []))):
            raise ValueError('workflow rules need API turns without acquisition, terminal tools or args interpolation')
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
