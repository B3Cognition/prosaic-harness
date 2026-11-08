"""Current use permission and conservative provenance, separate from capture."""
import math
import time
from .codec import ContextPackError,closed,decode,encode,integer,reference,locator
from .types import ContextScope,ContextSnapshot,_Record,_hash
from .selection import PreparedContextPack
from .bindings import ContextPackBindings

PURPOSES=frozenset({'invocation','deferredRead','historyReuse','validation','retainedRead'})
DISCLOSURES=frozenset({'inline','discoverable','read','status','validation'})
ENTRY_KEYS={'sourceAlias','sourceIdentity','sourceRevision','sourceOutcome','itemId','sourceLocator',
    'representation','contentSha256','citationId','disclosure','contentBytes','contentKind'}


def _entry(source,*,item=None,disclosure='status',representation=None,citation_id=None,content_sha256=None,content_bytes=0,content_kind=None):
    return dict(sourceAlias=source['alias'],sourceIdentity=source['sourceIdentity'],sourceRevision=source['revision'],
        sourceOutcome=source['outcome'],itemId=item['itemId'] if item else None,
        sourceLocator=item['locator'] if item else None,representation=representation,
        contentSha256=content_sha256,citationId=citation_id,disclosure=disclosure,
        contentBytes=content_bytes,contentKind=content_kind)


def _admit_entry(value):
    closed(value,ENTRY_KEYS)
    for key in ('sourceAlias','sourceIdentity','sourceRevision'): reference(value[key])
    if type(value['sourceOutcome']) is not str or value['sourceOutcome'] not in {'complete','partial','unavailable'}:
        raise ContextPackError()
    if type(value['disclosure']) is not str or value['disclosure'] not in DISCLOSURES: raise ContextPackError()
    integer(value['contentBytes'],0,2097152)
    if value['itemId'] is None:
        if value['disclosure'] not in {'status','validation'} or value['contentBytes']!=0 or any(value[k] is not None for k in ('sourceLocator','representation','contentSha256','citationId','contentKind')):
            raise ContextPackError()
    else:
        reference(value['itemId']);_hash(value['contentSha256'])
        if value['disclosure']=='status' or value['sourceOutcome']=='unavailable': raise ContextPackError()
        if value['citationId'] is not None: reference(value['citationId'])
        if value['disclosure']!='validation' and value['citationId'] is None: raise ContextPackError()
        if value['contentKind'] not in ('text','json'): raise ContextPackError()
        if locator(value['sourceLocator'])!=value['sourceLocator'] or locator(value['representation'],representation=True)!=value['representation']:
            raise ContextPackError()


