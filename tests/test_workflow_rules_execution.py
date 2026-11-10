"""Real guarded turns, host-owned dependency facts and bounded rule repair."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import pytest
from prosaic_harness import Harness, WorkflowBindings, WorkflowCatalog, WorkflowFactory, WorkflowPolicy
from prosaic_runtime import EndpointConfig, Guard, ProsaicArtifact, RuntimeConfig, Verdict
from test_workflow_rules_admission import SCHEMA, CAPS, artifact, definition, factory, guard


@pytest.fixture(params=['openai-compatible', 'anthropic'])
def rule_endpoint(request):
    requests, replies = [], []
    provider = request.param
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            answer = replies.pop(0)
            if callable(answer): answer = answer(requests[-1])
            tool = answer if isinstance(answer, dict) else None
            if provider == 'anthropic':
                body = {'id': 'fixture', 'type': 'message', 'role': 'assistant', 'model': 'synthetic',
                    'content': ([{'type': 'tool_use', 'id': 'call1', 'name': tool['name'], 'input': tool['input']}] if tool else [{'type': 'text', 'text': answer}]), 'stop_reason': 'tool_use' if tool else 'end_turn',
                    'usage': {'input_tokens': 2, 'output_tokens': 3}}
            else:
                body = {'choices': [{'message': ({'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call1', 'type': 'function', 'function': {'name': tool['name'], 'arguments': json.dumps(tool['input'])}}]} if tool else {'role': 'assistant', 'content': answer}), 'finish_reason': 'tool_calls' if tool else 'stop'}],
                    'usage': {'total_tokens': 5}}
            data = json.dumps(body).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    cfg = RuntimeConfig({'local': EndpointConfig(f'http://127.0.0.1:{server.server_port}/v1',
        'synthetic', provider=provider, max_tokens=128, features={'streaming': False})}, {}, 'local', frozenset())
    try: yield cfg, requests, replies
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        assert not thread.is_alive()


def strict(stage, context):
    return Verdict(json.loads(context.draft).get('ok') is True)


def test_retry_uses_one_invocation_and_keeps_durable_rule_proof(rule_endpoint, tmp_path):
    cfg, requests, replies = rule_endpoint
    replies.extend(['{"ok":false}', '{"ok":true}'])
    flow = factory(cfg=cfg, registered=[guard(check=strict)]).build(definition())
    controller = Harness(flow, tmp_path / 'run')
    state = controller.run({'workflow': {'step': 'forged'}, 'private': 'nested-request'})
    assert state['status'] == 'completed' and state['calls'] == 1 and len(requests) == 2
    assert state['outputs']['review'] == {'ok': True}
    receipt = controller.store.load_receipt('legacy', state['invocations'][0]['id'])
    proof = receipt['result']['metadata']['workflow_rules_v1']
    assert proof['version'] == 1 and len(proof['facts_sha256']) == len(proof['context_identity']) == 64
    assert proof['rules']['evaluated'] and proof['rules']['violated']
    assert Harness(flow, tmp_path / 'run').resume()['status'] == 'completed' and len(requests) == 2


@pytest.mark.parametrize('action,cap,raises', [('retry', 1, False), ('retry', 2, False), ('fail', 2, False), ('retry', 2, True)])
def test_rule_refusal_is_terminal_without_outer_retry(rule_endpoint, tmp_path, action, cap, raises):
    cfg, requests, replies = rule_endpoint
    def check(*args):
        if raises: raise RuntimeError('private guard fault')
        return Verdict(False)
    replies.extend(['{"ok":false}'] * 3)
    flow = factory(cfg=cfg, registered=[guard(check=check)],
        body=f'ALWAYS check. <!-- enforce: review_scope(stage=final, on_violation={action}) -->',
        policy_options={'max_provider_requests_per_invocation': cap}).build(definition())
    state = Harness(flow, tmp_path / 'run').run({})
    assert state['status'] == 'blocked' and state['reason'] == 'rule_violation'
    assert state['calls'] == 1 and len(requests) <= cap
    count = len(requests)
    assert Harness(flow, tmp_path / 'run').resume()['reason'] == 'rule_violation'
    assert len(requests) == count


def test_guard_gets_only_declared_accepted_dependencies_and_private_views(rule_endpoint, tmp_path):
    cfg, requests, replies = rule_endpoint
    seen = []
    def check(stage, context):
        facts = context.input_data['workflow']; seen.append(json.loads(json.dumps(facts)))
        facts['artifacts'].clear()
        return Verdict(True)
    g = guard(check=check)
    f = WorkflowFactory(catalog=WorkflowCatalog(agents={'first': artifact('Return JSON.'), 'guarded': artifact()},
        schemas={'result': SCHEMA}), bindings=WorkflowBindings(config=cfg, guards=[g]),
        policy=WorkflowPolicy(allowed_agents={'first', 'guarded'}, allowed_schemas={'result'},
            allowed_guards={'review_scope'}, allow_agent_composition=True, **CAPS))
    graph = definition(); graph['start'] = 'first'
    graph['steps']['first'] = {'kind': 'agent', 'agent': 'first', 'schema': 'result', 'next': 'review'}
    graph['steps']['review'].update(agent='guarded', inputs=['first'])
    replies.extend(['{"ok":true}', '{"ok":true}'])
    state = Harness(f.build(graph), tmp_path / 'run').run({'step': 'forged', 'artifacts': {'forged': {}}})
    assert state['status'] == 'completed'
    assert seen[0]['version'] == 1 and seen[0]['step'] == 'review'
    assert seen[0]['artifacts'] == {'first': {'ok': True}}
    assert seen[0]['request'] == {'step': 'forged', 'artifacts': {'forged': {}}}
    assert state['outputs']['first'] == {'ok': True}
    assert 'workflow' in json.dumps(requests[-1])


@pytest.mark.parametrize('limit', ['max_invocation_bytes', 'max_metadata_bytes', 'max_receipt_bytes'])
def test_unretainable_guarded_input_or_proof_refuses_before_pending(rule_endpoint, tmp_path, limit):
    cfg, requests, replies = rule_endpoint
    flow = factory(cfg=cfg, policy_options={limit: 32}).build(definition())
    state = Harness(flow, tmp_path / 'run').run({})
    assert state['status'] == 'blocked' and state['calls'] == 0 and state['pending'] is None
    assert requests == []


@pytest.mark.parametrize('action', ['fail', 'fix'])
def test_final_fail_and_fix_actions_remain_runtime_owned(rule_endpoint, tmp_path, action):
    cfg, requests, replies = rule_endpoint; replies.append('{"ok":false}')
    def check(stage, context):
        return Verdict(json.loads(context.draft)['ok'], fixed='{"ok":true}' if action == 'fix' else None)
    flow = factory(cfg=cfg, registered=[guard(check=check, fixes=action == 'fix')],
        body=f'ALWAYS check. <!-- enforce: review_scope(stage=final, on_violation={action}) -->').build(definition())
    h=Harness(flow, tmp_path / 'run'); state=h.run({})
    assert state['status'] == ('completed' if action == 'fix' else 'blocked')
    assert len(requests) == 1
    receipt=h.store.load_receipt('legacy',state['invocations'][0]['id'])
    assert bool(receipt['result']['metadata']['workflow_rules_v1']['rules']['fixed']) == (action == 'fix')


def test_all_four_rule_phases_receive_same_host_facts(rule_endpoint, tmp_path):
    from prosaic_runtime import CustomTool
    cfg, requests, replies = rule_endpoint; stages=[]; tool_calls=[]
    cfg=replace(cfg, allowed_tools=frozenset({'lookup'}))
    def check(stage, context):
        stages.append((stage, context.input_data['workflow']))
        return Verdict(True)
    phases=('before_tool','after_tool','before_answer','final')
    guards=[Guard('scope_'+stage,'all-phases-v1',(stage,),check) for stage in phases]
    body='\n'.join(f'ALWAYS check {stage}. <!-- enforce: scope_{stage}(stage={stage}, on_violation=fail) -->'
        for stage in phases)
    a=ProsaicArtifact.from_inspection({'id':'all.md','type':'subagent',
        'frontmatter':{'name':'all','description':'All stages','tools':['lookup']},'body':body})
    tool=CustomTool('lookup','Synthetic lookup',{'type':'object','properties':{},'additionalProperties':False},
        lambda value: tool_calls.append(value) or {'ok':True},'v1')
    f=WorkflowFactory(catalog=WorkflowCatalog(agents={'reviewer':a},schemas={'result':SCHEMA}),
        bindings=WorkflowBindings(config=cfg,custom_tools={'lookup':tool},guards=guards),
        policy=WorkflowPolicy(allowed_agents={'reviewer'},allowed_schemas={'result'},allowed_tools={'lookup'},
            allowed_guards={g.name for g in guards},max_provider_requests_per_invocation=2,max_tool_calls_per_invocation=1))
    graph=definition();graph['steps']['review'].update(tools=['lookup'],require_tools=['lookup'])
    replies.extend([{'name':'lookup','input':{}},'{"ok":true}'])
    state=Harness(f.build(graph),tmp_path/'run').run({'trusted':'host'})
    assert state['status']=='completed' and len(requests)==2 and tool_calls==[{}]
    assert {stage for stage,_ in stages}==set(phases)
    assert all(facts['request']=={'trusted':'host'} and facts['artifacts']=={} for _,facts in stages)


def test_present_stale_optional_dependency_refuses_before_guard_or_pending(rule_endpoint, tmp_path):
    cfg, requests, replies = rule_endpoint; seen=[]
    f=WorkflowFactory(catalog=WorkflowCatalog(agents={'plain':artifact('Return JSON.'),'guarded':artifact()},
        schemas={'result':SCHEMA}), bindings=WorkflowBindings(config=cfg,
            guards=[guard(check=lambda *args: seen.append(args) or Verdict(True))]),
        policy=WorkflowPolicy(allowed_agents={'plain','guarded'},allowed_schemas={'result'},
            allowed_guards={'review_scope'},allow_agent_composition=True,**CAPS))
    graph=definition();graph['start']='base'
    graph['steps'].update({
        'base':{'kind':'agent','agent':'plain','schema':'result','next':'choose'},
        'choose':{'kind':'gate','from':'base','field':['ok'],'equals':True,'pass':'selected','fail':'review'},
        'selected':{'kind':'agent','agent':'plain','schema':'result','inputs':['base'],'next':'base'},
    })
    graph['steps']['review'].update(agent='guarded',optional_inputs=['selected'])
    replies.extend(['{"ok":true}','{"ok":true}','{"ok":false}','{"ok":true}'])
    state=Harness(f.build(graph),tmp_path/'run').run({})
    assert state['status']=='blocked' and state['reason']=='stale_artifact'
    assert state['calls']==3 and state['pending'] is None and len(requests)==3 and seen==[]


def test_single_explicit_yaml_request_cap_is_honored_for_untagged_step(rule_endpoint, tmp_path):
    import yaml
    from test_workflow_rules_admission import yaml_project, load
    cfg, requests, replies = rule_endpoint
    path=yaml_project(tmp_path,tagged=False,caps=False)
    runtime=path.with_name('runtime.yml');config=yaml.safe_load(runtime.read_text())
    endpoint=cfg.profiles['local']
    config['profiles']['local'].update(base_url=endpoint.base_url,provider=endpoint.provider,max_tokens=128)
    runtime.write_text(yaml.safe_dump(config))
    document=yaml.safe_load(path.read_text())
    document['limits']['max_provider_requests_per_invocation']=0
    path.write_text(yaml.safe_dump(document));replies.append('{"ok":true}')
    state=Harness(load(path),tmp_path/'run').run({})
    assert state['status']=='blocked' and requests==[]


@pytest.mark.parametrize('stage', ['before_tool', 'after_tool', 'before_answer'])
def test_each_nonfinal_phase_can_block_workflow_acceptance(rule_endpoint, tmp_path, stage):
    from prosaic_runtime import CustomTool
    cfg, requests, replies=rule_endpoint; calls=[]
    cfg=replace(cfg,allowed_tools=frozenset({'lookup'}))
    g=Guard('scope','fail-'+stage,(stage,),lambda *args: Verdict(False))
    body=f'ALWAYS check scope. <!-- enforce: scope(stage={stage}, on_violation=fail) -->'
    a=ProsaicArtifact.from_inspection({'id':'scope.md','type':'subagent',
        'frontmatter':{'name':'scope','description':'Synthetic fail','tools':['lookup']},'body':body})
    tool=CustomTool('lookup','Synthetic lookup',{'type':'object','additionalProperties':False},
        lambda value: calls.append(value) or {'ok':True},'v1')
    f=WorkflowFactory(catalog=WorkflowCatalog(agents={'reviewer':a},schemas={'result':SCHEMA}),
        bindings=WorkflowBindings(config=cfg,custom_tools={'lookup':tool},guards=[g]),
        policy=WorkflowPolicy(allowed_agents={'reviewer'},allowed_schemas={'result'},allowed_tools={'lookup'},
            allowed_guards={'scope'},max_provider_requests_per_invocation=2,max_tool_calls_per_invocation=1))
    graph=definition();graph['steps']['review']['tools']=['lookup']
    replies.extend([{'name':'lookup','input':{}},'{"ok":true}'])
    state=Harness(f.build(graph),tmp_path/'run').run({})
    assert state['status']=='blocked' and state['reason']=='rule_violation' and state['calls']==1
    assert 'review' not in state['outputs'] and calls==([] if stage=='before_tool' else [{}])
