import json,time
import pytest
import prosaic_runtime as api
from prosaic_harness import (ContextPacker,ContextPackSpec,ContextSlot,ContextSnapshot,ContextItem,ContextSource,
    ContextPackBindings,ContextAuthorizer,InputSource)
from prosaic_harness.context_packs.codec import digest
from support.context_pack_cases import scope_case
from test_workflow_rules_execution import rule_endpoint


def reader_case(content='captured facts',*,representation=None,authorize=lambda use:True,availability='discoverable'):
    from prosaic_harness import ContextPackReader
    snapshot=ContextSnapshot.from_items([ContextItem('same','facts','1',content)],
        sources=[ContextSource('facts','accepted-record','1','complete')],scope_binding=scope_case())
    spec=ContextPackSpec('reader','1',[ContextSlot('facts',availability=availability,
        **({'representation':representation} if representation is not None else {}))])
    packer=ContextPacker();candidates=packer.compose(spec,snapshot)
    pack=packer.select(candidates,0,digest(candidates.variants[0]))
    bindings=ContextPackBindings(specs={'reader':spec},sources={'facts':InputSource('')},scope=scope_case(),
        authorizer=ContextAuthorizer('access','1',authorize))
    return ContextPackReader(),pack,bindings


def call(reader,scope,citation,**arguments):
    from prosaic_runtime.tools import execute_custom_tool
    return execute_custom_tool(reader.as_tool(),json.dumps({'citationId':citation,**arguments}),
        check_boundary=lambda:None,scope=scope,deadline=time.monotonic()+60)


def test_stable_tool_reads_only_selected_discoverable_snapshot():
    reader,pack,bindings=reader_case();scope=api.InvocationScope('turn-1',operation_namespace='test')
    descriptor=reader.as_tool().descriptor;citation=pack.envelope['index'][0]['citationId']
    assert descriptor['version']=='context-pack-reader-v1' and descriptor['with_context'] is True
    assert descriptor['max_result_bytes']==24576
    assert call(reader,scope,citation)['error']=='context_snapshot_unavailable'
    with reader.activate(scope,pack,bindings,deadline=time.monotonic()+60):
        result=call(reader,scope,citation)['result']
        assert result['content']=='captured facts' and result['complete'] is True
        assert result['snapshotDigest']==pack.snapshot.identity
        assert reader.as_tool().descriptor==descriptor
        assert call(reader,api.InvocationScope('turn-2',operation_namespace='test'),citation)['error']=='context_snapshot_unavailable'
    assert call(reader,scope,citation)['error']=='context_snapshot_unavailable'


def test_json_pointer_can_narrow_but_never_widen():
    reader,pack,bindings=reader_case({'public':{'title':'visible'},'private':'SECRET'},representation={'kind':'jsonPointer','pointer':'/public'})
    scope=api.InvocationScope('turn');citation=pack.envelope['index'][0]['citationId']
    with reader.activate(scope,pack,bindings,deadline=time.monotonic()+60):
        assert call(reader,scope,citation,pointer='/public/title')['result']['content']=='visible'
        for pointer in ('','/private','/publicity'):
            assert call(reader,scope,citation,pointer=pointer)['error']=='context_use_denied'


def test_text_pages_respect_utf8_and_actual_runtime_json_escaping():
    text=('ž\x00"\\'*10000)
    reader,pack,bindings=reader_case(text,representation={'kind':'utf8Range','start':2,'end':len(text.encode())-5})
    scope=api.InvocationScope('turn');citation=pack.envelope['index'][0]['citationId'];start=2;parts=[]
    with reader.activate(scope,pack,bindings,deadline=time.monotonic()+60):
        while True:
            result=call(reader,scope,citation,start=start)
            assert result['status']=='ok' and len(json.dumps(result).encode())<=24576
            page=result['result'];parts.append(page['content'])
            assert len(page['content'].encode())<=16384 and page['representation']['start']==start
            if page['nextOffset'] is None: break
            assert page['nextOffset']>start;start=page['nextOffset']
    assert ''.join(parts).encode()==text.encode()[2:-5]


def test_large_json_is_not_prefix_truncated():
    reader,pack,bindings=reader_case({'large':'x'*20000});scope=api.InvocationScope('turn')
    with reader.activate(scope,pack,bindings,deadline=time.monotonic()+60):
        assert call(reader,scope,pack.envelope['index'][0]['citationId'])['error']=='context_read_limit'


