import pytest
from prosaic_harness import ContextPackError
from prosaic_harness.context_packs.feedback import SafeFeedback,safe_feedback,private_diagnostics


def test_validator_secret_never_enters_public_feedback():
    issues=['expected owner SECRET-884']
    diagnostic=private_diagnostics(issues)
    result=safe_feedback('validationFailed','check-owner',len(issues),{})
    assert result.to_dict()=={'version':1,'policy':'safe-feedback-v1','code':'validationFailed','count':1,'message':None}
    assert 'SECRET-884' not in str(result.to_dict()) and 'SECRET-884' in str(diagnostic)


@pytest.mark.parametrize('code',['validationFailed','schemaViolation','humanResponseInvalid','gateInputInvalid','validatorFault'])
def test_closed_safe_codes_and_static_catalog_never_interpolate(code):
    message='Review {owner} without interpolating values.'
    feedback=safe_feedback(code,'check-owner',2,{'check-owner':message})
    assert feedback.to_dict()['message']==message
    assert SafeFeedback.from_dict(feedback.to_dict()).identity==feedback.identity


def test_catalog_counts_bytes_and_rejects_executable_or_dynamic_messages():
    for catalog in ({'check':'ž'*256},{'check':lambda context:'secret'},{str(i):'x' for i in range(65)}):
        with pytest.raises(ContextPackError): safe_feedback('validationFailed','check',1,catalog)
    for count in (True,0,-1,1.5):
        with pytest.raises(ContextPackError): safe_feedback('validationFailed','check',count,{})
    with pytest.raises(ContextPackError): safe_feedback('arbitrary raw issue','check',1,{})


def test_private_diagnostics_are_bounded_and_never_classify_issue_strings():
    issues=['schemaViolation: SECRET-884 '+('ž'*2000)]*20
    diagnostics=private_diagnostics(issues)
    assert len(diagnostics['issues'])==8
    assert len(str(diagnostics).encode())<8192
    assert safe_feedback('validationFailed','check',len(issues),{}).code=='validationFailed'


def test_private_diagnostic_limits_include_json_escaping():
    from prosaic_harness.context_packs.codec import encode
    result=private_diagnostics(['\x00'*10000]*8)
    assert len(encode(result))<=8192
    assert all(len(encode(issue))<=512 for issue in result['issues'])
