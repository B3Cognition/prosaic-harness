import json
from prosaic_harness import Validator
from test_workflow_rules_execution import rule_endpoint
from test_context_pack_workflow import markdown_flow,controller


def test_validator_diagnostics_never_enter_public_events_or_retry_input(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint;replies.extend(['{"ok":true}']*3)
    calls=[]
    def check(output,context):
        calls.append(context.step)
        return ['expected owner SECRET-884'] if len(calls)==1 else []
    validators={'private-check':Validator('1',check)}
    workflow,_=markdown_flow(tmp_path,cfg,validators=validators)
    events=[];harness=controller(workflow,tmp_path,validators=validators,on_event=events.append)
    state=harness.run({'task':'work','private':'UNRELATED-BUSINESS-419'})
    assert state['status']=='completed' and len(requests)==3
    public=json.dumps([requests,events])
    assert 'SECRET-884' not in public and 'UNRELATED-BUSINESS-419' not in public
    assert 'safe-feedback-v1' in public and 'validationFailed' in public


def test_revoked_private_validation_settles_receipt_without_running_validators(rule_endpoint,tmp_path,monkeypatch):
    import pytest
    from prosaic_harness import Harness
    cfg,requests,replies=rule_endpoint;replies.extend(['{"ok":true}']*2)
    denied=[False];checks=[]
    def authorize(use): return not (denied[0] and use.purpose=='validation')
    validators={'private-check':Validator('1',lambda output,context:checks.append(context) or [])}
    workflow,guards=markdown_flow(tmp_path,cfg,guarded=True,authorize=authorize,validators=validators)
    harness=controller(workflow,tmp_path,validators=validators)
    monkeypatch.setattr(harness,'_accept',lambda *a:(_ for _ in ()).throw(OSError('crash after durable receipt')))
    with pytest.raises(OSError): harness.run({'task':'work','private':'UNRELATED-BUSINESS-419'})
    denied[0]=True
    restored=Harness(workflow,store=harness.store,run_id='a'*32,validators=validators).resume()
    assert checks==[] and len(requests)==1 and len(guards)==1
    assert restored['status']=='blocked' and restored['reason']=='contextUseDenied'
    assert restored['pending'] is None and restored['invocations'][0]['status']=='complete'
    assert restored['contextPacks']['attempts'][restored['invocations'][0]['id']]['stage']=='adopted'


def test_validator_fault_has_closed_feedback_without_exception_details(rule_endpoint,tmp_path):
    cfg,requests,replies=rule_endpoint;replies.append('{"ok":true}')
    def broken(output,context): raise RuntimeError('PRIVATE-EXCEPTION-884')
    validators={'broken':Validator('1',broken)}
    workflow,_=markdown_flow(tmp_path,cfg,validators=validators)
    events=[];harness=controller(workflow,tmp_path,validators=validators,on_event=events.append)
    state=harness.run({'task':'work','private':'UNRELATED-BUSINESS-419'})
    assert state['status']=='blocked' and state['reason']=='validator_error'
    assert state['feedback']['policy']=='safe-feedback-v1' and state['feedback']['code']=='validatorFault'
    assert 'PRIVATE-EXCEPTION-884' not in json.dumps([events,requests])


def test_retained_read_denial_does_not_prevent_internal_adoption(rule_endpoint,tmp_path,monkeypatch):
    import pytest
    from prosaic_harness import Harness
    cfg,requests,replies=rule_endpoint;replies.extend(['{"ok":true}']*2)
    allowed=[True]
    workflow,_=markdown_flow(tmp_path,cfg,authorize=lambda use:allowed[0] or use.purpose!='retainedRead')
    harness=controller(workflow,tmp_path)
    monkeypatch.setattr(harness,'_accept',lambda *a:(_ for _ in ()).throw(OSError('after receipt')))
    with pytest.raises(OSError): harness.run({'task':'work','private':'PRIVATE-RETAINED-884'})
    allowed[0]=False
    restored=Harness(workflow,store=harness.store,run_id='a'*32)
    with pytest.raises(ValueError,match='contextUseDenied'): restored.resume()
    saved=harness.store.load_run('a'*32).state
    assert saved['pending'] is None and saved['status']=='completed' and len(requests)==2
    with pytest.raises(ValueError,match='contextUseDenied'): restored.status()


def test_opted_human_error_uses_closed_feedback_without_changing_waiting_state(rule_endpoint,tmp_path):
    import pytest
    from prosaic_harness import HumanResponseError
    from test_context_pack_workflow_limits import bounded_flow
    cfg,requests,replies=rule_endpoint;replies.append('{"ok":true}')
    definition={'version':1,'start':'build','steps':{
        'build':{'kind':'agent','agent':'worker','schema':'result','next':'approve'},
        'approve':{'kind':'pause','question':'Continue?','choices':{'yes':'done'}},'done':{'kind':'finish'}}}
    harness=controller(bounded_flow(cfg,definition),tmp_path)
    assert harness.run({'task':'work'})['status']=='waiting'
    before=harness.store.load_run('a'*32)
    with pytest.raises(HumanResponseError) as caught:
        harness.resume(choice='PRIVATE-INVALID-884',expected_revision=before.revision)
    assert caught.value.to_dict()['feedback']['code']=='humanResponseInvalid'
    assert 'PRIVATE-INVALID' not in json.dumps(caught.value.to_dict())
    assert harness.store.load_run('a'*32)==before


def test_opted_missing_gate_input_uses_closed_feedback(rule_endpoint,tmp_path):
    from test_context_pack_workflow_limits import bounded_flow
    cfg,requests,replies=rule_endpoint;replies.append('{"ok":true}')
    definition={'version':1,'start':'build','steps':{
        'build':{'kind':'agent','agent':'worker','schema':'result','next':'gate'},
        'gate':{'kind':'gate','from':'build','field':['missing'],'equals':True,'pass':'done','fail':'done'},
        'done':{'kind':'finish'}}}
    state=controller(bounded_flow(cfg,definition),tmp_path).run({'task':'work'})
    assert state['reason']=='gate_input_missing' and state['feedback']['code']=='gateInputInvalid'