class ExposureBindings(_Record):
    def __init__(self,scope,entries=()):
        if type(scope) is not ContextScope or type(entries) not in (list,tuple) or len(entries)>8192:
            raise ContextPackError()
        # Bound ownership before traversal and normalize a set of disclosures.
        entries=decode(encode(list(entries),maximum=2097152))
        for entry in entries: _admit_entry(entry)
        if len({entry['disclosure']=='validation' for entry in entries})>1:
            raise ContextPackError('contextBindingMismatch')
        unique={encode(e):e for e in entries}
        self._own(dict(version=1,scopeBinding=scope.to_dict(),entries=[unique[k] for k in sorted(unique)]),maximum=2097152)

    @property
    def scope(self): return ContextScope.from_dict(self.to_dict()['scopeBinding'])

    @classmethod
    def from_dict(cls,value):
        closed(value,{'version','scopeBinding','entries'})
        if type(value['version']) is not int or value['version']!=1: raise ContextPackError()
        return cls(ContextScope.from_dict(value['scopeBinding']),value['entries'])

    @classmethod
    def from_pack(cls,pack):
        if type(pack) is not PreparedContextPack: raise ContextPackError()
        snapshot=pack.snapshot.to_dict();source_map={s['alias']:s for s in snapshot['sources']}
        item_map={(i['sourceAlias'],i['itemId']):i for i in snapshot['items']}
        envelope=pack.envelope; entries=[]
        # An empty-result/status header is still a disclosure requiring permission.
        for alias in sorted({s.source for s in pack.spec.slots}):
            if alias in source_map: entries.append(_entry(source_map[alias]))
        for key,disclosure in (('items','inline'),('index','discoverable')):
            for item in envelope[key]:
                parent=item_map[(item['sourceAlias'],item['itemId'])]
                size=(len(item['content'].encode('utf-8')) if type(item.get('content')) is str else len(encode(item['content']))) if key=='items' else item['contentBytes']
                entries.append(_entry(source_map[item['sourceAlias']],item=parent,disclosure=disclosure,
                    representation=item['representation'],citation_id=item['citationId'],content_sha256=item['contentSha256'],
                    content_bytes=size,content_kind=item['contentKind']))
        return cls(ContextScope.from_dict(snapshot['scopeBinding']),entries)

    @classmethod
    def from_snapshot(cls,snapshot):
        if type(snapshot) is not ContextSnapshot: raise ContextPackError()
        document=snapshot.to_dict();sources={s['alias']:s for s in document['sources']}
        entries=[_entry(s,disclosure='validation') for s in sources.values()]
        for item in document['items']:
            size=len(item['content'].encode('utf-8')) if item['contentKind']=='text' else len(encode(item['content']))
            entries.append(_entry(sources[item['sourceAlias']],item=item,disclosure='validation',representation={'kind':'whole'},
                content_sha256=item['contentSha256'],content_bytes=size,content_kind=item['contentKind']))
        return cls(ContextScope.from_dict(document['scopeBinding']),entries)

    def union(self,*others):
        entries=self.entries
        for other in others:
            if type(other) is not ExposureBindings or other.scope.to_dict()!=self.scope.to_dict():
                raise ContextPackError('contextScopeMismatch')
            entries.extend(other.entries)
        return ExposureBindings(self.scope,entries)

    def contains(self,requested):
        if type(requested) is not ExposureBindings or requested.scope.to_dict()!=self.scope.to_dict(): return False
        return all(any(_allows(grant,entry) for grant in self.entries) for entry in requested.entries)


def _allows(grant,entry):
    fixed=('sourceAlias','sourceIdentity','sourceRevision','sourceOutcome','itemId','sourceLocator','citationId')
    if any(encode(grant[k])!=encode(entry[k]) for k in fixed): return False
    if (grant['disclosure']=='validation')!=(entry['disclosure']=='validation'): return False
    if grant['itemId'] is None: return grant==entry
    admitted=grant['representation'];requested=entry['representation']
    if admitted==requested: return grant['contentKind']==entry['contentKind'] and grant['contentSha256']==entry['contentSha256'] and grant['contentBytes']==entry['contentBytes']
    if requested['kind']=='whole': return False
    if requested['kind']=='utf8Range' and (entry['contentKind']!='text' or entry['contentBytes']!=requested['end']-requested['start']): return False
    if admitted['kind']=='whole':
        return (requested['kind']=='utf8Range' and grant['contentKind']=='text' and requested['end']<=grant['contentBytes']
                or requested['kind']=='jsonPointer' and grant['contentKind']=='json')
    if admitted['kind']!=requested['kind']: return False
    if admitted['kind']=='utf8Range': return admitted['start']<=requested['start']<=requested['end']<=admitted['end']
    if admitted['kind']=='jsonPointer':
        if grant['contentKind']!='json': return False
        def segments(value): return [v.replace('~1','/').replace('~0','~') for v in value.split('/')[1:]] if value else []
        prefix=segments(admitted['pointer']); path=segments(requested['pointer'])
        return path[:len(prefix)]==prefix
    return False


