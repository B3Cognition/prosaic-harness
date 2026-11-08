"""Installed context-pack workflows, conversations, and default-capacity witness.

Only synthetic loopback inference is used. PostgreSQL is explicitly supplied;
the caller owns provisioning, migration permissions, and cleanup.
"""
import argparse
from dataclasses import replace
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
import uuid
import yaml

import prosaic_runtime as runtime
from prosaic_harness import (Workflow,Harness,FileRunStore,Validator,ContextPackBindings,ContextAuthorizer,
    ContextScope,InputSource,EvidenceSource,ArtifactSource,ContextPackSpec,ContextSlot,ContextPacker,
    ContextPackReader,Conversation,ConversationBindings,ConversationPolicy,ConversationScope,MemorySessionStore,FileSessionStore)
from prosaic_harness.context_packs import capture_sources

fixture=runpy.run_path(str(Path(__file__).with_name('conversation_smoke.py')))


class Interrupted(BaseException): pass


class ReceiptInterruptingFileStore(FileRunStore):
    def save_receipt(self,*args,**kwargs):
        super().save_receipt(*args,**kwargs)
        raise Interrupted()


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(value): return hashlib.sha256(canonical(value)).hexdigest()


def origins(include_postgres):
    result=fixture['installed_origins'](include_postgres)
    import prosaic_runtime_postgres
    assert prosaic_runtime_postgres.__version__=='0.3.0'
    distributions={'prosaic':'b3-prosaic','prosaic_runtime':'b3-prosaic-runtime',
        'prosaic_harness':'b3-prosaic-harness','prosaic_runtime_postgres':'b3-prosaic-runtime-postgres'}
    if include_postgres: distributions['prosaic_harness_postgres']='b3-prosaic-harness-postgres'
    for prefix,distribution in distributions.items():
        owner=metadata.distribution(distribution)
        files={Path(owner.locate_file(f)).resolve() for f in owner.files}
        direct=owner.read_text('direct_url.json')
        assert direct is None or not json.loads(direct).get('dir_info',{}).get('editable',False)
        for name,module in tuple(sys.modules.items()):
            if name.split('.')[0]==prefix and getattr(module,'__file__',None):
                path=Path(module.__file__).resolve()
                assert 'site-packages' in path.parts and path in files,(name,str(path))
    return result


def config(url,tools=()):
    return runtime.RuntimeConfig({'local':runtime.EndpointConfig(url,'synthetic-context-pack',max_tokens=128,
        features={'streaming':False})},{},'local',frozenset(tools))


