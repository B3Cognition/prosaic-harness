"""Installed-only safe events, captured citations, receipt adoption; no paid inference."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from tempfile import TemporaryDirectory
from pathlib import Path
from importlib import metadata
import json,re,sys
import prosaic_runtime as runtime
import prosaic_harness as harness


def check_origins():
    distributions={'prosaic':'b3-prosaic','prosaic_runtime':'b3-prosaic-runtime','prosaic_harness':'b3-prosaic-harness'}
    for prefix,distribution in distributions.items():
        owner=metadata.distribution(distribution);files={Path(owner.locate_file(f)).resolve() for f in owner.files}
        direct=owner.read_text('direct_url.json')
        assert direct is None or not json.loads(direct).get('dir_info',{}).get('editable',False)
        for name,module in tuple(sys.modules.items()):
            if name.split('.')[0]==prefix and getattr(module,'__file__',None):
                path=Path(module.__file__).resolve();assert 'site-packages' in path.parts and path in files
    return {name:metadata.version(name) for name in distributions.values()}


def run(provider):
    requests=[];calls=[];events=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(request)
            second=len(requests)==2
            text='14 dependents [cite:'+re.search(r'ev_[0-9a-f]{64}',json.dumps(request)).group()+']' if second else None
            if provider=='anthropic':
                result={'id':'fixture','type':'message','role':'assistant','model':'fixture','content':(
                    [{'type':'text','text':text}] if second else [{'type':'tool_use','id':'one','name':'dependents','input':{'component':'csb-frontend','secret':'PRIVATE-ARG'}}]),
                    'stop_reason':'end_turn' if second else 'tool_use','usage':{'input_tokens':2,'output_tokens':3}}
            else:
                result={'choices':[{'message':({'role':'assistant','content':text} if second else {'role':'assistant','content':None,
                    'tool_calls':[{'id':'one','type':'function','function':{'name':'dependents','arguments':json.dumps({'component':'csb-frontend','secret':'PRIVATE-ARG'})}}]}),
                    'finish_reason':'stop' if second else 'tool_calls'}],'usage':{'total_tokens':5}}
            body=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        def handler(args):
            calls.append(1)
            return runtime.ToolResultV1(data={'count':14},evidence=(runtime.EvidenceDraftV1('graph','r1','PRIVATE-LOCATOR','/count','Dependents'),))
        tool=runtime.CustomTool('dependents','Read actual dependents',{'type':'object','required':['component','secret'],
            'properties':{'component':{'type':'string'},'secret':{'type':'string'}},'additionalProperties':False},handler,'1',max_result_bytes=8192,
            result_contract=runtime.ToolResultContractV1('1'),event_policy=runtime.ToolEventPolicyV1('1',{
                'component':runtime.ToolDisplayFieldV1('arguments','/component'),'count':runtime.ToolDisplayFieldV1('result','/count')}))
        contracts=harness.ToolContracts('host','1',evidence_authorizer=runtime.EvidenceAuthorizerV1('sources','1',lambda use:True),
            display_authorizer=runtime.ToolDisplayAuthorizerV1('display','1',lambda use:True),citations=runtime.CitationPolicyV1('required'))
        config=runtime.RuntimeConfig({'local':runtime.EndpointConfig(f'http://127.0.0.1:{server.server_port}/v1','fixture',provider=provider,
            features={'streaming':False})},{},'local',frozenset({'dependents'}))
        agent=runtime.ProsaicArtifact('analyst','subagent',{'name':'analyst','description':'Fixture','tools':['dependents']},'ALWAYS use captured evidence and cite it.')
        bindings=harness.ConversationBindings(agent,version='fixture-1',config=config,policy=harness.ConversationPolicy(),custom_tools={'dependents':tool},
            run_policy=runtime.RunPolicy(allowed_tools=frozenset({'dependents'}),max_provider_requests=2,max_tool_calls=1),tool_contracts=contracts)
        with TemporaryDirectory() as temporary:
            store=harness.FileSessionStore(Path(temporary).resolve()/'sessions',namespace='tool-smoke');store.initialize(tool_contracts=True)
            scope=harness.ConversationScope('tool-smoke','sandbox','fixture','tenant','actor')
            chat=harness.Conversation(bindings,store=store,scope=scope);session=chat.create()
            def crash(event):
                events.append(event)
                if event['event']=='receiptSaved':raise OSError('fixture lost acknowledgment')
            try:chat.send(session.session_id,message_id='one',message='Find dependents',expected_revision=session.revision,on_event=crash)
            except (OSError,harness.StoreUnavailable):pass
            reopened=harness.FileSessionStore(Path(temporary).resolve()/'sessions',namespace='tool-smoke')
            result=harness.Conversation(bindings,store=reopened,scope=scope).recover(session.session_id)
            assert result.document['status']=='completed' and result.document['citations']['markers']
            assert calls==[1] and len(requests)==2
            assert all(secret not in json.dumps(events) for secret in ('PRIVATE-ARG','PRIVATE-LOCATOR'))
            assert any(event.get('toolEventV1',{}).get('display',{}).get('count')==14 for event in events)
            # Events-only adoption leaves existing callback return/framing intact.
            plain=runtime.CustomTool('plain','Legacy',{'type':'object','additionalProperties':False},lambda args:{'legacy':True},'1')
            direct=runtime.ProsaicRuntime(replace(config,allowed_tools=frozenset({'plain'})),custom_tools={'plain':plain}).run_tool('plain',{},
                policy=runtime.RunPolicy(allowed_tools=frozenset({'plain'})),operation_context=runtime.InvocationScope('legacy'),
                tool_contract_bindings=runtime.ToolContractBindingsV1('events','1',runtime.InvocationScope('legacy')))
            assert direct.exit_code==0 and json.loads(direct.stdout)=={'legacy':True}
        return {'provider':provider,'providerRequests':len(requests),'effects':len(calls),'receiptAdopted':True}
    finally:
        server.shutdown();server.server_close();thread.join(5);assert not thread.is_alive()


if __name__=='__main__':
    outcomes=[run(provider) for provider in ('openai-compatible','anthropic')]
    print(json.dumps({'passed':True,'versions':check_origins(),'cases':outcomes},sort_keys=True))
