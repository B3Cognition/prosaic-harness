"""Deterministic whole-unit composition over already owned evidence."""
import hashlib
import math
import time
from .codec import ContextPackError, closed, decode, digest, encode, integer,locator as admit_locator
from .types import ContextPackPolicy, ContextPackSpec, ContextSnapshot, _Record, _hash

_clock = time.monotonic
RENDER_VERSION = 'context-pack-envelope-v1'


def project(content, representation):
    """Select exact captured bytes/JSON; never consult a source."""
    representation=admit_locator(representation,representation=True)
    kind=representation['kind']
    if kind=='whole': return content
    if kind=='utf8Range':
        if type(content) is not str: raise ContextPackError()
        data=content.encode('utf-8')
        start,end=representation['start'],representation['end']
        if end>len(data): raise ContextPackError()
        try:
            data[:start].decode('utf-8',errors='strict')
            data[:end].decode('utf-8',errors='strict')
            return data[start:end].decode('utf-8',errors='strict')
        except UnicodeError: raise ContextPackError() from None
    pointer=representation['pointer']
    value=content
    for component in pointer.split('/')[1:] if pointer else ():
        key=component.replace('~1','/').replace('~0','~')
        if type(value) is dict:
            if key not in value: raise ContextPackError()
            value=value[key]
        elif type(value) is list:
            if not key.isascii() or not key.isdigit() or (len(key)>1 and key[0]=='0') or len(key)>10:
                raise ContextPackError()
            offset=int(key)
            if offset>=len(value): raise ContextPackError()
            value=value[offset]
        else: raise ContextPackError()
    return value


def _content_bytes(value):
    return value.encode('utf-8') if type(value) is str else encode(value)


def _validate_capture(document,declaration,policy,check=lambda:None):
    if (len(document['items'])>policy.max_captured_items or len(document['sources'])>policy.max_source_aliases
            or len(encode(document))>policy.max_snapshot_bytes): raise ContextPackError('contextSnapshotLimit')
    if len(declaration['slots'])>policy.max_slots: raise ContextPackError('contextPackLimit')
    total=0
    for item in document['items']:
        check()
        content=item['content']
        maximum=policy.max_item_bytes*6+2 if type(content) is str else policy.max_item_bytes
        encode(content,maximum=maximum,depth=policy.max_json_depth,nodes=policy.max_json_nodes)
        size=len(_content_bytes(content));total+=size
        if size>policy.max_item_bytes or len(item['labels'])>policy.max_labels_per_item:
            raise ContextPackError('contextSnapshotLimit')
    if total>policy.max_total_content_bytes: raise ContextPackError('contextSnapshotLimit')