def markdown_workflow(root,url,requests,replies):
    (root/'.prosaic/subagents').mkdir(parents=True)
    (root/'requirements.md').write_text('REQUIREMENTS-214: return valid structured evidence.')
    (root/'constraints.md').write_text('CONSTRAINTS-317: preserve accepted evidence.')
    (root/'.prosaic/subagents/worker.md').write_text('---\nname: worker\ndescription: Selected workflow context\n---\n'
        'ALWAYS validate captured facts. <!-- enforce: facts(stage=final, on_violation=fail) -->\nNEVER invent facts.\n')
    (root/'result.json').write_text(json.dumps({'type':'object','required':['ok'],
        'properties':{'ok':{'type':'boolean'}},'additionalProperties':False}))
    (root/'runtime.yml').write_text(yaml.safe_dump({'default_profile':'local','profiles':{'local':{
        'base_url':url,'model':'synthetic-context-pack','max_tokens':128,'features':{'streaming':False}}}}))
    definitions={alias:{'version':'1','taskSource':'task','slots':[{'source':source,'required':True} for source in sources]}
        for alias,sources in (('implementation',('task','requirements','constraints')),('review',('task','requirements','candidate')))}
    definition={'version':1,'source':'.prosaic','runtime':'runtime.yml','evidence':['requirements.md','constraints.md'],
        'contextPacks':definitions,'agentContextPacks':{'subagents/worker.md':'implementation'},'start':'build',
        'limits':{'timeout_s':10,'max_provider_requests_per_invocation':2,'max_tool_calls_per_invocation':0},
        'steps':{'build':{'kind':'agent','agent':'subagents/worker.md','schema':'result.json','validators':['check'],'next':'review'},
            'review':{'kind':'agent','agent':'subagents/worker.md','schema':'result.json','contextPack':'review',
                'inputs':['build'],'next':'done'},'done':{'kind':'finish','requires':['review']}}}
    path=root/'workflow.yml';path.write_text(yaml.safe_dump(definition))
    scope=ContextScope('test','sandbox','pack-smoke','tenant','actor')
    bindings=ContextPackBindings(specs={},sources={'task':InputSource('/task'),'requirements':EvidenceSource('requirements.md'),
        'constraints':EvidenceSource('constraints.md'),'candidate':ArtifactSource('build')},scope=scope,
        authorizer=ContextAuthorizer('access','1',lambda use:True))
    checks=[];guards=[]
    def guard(stage,context):
        assert context.authoritative_input_data['workflow']['request']['private']=='UNDECLARED-BUSINESS-884'
        assert 'UNDECLARED-BUSINESS-884' not in json.dumps(context.input_data)
        guards.append(stage);return runtime.Verdict(True)
    def validator(output,context):
        assert context.request['private']=='UNDECLARED-BUSINESS-884'
        checks.append(context.step)
        return ['PRIVATE-DIAGNOSTIC-884'] if len(checks)==1 else []
    validators={'check':Validator('1',validator)}
    workflow=Workflow.load(path,executable=str(Path(sys.executable).parent/'prosaic'),context_packs=bindings,
        guards=[runtime.Guard('facts','1',('final',),guard,input_access='authoritativeAndModel')],repeatable_validators=['check'])
    store=ReceiptInterruptingFileStore(root/'storage',namespace='test');store.initialize(context_packs=True)
    events=[];sid=uuid.uuid4().hex
    controller=Harness(workflow,store=store,run_id=sid,validators=validators,on_event=events.append)
    replies.extend([fixture['answer']('{"ok":true}')]*3)
    before=len(requests)
    try: controller.run({'task':'Review supplied requirements','private':'UNDECLARED-BUSINESS-884'})
    except Interrupted: pass
    else: raise AssertionError('receipt interruption was not reached')
    assert len(requests)==before+1 and len(guards)==1 and checks==[]
    reopened=FileRunStore(root/'storage',namespace='test')
    result=Harness(workflow,store=reopened,run_id=sid,validators=validators,on_event=events.append).resume()
    assert result['status']=='completed' and len(requests)==before+3 and len(guards)==3
    first,last=json.dumps(requests[before]),json.dumps(requests[-1])
    assert 'CONSTRAINTS-317' in first and 'CONSTRAINTS-317' not in last
    assert 'REQUIREMENTS-214' in first and 'REQUIREMENTS-214' in last
    public=json.dumps([requests[before:],events])
    assert 'PRIVATE-DIAGNOSTIC-884' not in public and 'UNDECLARED-BUSINESS-884' not in public
    assert 'safe-feedback-v1' in public
    return {'nodes':2,'providerRequests':3,'guardCalls':3,'restartAdopted':True}


def tool_answer(citation,call):
    return 200,{'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{
        'id':str(call),'type':'function','function':{'name':'read_context_item','arguments':json.dumps({'citationId':citation})}}]},
        'finish_reason':'tool_calls'}],'usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5}}


