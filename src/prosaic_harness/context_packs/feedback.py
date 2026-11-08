"""Closed feedback codes and host-declared constant messages only."""
from .codec import ContextPackError,closed,decode,encode,integer,reference
from .types import _Record
from .bindings import admit_options

CODES=frozenset({'validationFailed','schemaViolation','humanResponseInvalid','gateInputInvalid','validatorFault'})


class SafeFeedback(_Record):
    @classmethod
    def from_dict(cls,value):
        closed(value,{'version','policy','code','count','message'})
        if type(value['version']) is not int or value['version']!=1 or value['policy']!='safe-feedback-v1':
            raise ContextPackError()
        if type(value['code']) is not str or value['code'] not in CODES: raise ContextPackError()
        integer(value['count'],1,65536)
        message=value['message']
        if message is not None and (type(message) is not str or len(message.encode('utf-8'))>512): raise ContextPackError()
        result=object.__new__(cls);result._own(value,maximum=1024)
        return result


def safe_feedback(kind,check_alias,count,catalog):
    admitted,_=admit_options(catalog)
    if check_alias is not None: reference(check_alias)
    return SafeFeedback.from_dict(dict(version=1,policy='safe-feedback-v1',code=kind,count=count,
        message=admitted.get(check_alias) if check_alias is not None else None))


def readmit_feedback(value,catalog):
    if value is None: return
    admitted,_=admit_options(catalog)
    feedback=SafeFeedback.from_dict(value)
    if feedback.message is not None and feedback.message not in admitted.values():
        raise ContextPackError('contextBindingMismatch')


def private_diagnostics(issues):
    if type(issues) not in (tuple,list): raise ContextPackError()
    result=[]
    for issue in issues[:8]:
        if type(issue) is not str: raise ContextPackError()
        try: content=issue[:512].encode('utf-8',errors='strict')
        except UnicodeError: content=b'invalidDiagnostic'
        text=content[:512].decode('utf-8',errors='ignore')
        while len(encode(text))>512:
            text=text[:max(1,len(text)//2)]
        result.append(text)
    return decode(encode(dict(version=1,issues=result),maximum=8192))