def _resolve(spec, snapshot, check):
    sources={s['alias']:s for s in snapshot['sources']}
    by_source={alias:{} for alias in sources}
    for item in snapshot['items']: by_source[item['sourceAlias']][item['itemId']]=item
    units={}; slots=[]
    for index,slot in enumerate(spec['slots']):
        check()
        source=sources.get(slot['source'])
        available=source is not None and source['outcome']!='unavailable'
        outcome=source['outcome'] if source else 'unavailable'
        if outcome=='partial' and not slot['allowPartial']: available=False
        if slot['required'] and not available:
            raise ContextPackError('requiredContextMissing')
        items=by_source.get(slot['source'],{}) if available else {}
        order=list(slot['itemIds']) if slot['itemIds'] else (
            list(source['rankedItemIds']) + sorted(set(items)-set(source['rankedItemIds'])) if available else [])
        chosen=[]
        for item_id in order:
            item=items.get(item_id)
            if item is None: continue
            labels=item['labels']
            if any(key not in labels or encode(labels[key]) not in {encode(v) for v in values}
                   for key,values in slot['labels'].items()): continue
            chosen.append(item)
        if len(chosen)>slot['maxItems']: raise ContextPackError('selectionLimit')
        if len(chosen)<slot['minItems']: raise ContextPackError('requiredContextMissing')
        if slot['required'] and not chosen and outcome!='complete':
            raise ContextPackError('requiredContextMissing')
        selected_ids=[]
        for rank,item in enumerate(chosen):
            check()
            value=project(item['content'],slot['representation'])
            if slot['source']==spec['taskSource'] and (value is None or
                    (type(value) is str and not value.strip()) or (type(value) in (dict,list) and not value)):
                raise ContextPackError('requiredContextMissing')
            content_sha=hashlib.sha256(_content_bytes(value)).hexdigest()
            identity=dict(scopeBinding=snapshot['scopeBinding'],sourceAlias=slot['source'],
                sourceIdentity=source['sourceIdentity'],sourceRevision=source['revision'],
                itemId=item['itemId'],sourceLocator=item['locator'],representation=slot['representation'],contentSha256=content_sha)
            citation='ctx_'+digest(identity)
            selected_ids.append(citation)
            priority=(-slot['priority'],index,rank)
            if citation not in units:
                entry=dict(citationId=citation,content=value,contentKind='text' if type(value) is str else 'json',
                    contentSha256=content_sha,slotIndexes=[],sourceAlias=slot['source'],
                    sourceIdentity=source['sourceIdentity'],sourceRevision=source['revision'],
                    sourceOutcome=source['outcome'],itemId=item['itemId'],sourceLocator=item['locator'],
                    representation=slot['representation'],derivedFrom=item['derivedFrom'])
                units[citation]=dict(entry=entry,required=False,inline=False,discoverable=False,
                    priority=priority,label=item['label'])
            unit=units[citation]
            unit['entry']['slotIndexes'].append(index)
            unit['required'] |= slot['required']
            unit['inline'] |= slot['availability']=='inline'
            unit['discoverable'] |= slot['availability']=='discoverable'
            unit['priority']=min(unit['priority'],priority)
        slots.append(dict(slotIndex=index,required=slot['required'],minItems=slot['minItems'],
            matchedCount=len(chosen),outcome=outcome,citations=selected_ids))
    return units,slots


def _envelope(units, slots, selected):
    ordered=sorted(units,key=lambda c:units[c]['priority'])
    inline=[units[c]['entry'] for c in ordered if c in selected]
    index=[]
    for citation in ordered:
        unit=units[citation]
        if citation in selected or not unit['discoverable']: continue
        item={k:v for k,v in unit['entry'].items() if k!='content'}
        item.update(label=unit['label'],contentBytes=len(_content_bytes(unit['entry']['content'])))
        index.append(item)
    deferred={i['citationId'] for i in index}
    coverage=[]
    for slot in slots:
        coverage.append({k:v for k,v in slot.items() if k!='citations'} |
            dict(selectedCount=sum(c in selected for c in slot['citations']),
                 deferredCount=sum(c in deferred for c in slot['citations'])))
    return dict(version=1,format=RENDER_VERSION,items=inline,index=index,coverage=coverage)


def _report(envelope, units, reasons):
    selected=[i['citationId'] for i in envelope['items']]
    deferred=[i['citationId'] for i in envelope['index']]
    omitted=[c for c in sorted(units,key=lambda c:units[c]['priority']) if c not in selected and c not in deferred]
    return dict(version=1,slots=envelope['coverage'],selectedItemCount=len(selected),
        deferredItemCount=len(deferred),omittedItemCount=len(omitted),
        requiredCoverageComplete=all(not s['required'] or s['selectedCount']>=s['minItems'] for s in envelope['coverage']),
        selectedCitations=selected,deferredCitations=deferred,
        omissions=[dict(citationId=c,slotIndexes=units[c]['entry']['slotIndexes'],reason=reasons.get(c,'variantBudget')) for c in omitted],
        countingKind='notCounted',encodedEnvelopeBytes=len(encode(envelope)),indexBytes=len(encode(envelope['index'])))


