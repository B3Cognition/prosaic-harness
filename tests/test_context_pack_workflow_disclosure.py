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