def capacity_workflow(root,url,requests,replies):
    """Real controller records, finite default quotas, and two full reader results."""
    reader=ContextPackReader();scope=ContextScope('test','sandbox','pack-smoke','tenant','actor')
    # Eight substantial Markdown bodies, six small bodies, a task, and one
    # accepted structured lookup are exactly sixteen captured items.
    evidence={f'facts-{i}.md':('INLINE-FACT-'+str(i)+' '+('x'*1536) if i<8 else 'DISCOVERABLE-FACT-'+str(i)) for i in range(14)}
    for path,text in evidence.items(): (root/path).write_text(text)
    sources={'task':InputSource('/task'),'lookup':ArtifactSource('lookup'),
        **{f'facts{i}':EvidenceSource(path) for i,path in enumerate(evidence)}}
    slots=[ContextSlot('task',required=True),*[ContextSlot(f'facts{i}',required=True) for i in range(8)],
        ContextSlot('lookup',availability='discoverable',representation={'kind':'jsonPointer','pointer':'/a'}),
        ContextSlot('lookup',availability='discoverable',representation={'kind':'jsonPointer','pointer':'/b'}),
        *[ContextSlot(f'facts{i}',availability='discoverable') for i in range(8,14)]]
    spec=ContextPackSpec('capacity','1',slots,task_source='task')
    packs=ContextPackBindings(specs={'capacity':spec},sources=sources,scope=scope,
        authorizer=ContextAuthorizer('access','1',lambda use:True))
    output={'a':'\x01'*100,'b':'\x01'*100}
    lookup=runtime.CustomTool('lookup_records','Return captured structured records',{'type':'object','additionalProperties':False},
        lambda arguments:output,'1',max_result_bytes=65536)
    seen=[]
    def check(stage,context):
        assert len(canonical(context.authoritative_input_data))>=65536
        assert 'PRIVATE-CAPACITY-884' in json.dumps(context.authoritative_input_data)
        assert 'PRIVATE-CAPACITY-884' not in json.dumps(context.input_data)
        seen.append(stage);return runtime.Verdict(True)
    (root/'.prosaic/subagents').mkdir(parents=True)
    (root/'.prosaic/subagents/worker.md').write_text('---\nname: worker\ndescription: Read captured records\n'
        'tools: [read_context_item]\n---\nALWAYS check captured facts. <!-- enforce: facts(stage=final, on_violation=fail) -->\nNEVER invent facts.\n')
    (root/'result.json').write_text('{"type":"object"}')
    (root/'runtime.yml').write_text(yaml.safe_dump({'default_profile':'local','allowed_tools':['lookup_records','read_context_item'],
        'profiles':{'local':{'base_url':url,'model':'synthetic-context-pack','max_tokens':128,'features':{'streaming':False}}}}))
    definitions={'capacity':{'version':'1','taskSource':'task','slots':[slot.to_dict() for slot in slots]}}
    graph={'version':1,'source':'.prosaic','runtime':'runtime.yml','evidence':list(evidence),'contextPacks':definitions,
        'start':'lookup','limits':{'timeout_s':10,'max_provider_requests_per_invocation':3,'max_tool_calls_per_invocation':2},
        'steps':{'lookup':{'kind':'tool','tool':'lookup_records','arguments':{},'schema':'result.json','next':'review'},
            'review':{'kind':'agent','agent':'subagents/worker.md','schema':'result.json','contextPack':'capacity',
                'tools':['read_context_item'],'require_tools':['read_context_item'],'optional_inputs':['lookup'],'next':'done'},
            'done':{'kind':'finish','requires':['review']}}}
    (root/'workflow.yml').write_text(yaml.safe_dump(graph))
    workflow=Workflow.load(root/'workflow.yml',executable=str(Path(sys.executable).parent/'prosaic'),context_packs=packs,
        custom_tools={'lookup_records':lookup,'read_context_item':reader.as_tool()},allowed_direct_tools=frozenset({'lookup_records'}),
        guards=[runtime.Guard('facts','1',('final',),check,input_access='authoritativeAndModel')])
    inputs={'task':'Review accepted records','private':'PRIVATE-CAPACITY-884'}
    def arguments_case():
        return {'request':inputs,'artifacts':{'lookup':output},'artifact_bindings':{'lookup':{
            'id':'0'*32,'sha256':hashlib.sha256(json.dumps(output,sort_keys=True,allow_nan=False).encode()).hexdigest(),
            'dependencies':{},'contextPackIdentity':None,'contextSourceRevisions':None}},'sources':workflow.snapshot(),'validation_feedback':None}
    def captured():
        return ContextPacker().compose(spec,capture_sources(spec,arguments_case(),workflow.snapshot(),packs))
    preliminary=captured();pack=ContextPacker().select(preliminary,0,digest(preliminary.variants[0]))
    grant=next(value for value in pack.envelope['index'] if value['sourceAlias']=='lookup')
    source=next(value for value in pack.snapshot.sources if value.alias=='lookup')
    item=next(value for value in pack.snapshot.items if value.source_alias=='lookup')
    template={key:grant[key] for key in ('citationId','sourceAlias','sourceRevision','itemId')}
    template.update(sourceIdentity=source.source_identity,sourceLocator=item.locator,snapshotDigest=pack.snapshot.identity,
        packReference=pack.reference,representation={'kind':'jsonPointer','pointer':'/a'},content='',contentKind='text',
        contentSha256='0'*64,complete=False,nextOffset=None,continuationAvailable=False)
    empty=len(json.dumps({'status':'ok','result':template},allow_nan=False).encode())
    size=(24576-empty)//6
    output.update(a='\x01'*size,b='\x01'*size)
    private_bytes=len(canonical({'workflow':{**arguments_case(),'version':1,'step':'review'}}))
    inputs['private']+='p'*max(0,65536-private_bytes)
    candidates=captured();assert len(candidates.snapshot.items)==16 and len(canonical(candidates.snapshot.to_dict()))>=32768
    assert len(canonical({'contextPack':candidates.variants[0]}))>=16384
    store=FileRunStore(root/'storage',namespace='test');store.initialize(context_packs=True)
    controller=Harness(workflow,store=store,run_id=uuid.uuid4().hex)
    before=len(requests)
    # Citation identities include the real accepted producer binding. Queue
    # each reader call from the actual first dispatched model envelope.
    def progress(event):
        if event.get('event')=='step_started' and event.get('step')=='review':
            state=controller.status().state
            arguments={'request':state['inputs'],'artifacts':state['outputs'],'artifact_bindings':state['bindings'],
                'sources':state['evidence'],'validation_feedback':None}
            actual=ContextPacker().compose(spec,capture_sources(spec,arguments,state['evidence'],packs))
            citations=[value['citationId'] for value in actual.variants[0]['index'] if value['sourceAlias']=='lookup']
            assert len(citations)==2
            replies.extend([tool_answer(citations[0],1),tool_answer(citations[1],2),fixture['answer']('{"ok":true}')])
    controller.on_event=progress
    state=controller.run(inputs)
    assert state['status']=='completed',(state['status'],state['reason'],len(requests)-before)
    aid=state['bindings']['review']['id'];packet=store.load_receipt(state['run_id'],aid)
    frame=packet['contextPack'];outcomes=packet['contextPackResult']['evidence']['toolOutcomes']
    sizes=[len(json.dumps(value['outcome'],allow_nan=False).encode()) for value in outcomes]
    assert len(sizes)==2 and all(24570<=amount<=24576+1536 for amount in sizes),sizes
    assert len(requests)==before+3 and len(seen)==1 and reader.active_count==0
    assert len(canonical(packet))<=1048576 and len(canonical(state))<=4194304
    assert len(canonical(frame['frozenInput']['authoritativeInputData']))>=65536
    return {'capturedItems':16,'snapshotBytes':len(canonical(candidates.snapshot.to_dict())),
        'modelBytes':len(canonical(frame['frozenInput']['selectedInputData'])),
        'privateFactsBytes':len(canonical(frame['frozenInput']['authoritativeInputData'])),
        'readerOutcomeBytes':sizes,'receiptBytes':len(canonical(packet)),'stateBytes':len(canonical(state)),
        'reservedReceiptBytes':state['contextPacks']['reservations'][aid]['receiptBytes']}


