"""Invocation-scoped reads of captured bytes through an ordinary CustomTool."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import threading
import time
from .codec import ContextPackError,integer
from .selection import PreparedContextPack,project,_content_bytes
from .bindings import ContextPackBindings
from .authorization import ExposureBindings,ContextUse,authorize_context_use

NAME='read_context_item'
VERSION='context-pack-reader-v1'
SCHEMA={'type':'object','additionalProperties':False,'required':['citationId'],'properties':{
    'citationId':{'type':'string','minLength':1,'maxLength':128},
    'start':{'type':'integer','minimum':0,'maximum':2097152},
    'end':{'type':'integer','minimum':0,'maximum':2097152},
    'pointer':{'type':'string','maxLength':8192}}}


def _key(scope):
    from prosaic_runtime import InvocationScope
    if type(scope) is not InvocationScope: raise ContextPackError('contextScopeMismatch')
    scope.__post_init__()
    return (scope.invocation_id,scope.run_id,scope.step_id,scope.operation_namespace)


@dataclass(frozen=True)
class _Active:
    pack: PreparedContextPack
    bindings: ContextPackBindings
    deadline: float
    cancelled: object


class ContextPackReader:
    def __init__(self,*,max_body_bytes=16384,max_result_bytes=24576):
        integer(max_body_bytes,1,16384);integer(max_result_bytes,1024,24576)
        self._max_body_bytes=max_body_bytes;self._max_result_bytes=max_result_bytes
        self._active={};self._lock=threading.RLock()
        from prosaic_runtime import CustomTool
        self._tool=CustomTool(NAME,'Read an admitted captured context item. Text offsets are UTF-8 bytes; pointers are absolute within the captured JSON item.',
            SCHEMA,self._dispatch,VERSION,with_context=True,max_argument_bytes=12288,max_result_bytes=max_result_bytes)

    def as_tool(self): return self._tool

    @property
    def max_body_bytes(self): return self._max_body_bytes

    @property
    def max_result_bytes(self): return self._max_result_bytes

    @property
    def active_count(self):
        with self._lock: return len(self._active)

    @contextmanager
    def activate(self,scope,pack,bindings,*,deadline,cancelled=lambda:False):
        key=_key(scope)
        if type(pack) is not PreparedContextPack or type(bindings) is not ContextPackBindings or not callable(cancelled):
            raise ContextPackError()
        if type(deadline) not in (int,float) or not math.isfinite(deadline) or deadline<=0: raise ContextPackError()
        bindings.readmit()
        if pack.snapshot.scope_binding.to_dict()!=bindings.scope.to_dict(): raise ContextPackError('contextScopeMismatch')
        active=_Active(pack,bindings.frozen_copy(),deadline,cancelled)
        with self._lock:
            if key in self._active: raise ContextPackError('contextBindingMismatch')
            self._active[key]=active
        try: yield self
        finally:
            with self._lock:
                if self._active.get(key) is active: del self._active[key]

    def _current(self,key,active,context):
        with self._lock:
            if self._active.get(key) is not active: return False
        try:
            return (context.tool_name==NAME and context.tool_version==VERSION
                and context.deadline is not None and time.monotonic()<min(context.deadline,active.deadline)
                and not active.cancelled() and not context.cancelled())
        except Exception: return False

    def _size(self,result):
        # Runtime's bounded_result uses this exact JSON framing (including
        # default ASCII escaping). Canonical storage size alone is insufficient.
        return len(json.dumps({'status':'ok','result':result},allow_nan=False).encode('utf-8'))

    def _dispatch(self,arguments,context):
        result=self._read(arguments,context)
        if set(result)=={'error'}:
            from prosaic_runtime import ToolFailure
            codes={'contextUseDenied':'context_use_denied','contextReadLimit':'context_read_limit',
                'contextSnapshotUnavailable':'context_snapshot_unavailable'}
            return ToolFailure(codes[result['error']])
        return result

    def _read(self,arguments,context):
        try:
            key=_key(context.scope)
            with self._lock: active=self._active.get(key)
            if active is None or not self._current(key,active,context): return {'error':'contextSnapshotUnavailable'}
            pack=active.pack
            grant=next((e for e in ExposureBindings.from_pack(pack).entries
                if e['disclosure']=='discoverable' and e['citationId']==arguments['citationId']),None)
            if grant is None: return {'error':'contextUseDenied'}
            item=next(i for i in pack.snapshot.to_dict()['items']
                if i['sourceAlias']==grant['sourceAlias'] and i['itemId']==grant['itemId'])
            result=self._result(pack,grant,item,arguments)
            entry={**grant,'disclosure':'read'}
            if result is not None:
                body=result['content'];entry.update(representation=result['representation'],
                    contentSha256=result['contentSha256'],contentBytes=len(_content_bytes(body)),contentKind=result['contentKind'])
            requested=ExposureBindings(active.bindings.scope,[entry])
            use=ContextUse.for_pack('deferredRead',pack,operation_id=context.scope.invocation_id,
                run_id=context.scope.run_id,deadline=min(context.deadline,active.deadline),requested=requested)
            authorize_context_use(active.bindings,use)
            if not self._current(key,active,context): return {'error':'contextSnapshotUnavailable'}
            return result if result is not None else {'error':'contextReadLimit'}
        except ContextPackError as error:
            return {'error':'contextUseDenied' if error.code!='contextSnapshotUnavailable' else error.code}
        except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,StopIteration):
            return {'error':'contextUseDenied'}

    def _result(self,pack,grant,item,arguments):
        admitted=grant['representation'];raw=item['content']
        base={key:grant[key] for key in ('citationId','sourceAlias','sourceIdentity','sourceRevision','sourceLocator','itemId')}
        base.update(snapshotDigest=pack.snapshot.identity,packReference=pack.reference)
        def value(body,representation,*,complete,next_offset=None):
            return dict(base,representation=representation,content=body,
                contentKind='text' if type(body) is str else 'json',contentSha256=hashlib.sha256(_content_bytes(body)).hexdigest(),
                complete=complete,nextOffset=next_offset,continuationAvailable=next_offset is not None)
        if item['contentKind']=='json':
            if 'start' in arguments or 'end' in arguments: raise ContextPackError('contextUseDenied')
            selected=admitted if 'pointer' not in arguments else {'kind':'jsonPointer','pointer':arguments['pointer']}
            # Prove narrowing before consulting even the privately retained
            # parent, to keep rejected sibling content outside the read path.
            if admitted['kind']=='jsonPointer':
                target=selected.get('pointer','')
                prefix=admitted['pointer']
                if target!=prefix and (not target.startswith(prefix+'/') if prefix else not target.startswith('/')):
                    raise ContextPackError('contextUseDenied')
            elif admitted['kind']!='whole': raise ContextPackError('contextUseDenied')
            body=project(raw,selected)
            result=value(body,selected,complete=selected['kind']=='whole')
            return result if len(_content_bytes(body))<=self.max_body_bytes and self._size(result)<=self.max_result_bytes else None
        if 'pointer' in arguments: raise ContextPackError('contextUseDenied')
        encoded=raw.encode('utf-8')
        if admitted['kind']=='whole': lower,upper=0,len(encoded)
        elif admitted['kind']=='utf8Range': lower,upper=admitted['start'],admitted['end']
        else: raise ContextPackError('contextUseDenied')
        start=arguments.get('start',lower);end=arguments.get('end',upper)
        integer(start,lower,upper);integer(end,start,upper)
        # Validate requested boundaries, including a zero-length range.
        project(raw,{'kind':'utf8Range','start':start,'end':end})
        page=encoded[start:min(end,start+self.max_body_bytes)].decode('utf-8',errors='ignore')
        def make(text):
            stop=start+len(text.encode('utf-8'))
            return value(text,{'kind':'utf8Range','start':start,'end':stop},
                complete=start==0 and stop==len(encoded),next_offset=stop if stop<end else None)
        result=make(page)
        if self._size(result)<=self.max_result_bytes: return result
        low,high=0,len(page)
        while low<high:
            middle=(low+high+1)//2
            if self._size(make(page[:middle]))<=self.max_result_bytes: low=middle
            else: high=middle-1
        if low==0 and start<end: return None
        result=make(page[:low])
        return result if self._size(result)<=self.max_result_bytes else None
