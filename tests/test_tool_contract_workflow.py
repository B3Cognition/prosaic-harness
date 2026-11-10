from dataclasses import replace
import json
import re
import pytest
import prosaic_runtime as runtime_api
import prosaic_harness as api
from test_workflow_rules_execution import rule_endpoint
from support.context_pack_cases import scope_case


def flow(cfg, *, calls=None, pack=False, checks=None, grant=lambda use: True):
    calls = [] if calls is None else calls
    schema = {'type': 'object', 'required': ['ok', 'citation'], 'properties': {
        'ok': {'type': 'boolean'}, 'citation': {'type': 'string'}}, 'additionalProperties': False}
    def lookup(args):
        calls.append(1)
        return runtime_api.ToolResultV1(data={'count': 14}, evidence=(runtime_api.EvidenceDraftV1(
            'graph', 'r1', 'PRIVATE-LOCATOR', '/count', 'Dependents'),))
    tool = runtime_api.CustomTool('lookup', 'Lookup', {'type': 'object', 'additionalProperties': False}, lookup, '1',
        max_result_bytes=8192, result_contract=runtime_api.ToolResultContractV1('1'), event_policy=runtime_api.ToolEventPolicyV1('1', {
            'count': runtime_api.ToolDisplayFieldV1('result', '/count')}))
    contracts = api.ToolContracts('host', '1', evidence_authorizer=runtime_api.EvidenceAuthorizerV1('sources', '1', grant),
        display_authorizer=runtime_api.ToolDisplayAuthorizerV1('viewer', '1', lambda use: True),
        citations=runtime_api.CitationPolicyV1('required'))
    body = 'Return JSON with ok and a citation.'
    guards = []
    if checks is not None:
        def check(stage, ctx):
            checks.append(1)
            if pack:
                assert ctx.authoritative_input_data['workflow']['request']['private'] == 'PRIVATE-FACT'
                assert 'PRIVATE-FACT' not in json.dumps(ctx.input_data)
            return runtime_api.Verdict(True)
        guards = [runtime_api.Guard('facts', '1', ('final',), check,
            input_access='authoritativeAndModel' if pack else 'model')]
        body += '\nALWAYS check facts. <!-- enforce: facts(stage=final, on_violation=fail) -->'
    agent = runtime_api.ProsaicArtifact.from_inspection({'id': 'approved', 'type': 'subagent',
        'frontmatter': {'name': 'analyst', 'description': 'Review evidence', 'tools': ['lookup']}, 'body': body})
    packs = None
    if pack:
        packs = api.ContextPackBindings(specs={'selected': api.ContextPackSpec('selected', '1', [
            api.ContextSlot('task', required=True)], task_source='task')}, sources={'task': api.InputSource('/task')},
            scope=scope_case(), authorizer=api.ContextAuthorizer('packs', '1', lambda use: True),
            agent_defaults={'analyst': 'selected'})
    cfg = replace(cfg, allowed_tools=frozenset({'lookup'}))
    factory = api.WorkflowFactory(catalog=api.WorkflowCatalog(agents={'analyst': agent}, schemas={'result': schema}),
        bindings=api.WorkflowBindings(config=cfg, custom_tools={'lookup': tool}, tool_contracts=contracts,
            guards=guards, context_packs=packs), policy=api.WorkflowPolicy(allowed_agents={'analyst'}, allowed_schemas={'result'},
                allowed_tools={'lookup'}, allowed_guards={'facts'}, max_provider_requests_per_invocation=2,
                max_tool_calls_per_invocation=1))
    return factory.build({'version': 1, 'start': 'review', 'steps': {
        'review': {'kind': 'agent', 'agent': 'analyst', 'schema': 'result', 'tools': ['lookup'], 'next': 'done'},
        'done': {'kind': 'finish', 'requires': ['review']}}})


def queue_answer(replies, *, pack=False):
    replies.append({'name': 'lookup', 'input': {}})
    def answer(payload):
        pattern = r'ctx_[0-9a-f]{64}' if pack else r'ev_[0-9a-f]{64}'
        source = re.search(pattern, json.dumps(payload)).group()
        return json.dumps({'ok': True, 'citation': f'[cite:{source}]'})
    replies.append(answer)


def controller(workflow, tmp_path, **options):
    store = api.FileRunStore(tmp_path / 'store', namespace='test')
    store.initialize(tool_contracts=True)
    return api.Harness(workflow, store=store, run_id='a' * 32, **options)


def yaml_flow(cfg,tmp_path,*,calls):
    import sys
    from pathlib import Path
    import yaml
    original=flow(cfg,calls=calls,pack=True)
    source=tmp_path/'.prosaic/subagents';source.mkdir(parents=True)
    artifact=original.artifacts['review']
    (source/'analyst.md').write_text('---\n'+yaml.safe_dump(artifact.frontmatter)+'---\n'+artifact.body+'\n')
    (tmp_path/'result.json').write_text(json.dumps(original.schemas['review']))
    endpoint=cfg.profiles['local']
    (tmp_path/'runtime.yml').write_text(yaml.safe_dump(dict(default_profile='local',allowed_tools=['lookup'],profiles={
        'local':dict(base_url=endpoint.base_url,model=endpoint.model,provider=endpoint.provider,features={'streaming':False})})))
    graph=json.loads(json.dumps(original.definition));graph.update(source='.prosaic',runtime='runtime.yml')
    graph['limits'].pop('max_tokens')
    graph['steps']['review'].update(agent='subagents/analyst.md',schema='result.json',contextPack='selected')
    path=tmp_path/'workflow.yml';path.write_text(yaml.safe_dump(graph))
    return api.Workflow.load(path,executable=str(Path(sys.executable).parent/'prosaic'),
        custom_tools=original.custom_tools,context_packs=original._context_packs,tool_contracts=original._tool_contracts)


def test_workflow_contract_records_capture_completed_effect_before_denied_projection(rule_endpoint, tmp_path):
    cfg, requests, replies = rule_endpoint
    calls = []
    workflow = flow(cfg, calls=calls, grant=lambda use: False)
    replies.append({'name': 'lookup', 'input': {}})
    harness = controller(workflow, tmp_path)
    state = harness.run({'task': 'Review', 'private': 'PRIVATE-FACT'})
    assert state['status'] == 'blocked' and state['version'] == 4
    assert len(requests) == 1 and calls == [1]
    receipt = harness.store.load_receipt(state['run_id'], state['invocations'][0]['id'])
    assert receipt['version'] == 3 and receipt['toolContractV1']['evidence']['toolAttempts'] == 1
    assert receipt['toolContractV1']['evidence']['toolContractV1']['evidence']['calls'][0]['status'] == 'completed'
    assert api.Harness(workflow, store=harness.store, run_id=state['run_id']).resume()['status'] == 'blocked'
    assert len(requests) == 1 and calls == [1]
