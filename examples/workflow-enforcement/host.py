"""Trusted application policy and public YAML/native workflow construction.

ALWAYS derive scope from accepted declared dependencies. NEVER trust changed_ids.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from prosaic_harness import Workflow, WorkflowBindings, WorkflowCatalog, WorkflowFactory, WorkflowPolicy
from prosaic_runtime import Guard, Verdict

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('_workflow_enforcement_checks', ROOT / 'checks.py')
_checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_checks)


def validate_request(request):
    return _checks._index(request, 'insights', 'id')


def validators():
    return _checks.validators()


def guard_check(stage, context):
    try:
        value = json.loads(context.draft)
        facts = context.input_data['workflow']
        if facts['version'] != 1 or facts['step'] != 'revised_review':
            return Verdict(False)
        errors = _checks.review_scope(value, SimpleNamespace(step=facts['step'],
            request=facts['request'], artifacts=facts['artifacts']))
        return Verdict(not errors)
    except (KeyError, ValueError, TypeError):
        return Verdict(False)


def guards():
    content = Path(__file__).read_bytes() + (ROOT / 'checks.py').read_bytes()
    version = 'workflow-review-v1:' + hashlib.sha256(content).hexdigest()
    return [Guard('review_scope', version, ('final',), guard_check)]


def workflow(*, mode='yaml', executable='prosaic'):
    flow = Workflow.load(ROOT / 'workflow.yml', executable=executable, guards=guards())
    if mode == 'yaml':
        return flow
    if mode != 'native':
        raise ValueError('mode must be yaml or native')
    definition = deepcopy(flow.definition)
    for key in ('source', 'runtime'):
        definition.pop(key)
    for name, step in definition['steps'].items():
        if step['kind'] == 'agent':
            step.update(agent=name, schema=name)
    return WorkflowFactory(
        catalog=WorkflowCatalog(agents=flow.artifacts, schemas=flow.schemas),
        bindings=WorkflowBindings(config=flow.config, validators=validators(), guards=guards(),
            rule_project=ROOT, rule_project_identity='workflow-enforcement-v1'),
        policy=WorkflowPolicy(allowed_agents=set(flow.artifacts), allowed_schemas=set(flow.schemas),
            allowed_validators={'review_scope', 'revision_shape'}, allowed_guards={'review_scope'},
            allowed_model_tiers={'fast'}, allow_agent_composition=True, max_calls=3,
            max_attempts=1, timeout_s=60, max_run_s=240,
            max_provider_requests_per_invocation=2, max_tool_calls_per_invocation=0),
    ).build(definition)