def test_current_authorization_and_cancellation_are_checked_each_read():
    allowed=[True];uses=[]
    def authorize(use): uses.append(use);return allowed[0]
    reader,pack,bindings=reader_case(authorize=authorize);scope=api.InvocationScope('turn');cancelled=[False]
    with reader.activate(scope,pack,bindings,deadline=time.monotonic()+60,cancelled=lambda:cancelled[0]):
        citation=pack.envelope['index'][0]['citationId']
        assert call(reader,scope,citation)['result']['content']=='captured facts'
        allowed[0]=False
        assert call(reader,scope,citation)['error']=='context_use_denied'
        allowed[0]=True;cancelled[0]=True
        assert call(reader,scope,citation)['error']=='context_snapshot_unavailable'
    assert all(use.purpose=='deferredRead' for use in uses)


def test_inline_only_item_is_not_a_reader_grant():
    reader,pack,bindings=reader_case(availability='inline');scope=api.InvocationScope('turn')
    with reader.activate(scope,pack,bindings,deadline=time.monotonic()+60):
        assert call(reader,scope,pack.envelope['items'][0]['citationId'])['error']=='context_use_denied'


@pytest.mark.parametrize('stage',[None,'before_tool','after_tool'])
def test_real_runtime_tools_guards_and_budget_preserve_actual_outcomes(rule_endpoint,stage):
    from dataclasses import replace
    cfg,requests,replies=rule_endpoint
    cfg=replace(cfg,allowed_tools=frozenset({'read_context_item'}))
    uses=[];reader,pack,bindings=reader_case(authorize=lambda use:uses.append(use) or True)
    citation=pack.envelope['index'][0]['citationId']
    guards=[];body='ALWAYS use captured evidence. NEVER invent facts.'
    if stage is not None:
        guards=[api.Guard('scope','1',(stage,),lambda s,c:api.Verdict(False))]
        body+=f'\nALWAYS check scope. <!-- enforce: scope(stage={stage}, on_violation=fail) -->'
    artifact=api.ProsaicArtifact.from_inspection(dict(id='reader.md',type='subagent',
        frontmatter={'name':'reader','description':'Captured evidence test','tools':['read_context_item']},body=body))
    runtime=api.ProsaicRuntime(cfg,custom_tools={'read_context_item':reader.as_tool()},guards=guards)
    scope=api.InvocationScope('actual-turn',run_id='actual-run',operation_namespace='test')
    prepared=runtime.prepare_turn(artifact,message='Read the selected evidence',input_data={'contextPack':pack.envelope},
        input_profile='context-pack-input-v1',policy=api.RunPolicy(allowed_tools=frozenset({'read_context_item'}),
            max_provider_requests=2,max_tool_calls=1))
    replies.extend([{'name':'read_context_item','input':{'citationId':citation}},'captured answer'])
    with reader.activate(scope,pack,bindings,deadline=time.monotonic()+60):
        result=runtime.turn(prepared,operation_context=scope)
    evidence=result.evidence.to_dict()
    assert reader.active_count==0
    if stage is None:
        assert result.result.exit_code==0 and evidence['toolAttempts']==1
        assert 'captured facts' in json.dumps(requests[-1])
    else:
        assert evidence['failureCode']=='ruleViolation' and len(requests)==1
        assert (len(uses)>0)==(stage=='after_tool')
        assert evidence['toolAttempts']==(1 if stage=='after_tool' else 0)


def test_revoked_oversized_item_still_checks_current_authorization():
    reader,pack,bindings=reader_case({'large':'x'*20000},authorize=lambda use:False)
    scope=api.InvocationScope('turn')
    with reader.activate(scope,pack,bindings,deadline=time.monotonic()+60):
        assert call(reader,scope,pack.envelope['index'][0]['citationId'])['error']=='context_use_denied'


def test_denied_reader_is_a_controlled_failed_tool_outcome():
    from prosaic_runtime.tools import execute_custom_tool
    reader,pack,bindings=reader_case();outcomes=[]
    result=execute_custom_tool(reader.as_tool(),json.dumps({'citationId':pack.envelope['index'][0]['citationId']}),
        check_boundary=lambda:None,scope=api.InvocationScope('missing'),deadline=time.monotonic()+60,on_outcome=outcomes.append)
    assert result=={'status':'error','error':'context_snapshot_unavailable'}
    assert outcomes[-1].to_dict()['code']=='controlled_failure'