class ContextUse(_Record):
    """A bounded logical use; deadline is in Runtime's monotonic-clock seconds."""
    def __init__(self,purpose,*,scope,operation_id,exposures,deadline=None,session_id=None,run_id=None,validation_input=None):
        if type(purpose) is not str or purpose not in PURPOSES or type(scope) is not ContextScope or type(exposures) is not ExposureBindings:
            raise ContextPackError()
        reference(operation_id)
        for value in (session_id,run_id):
            if value is not None: reference(value)
        if deadline is None:
            if purpose!='retainedRead': raise ContextPackError()
        elif type(deadline) not in (int,float) or deadline<=0 or deadline>2**63-1 or not math.isfinite(deadline):
            raise ContextPackError()
        if scope.to_dict()!=exposures.scope.to_dict(): raise ContextPackError('contextScopeMismatch')
        private=any(e['disclosure']=='validation' for e in exposures.entries)
        if (private and purpose in {'invocation','deferredRead','historyReuse'}) or (purpose=='validation' and any(e['disclosure']!='validation' for e in exposures.entries)):
            raise ContextPackError('contextBindingMismatch')
        document=dict(version=1,purpose=purpose,scopeBinding=scope.to_dict(),operationId=operation_id,
            sessionId=session_id,runId=run_id,deadline=deadline,exposures=exposures.to_dict())
        if validation_input is not None:
            if purpose not in {'validation','retainedRead'}: raise ContextPackError('contextBindingMismatch')
            closed(validation_input,{'profile','digest'})
            reference(validation_input['profile']);_hash(validation_input['digest'])
            document.update(version=2,validationInput=validation_input)
        self._own(document,maximum=3145728)

    @property
    def scope(self): return ContextScope.from_dict(self.to_dict()['scopeBinding'])

    @property
    def exposures(self): return ExposureBindings.from_dict(self.to_dict()['exposures'])

    @property
    def source_refs(self): return tuple(self.exposures.entries)

    @classmethod
    def for_pack(cls,purpose,pack,*,operation_id,deadline=None,session_id=None,run_id=None,requested=None):
        if type(pack) is not PreparedContextPack: raise ContextPackError()
        allowed=ExposureBindings.from_snapshot(pack.snapshot) if purpose=='validation' else ExposureBindings.from_pack(pack)
        if requested is not None and not allowed.contains(requested): raise ContextPackError('contextUseDenied')
        return cls(purpose,scope=allowed.scope,operation_id=operation_id,deadline=deadline,
            session_id=session_id,run_id=run_id,exposures=requested if requested is not None else allowed)

    @classmethod
    def from_dict(cls,value):
        if type(value) is not dict or type(value.get('version')) is not int or value['version'] not in (1,2): raise ContextPackError()
        closed(value,{'version','purpose','scopeBinding','operationId','sessionId','runId','deadline','exposures',
            *({'validationInput'} if value['version']==2 else ())})
        if value['version']==2 and value['validationInput'] is None: raise ContextPackError()
        return cls(value['purpose'],scope=ContextScope.from_dict(value['scopeBinding']),operation_id=value['operationId'],
            session_id=value['sessionId'],run_id=value['runId'],deadline=value['deadline'],exposures=ExposureBindings.from_dict(value['exposures']),
            validation_input=value.get('validationInput'))


def authorize_context_use(bindings,use):
    if type(bindings) is not ContextPackBindings or type(use) is not ContextUse: raise ContextPackError()
    bindings.readmit()
    if bindings.scope.to_dict()!=use.scope.to_dict(): raise ContextPackError('contextScopeMismatch')
    if any(entry['sourceAlias'] not in bindings.sources for entry in use.source_refs):
        raise ContextPackError('contextBindingMismatch')
    if use.deadline is not None and time.monotonic()>=use.deadline: raise ContextPackError('contextUseDenied')
    try:
        allowed=bindings.authorizer.authorize(ContextUse.from_dict(use.to_dict()))
    except Exception:
        raise ContextPackError('contextUseDenied') from None
    if allowed is not True or (use.deadline is not None and time.monotonic()>=use.deadline):
        raise ContextPackError('contextUseDenied')
    bindings.readmit()