class ContextPackCandidates(_Record):
    @classmethod
    def _create(cls,spec,snapshot,policy,variants,reports):
        instance=object.__new__(cls)
        instance._own(dict(version=1,spec=spec,snapshot=snapshot,policy=policy.to_dict(),variants=variants,reports=reports), maximum=8388608,depth=48)
        return instance

    @property
    def candidate_identity(self): return self.identity

    @property
    def snapshot(self): return ContextSnapshot.from_dict(self.to_dict()['snapshot'])

    @property
    def spec(self): return ContextPackSpec.from_dict(self.to_dict()['spec'])

    @classmethod
    def from_dict(cls,value):
        closed(value,{'version','spec','snapshot','policy','variants','reports'})
        encode(value,maximum=8388608,depth=48)
        if type(value['version']) is not int or value['version']!=1: raise ContextPackError()
        policy=ContextPackPolicy.from_dict(value['policy'])
        spec=ContextPackSpec.from_dict(value['spec']);snapshot=ContextSnapshot.from_dict(value['snapshot'])
        _validate_capture(snapshot.to_dict(),spec.to_dict(),policy)
        variants=value['variants'];reports=value['reports']
        if (type(variants) is not list or not 1<=len(variants)<=policy.max_variants
                or type(reports) is not list or len(reports)!=len(variants)):
            raise ContextPackError()
        total=0;previous=None
        for index,(envelope,report) in enumerate(zip(variants,reports)):
            reference=dict(specDigest=spec.identity,snapshotIdentity=snapshot.identity,
                selectedVariantIndex=index,envelopeDigest=digest(envelope),reportDigest=digest(report),renderVersion=RENDER_VERSION)
            reference['packIdentity']=digest(reference)
            PreparedContextPack.from_dict(dict(version=1,spec=spec.to_dict(),snapshot=snapshot.to_dict(),
                envelope=envelope,report=report,reference=reference))
            size=len(encode(envelope));total+=size
            if size>policy.max_inline_bytes or len(encode(envelope['index']))>policy.max_index_bytes:
                raise ContextPackError('contextPackLimit')
            selected={entry['citationId'] for entry in envelope['items']}
            if previous is not None and not selected<previous: raise ContextPackError('contextBindingMismatch')
            previous=selected
        if total>policy.max_variant_bytes: raise ContextPackError('contextPackLimit')
        if any(not any(spec.slots[n].required for n in item['slotIndexes']) for item in variants[-1]['items']):
            raise ContextPackError('contextBindingMismatch')
        return cls._create(spec.to_dict(),snapshot.to_dict(),policy,variants,reports)

    def safe_report(self,index):
        reports=self.reports
        integer(index,0,len(reports)-1)
        return {k:reports[index][k] for k in ('selectedItemCount','deferredItemCount','omittedItemCount','requiredCoverageComplete','countingKind')}


class PreparedContextPack(_Record):
    @classmethod
    def _create(cls,spec,snapshot,envelope,report,reference):
        result=object.__new__(cls)
        result._own(dict(version=1,spec=spec,snapshot=snapshot,envelope=envelope,report=report,reference=reference),maximum=8388608,depth=48)
        return result

    @property
    def pack_identity(self): return self.reference['packIdentity']

    @property
    def snapshot(self): return ContextSnapshot.from_dict(self.to_dict()['snapshot'])

    @property
    def spec(self): return ContextPackSpec.from_dict(self.to_dict()['spec'])

    @classmethod
    def from_dict(cls,value):
        closed(value,{'version','spec','snapshot','envelope','report','reference'})
        encode(value,maximum=8388608,depth=48)
        if type(value['version']) is not int or value['version']!=1: raise ContextPackError()
        spec=ContextPackSpec.from_dict(value['spec']); snapshot=ContextSnapshot.from_dict(value['snapshot'])
        ref=value['reference']
        closed(ref,{'specDigest','snapshotIdentity','selectedVariantIndex','envelopeDigest','reportDigest','renderVersion','packIdentity'})
        integer(ref['selectedVariantIndex'],0,7)
        expected=dict(specDigest=spec.identity,snapshotIdentity=snapshot.identity,
            selectedVariantIndex=ref['selectedVariantIndex'],envelopeDigest=digest(value['envelope']),
            reportDigest=digest(value['report']),renderVersion=RENDER_VERSION)
        if {**expected,'packIdentity':digest(expected)}!=ref: raise ContextPackError('contextBindingMismatch')
        # Verify the selected projection directly, without refitting variants or invoking callbacks.
        units,slots=_resolve(spec.to_dict(),snapshot.to_dict(),lambda:None)
        envelope=value['envelope']
        closed(envelope,{'version','format','items','index','coverage'})
        if type(envelope['items']) is not list: raise ContextPackError()
        selected=set()
        for item in envelope['items']:
            if type(item) is not dict or type(item.get('citationId')) is not str: raise ContextPackError()
            citation=item['citationId']
            if citation not in units or not units[citation]['inline'] or citation in selected: raise ContextPackError()
            selected.add(citation)
        if any(u['required'] and c not in selected for c,u in units.items()): raise ContextPackError('requiredContextMissing')
        if _envelope(units,slots,selected)!=envelope: raise ContextPackError('contextBindingMismatch')
        report=value['report']
        if type(report) is not dict or type(report.get('omissions')) is not list: raise ContextPackError()
        reasons={v['citationId']:v['reason'] for v in report['omissions'] if type(v) is dict and set(v)=={'citationId','slotIndexes','reason'}}
        if any(v not in {'byteLimit','variantBudget'} for v in reasons.values()) or _report(envelope,units,reasons)!=report:
            raise ContextPackError('contextBindingMismatch')
        return cls._create(spec.to_dict(),snapshot.to_dict(),envelope,report,ref)