def conversations(store,url,requests,replies):
    scope=ConversationScope(store.namespace,'sandbox','pack-chat','tenant','actor')
    spec=ContextPackSpec('chat','1',[ContextSlot('task',required=True)],task_source='task')
    packs=ContextPackBindings(specs={'chat':spec},sources={'task':InputSource('/task')},
        scope=ContextScope.from_conversation(scope),authorizer=ContextAuthorizer('access','1',lambda use:True))
    binding=ConversationBindings(runtime.ProsaicArtifact('chat','subagent',{'name':'chat','description':'Captured conversation'},
        'ALWAYS use supplied context. NEVER invent facts.'),version='pack-chat-1',config=config(url),
        policy=ConversationPolicy(),run_policy=runtime.RunPolicy(max_provider_requests=1,max_tool_calls=0),context_packs=packs)
    candidates=ContextPacker().compose(spec,capture_sources(spec,{'request':{'task':'SELECTED-CHAT-719'}},{},packs))
    chat=Conversation(binding,store=store,scope=scope);session=chat.create();before=len(requests)
    replies.extend([fixture['answer']('Answer'),fixture['answer']('Follow-up')])
    first=chat.send(session.session_id,message_id='first',message='Exact question',expected_revision=session.revision,context_pack=candidates)
    assert chat.send(session.session_id,message_id='first',message='Exact question',expected_revision=session.revision,
        context_pack=candidates).document==first.document and len(requests)==before+1
    second=Conversation(binding,store=store,scope=scope).send(session.session_id,message_id='second',message='Continue',
        expected_revision=first.document['revision'])
    assert second.document['status']=='completed' and 'SELECTED-CHAT-719' not in json.dumps(requests[-1])
    assert store.load_session(session.session_id,scope=scope).state['version']==3
    return {'turns':2,'providerRequests':2,'replayRequests':0}


def main():
    assert sys.flags.isolated,'run installed acceptance with python -I'
    parser=argparse.ArgumentParser();parser.add_argument('--postgres-dsn-env');parser.add_argument('--require-postgres',action='store_true')
    args=parser.parse_args()
    if args.require_postgres and not args.postgres_dsn_env: parser.error('--postgres-dsn-env is required')
    with TemporaryDirectory(prefix='prosaic-pack-installed-') as directory,fixture['endpoint']() as (url,requests,replies):
        root=Path(directory).resolve();files=root/'files';files.mkdir()
        result={'markdown':markdown_workflow(files,url,requests,replies)}
        memory=MemorySessionStore(namespace='test');memory.initialize(context_packs=True)
        result['memory']=conversations(memory,url,requests,replies)
        file_store=FileSessionStore(root/'sessions',namespace='test');file_store.initialize(context_packs=True)
        result['file']=conversations(file_store,url,requests,replies)
        capacity=root/'capacity';capacity.mkdir();result['capacity']=capacity_workflow(capacity,url,requests,replies)
        if args.postgres_dsn_env:
            from prosaic_harness_postgres import PostgresSessionStore
            dsn=os.environ[args.postgres_dsn_env]
            with PostgresSessionStore(dsn,namespace='pack-installed') as store:
                store.check_ready();result['postgres']=conversations(store,url,requests,replies)
        assert not replies
        result['origins']=origins(bool(args.postgres_dsn_env));result['version']=1
        print(json.dumps(result,sort_keys=True))


if __name__=='__main__': main()