class ContextPacker:
    def __init__(self, *, policy=ContextPackPolicy()):
        if type(policy) is not ContextPackPolicy: raise ContextPackError()
        self.policy=policy

    def compose(self,spec,snapshot):
        if type(spec) is not ContextPackSpec or type(snapshot) is not ContextSnapshot:
            raise ContextPackError()
        start=_clock(); policy=self.policy
        def check():
            if (_clock()-start)*1000>=policy.composition_timeout_ms: raise ContextPackError('contextPackLimit')
        document=snapshot.to_dict(); declaration=spec.to_dict()
        _validate_capture(document,declaration,policy,check)
        units,slots=_resolve(declaration,document,check)
        mandatory={c for c,u in units.items() if u['required']}
        optional=sorted((c for c,u in units.items() if u['inline'] and not u['required']),key=lambda c:units[c]['priority'])
        def admitted(selected):
            check()
            envelope=_envelope(units,slots,selected)
            if len(encode(envelope['index']))>policy.max_index_bytes: raise ContextPackError('contextPackLimit')
            return envelope if len(encode(envelope))<=policy.max_inline_bytes else None
        base=admitted(mandatory)
        if base is None: raise ContextPackError('contextPackLimit')
        selected=set(mandatory); reasons={}
        if policy.max_variants>1:
            for citation in optional:
                if admitted(selected|{citation}) is None: reasons[citation]='byteLimit'
                else: selected.add(citation)
        kept=[c for c in optional if c in selected]
        group=max(1,math.ceil(len(kept)/(policy.max_variants-1))) if policy.max_variants>1 else 1
        selections=[set(selected)]
        for offset in range(0,len(kept),group):
            selected-=set(list(reversed(kept))[offset:offset+group])
            selections.append(set(selected))
        variants=[];reports=[];total_bytes=0
        for selected in selections:
            check()
            envelope=admitted(selected)
            if envelope is None: raise ContextPackError('contextPackLimit')
            total_bytes+=len(encode(envelope))
            if total_bytes>policy.max_variant_bytes: raise ContextPackError('contextPackLimit')
            variants.append(envelope); reports.append(_report(envelope,units,reasons))
        check()
        result=ContextPackCandidates._create(declaration,document,policy,variants,reports)
        check()
        return result

    def select(self,candidates,index,envelope_digest):
        if type(candidates) is not ContextPackCandidates: raise ContextPackError()
        value=candidates.to_dict()
        integer(index,0,len(value['variants'])-1); _hash(envelope_digest)
        envelope=value['variants'][index]; report=value['reports'][index]
        if digest(envelope)!=envelope_digest: raise ContextPackError('contextBindingMismatch')
        reference=dict(specDigest=digest(value['spec']),snapshotIdentity=digest(value['snapshot']),
            selectedVariantIndex=index,envelopeDigest=envelope_digest,reportDigest=digest(report),renderVersion=RENDER_VERSION)
        reference['packIdentity']=digest(reference)
        return PreparedContextPack._create(value['spec'],value['snapshot'],envelope,report,reference)
