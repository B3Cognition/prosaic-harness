"""Owned, bounded context data. Construction has no source or permission effects."""
from dataclasses import dataclass, fields
import hashlib
from pathlib import PurePosixPath
from .codec import (ContextPackError, closed, decode, encode, integer,
                    locator as admit_locator, reference)


@dataclass(frozen=True)
class ContextPackPolicy:
    max_source_aliases: int = 16
    max_slots: int = 32
    max_captured_items: int = 128
    max_item_bytes: int = 262144
    max_total_content_bytes: int = 2097152
    max_snapshot_bytes: int = 3145728
    max_inline_bytes: int = 49152
    max_index_bytes: int = 8192
    max_variants: int = 8
    max_variant_bytes: int = 524288
    max_labels_per_item: int = 16
    max_json_depth: int = 32
    max_json_nodes: int = 16384
    composition_timeout_ms: int = 250

    def __post_init__(self):
        for f in fields(self):
            integer(getattr(self, f.name), 1)
        if self.max_json_depth > 64 or self.max_variants > 8:
            raise ContextPackError()

    def to_dict(self):
        return {_camel(f.name): getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, value):
        names = {_camel(f.name): f.name for f in fields(cls)}
        closed(value, names)
        return cls(**{names[k]: v for k, v in value.items()})


def _camel(name):
    head, *tail = name.split('_')
    return head + ''.join(p.title() for p in tail)


@dataclass(frozen=True, init=False)
class _Record:
    _encoded: bytes

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        def immutable(self, *args):
            raise AttributeError('immutable context record')
        cls.__setattr__ = immutable
        cls.__delattr__ = immutable

    def _own(self, document, **limits):
        object.__setattr__(self, '_encoded', encode(document, **limits))

    def to_dict(self):
        return decode(self._encoded)

    @property
    def identity(self):
        return hashlib.sha256(self._encoded).hexdigest()

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        document = self.to_dict()
        key = _camel(name)
        if key not in document:
            raise AttributeError(name)
        return document[key]


class ContextScope(_Record):
    def __init__(self, namespace, environment, application, tenant, actor, billing_account=None):
        document = dict(namespace=namespace, environment=environment, application=application,
                        tenant=tenant, actor=actor, billingAccount=billing_account)
        for key, value in document.items():
            if key != 'billingAccount' or value is not None:
                reference(value)
        self._own(document)

    @classmethod
    def from_dict(cls, value):
        closed(value, {'namespace','environment','application','tenant','actor','billingAccount'})
        return cls(*(value[k] for k in ('namespace','environment','application','tenant','actor','billingAccount')))

    @classmethod
    def from_conversation(cls, scope):
        from ..conversation_bindings import ConversationScope
        if type(scope) is not ConversationScope:
            raise ContextPackError('contextScopeMismatch')
        return cls.from_dict(scope.to_dict())


class ContextSource(_Record):
    def __init__(self, alias, identity, revision, outcome, *, ranked_item_ids=()):
        for value in (alias, identity, revision): reference(value)
        if type(outcome) is not str or outcome not in {'complete','partial','unavailable'}:
            raise ContextPackError()
        ranked = _references(ranked_item_ids, 128)
        self._own(dict(alias=alias, sourceIdentity=identity, revision=revision,
                       outcome=outcome, rankedItemIds=ranked))

    @property
    def source_identity(self):
        return self.to_dict()['sourceIdentity']

    @property
    def ranked_item_ids(self):
        return tuple(self.to_dict()['rankedItemIds'])

    @classmethod
    def from_dict(cls, value):
        closed(value, {'alias','sourceIdentity','revision','outcome','rankedItemIds'})
        return cls(value['alias'], value['sourceIdentity'], value['revision'], value['outcome'], ranked_item_ids=value['rankedItemIds'])


def _references(values, maximum):
    if type(values) not in (tuple, list) or len(values) > maximum:
        raise ContextPackError()
    result = [reference(v) for v in values]
    if len(set(result)) != len(result):
        raise ContextPackError()
    return result


def _labels(value, *, filters=False):
    if value is None: return {}
    if type(value) is not dict or len(value) > 16:
        raise ContextPackError()
    result = {}
    for key, child in value.items():
        reference(key)
        values = child if filters else [child]
        if type(values) not in (tuple, list) or not values or len(values) > 128:
            raise ContextPackError()
        for scalar in values:
            if type(scalar) not in (str, int, float, bool, type(None)):
                raise ContextPackError()
            encode(scalar, maximum=512)
        if filters:
            canonical = {encode(v): v for v in values}
            result[key] = [canonical[k] for k in sorted(canonical)]
        else:
            result[key] = child
    return result


class ContextItem(_Record):
    def __init__(self, item_id, source_alias, source_revision, content, *, locator=None,
                 label=None, labels=None, derived_from=()):
        for value in (item_id, source_alias, source_revision): reference(value)
        if label is not None: reference(label)
        encoded = encode(content, maximum=1572866 if type(content) is str else 262144, depth=32, nodes=16384)
        content_bytes = content.encode('utf-8') if type(content) is str else encoded
        if len(content_bytes)>262144: raise ContextPackError('contextSnapshotLimit')
        if type(derived_from) not in (tuple, list) or len(derived_from) > 128:
            raise ContextPackError()
        provenance=[]
        for link in derived_from:
            closed(link, {'sourceAlias','itemId','contentSha256'})
            reference(link['sourceAlias']); reference(link['itemId']); _hash(link['contentSha256'])
            provenance.append(link)
        self._own(dict(itemId=item_id, sourceAlias=source_alias, sourceRevision=source_revision,
            content=content, contentKind='text' if type(content) is str else 'json',
            contentSha256=hashlib.sha256(content_bytes).hexdigest(), locator=admit_locator(locator),
            label=label, labels=_labels(labels), derivedFrom=provenance), maximum=3145728, depth=36)

    @classmethod
    def from_dict(cls, value):
        closed(value, {'itemId','sourceAlias','sourceRevision','content','contentKind','contentSha256','locator','label','labels','derivedFrom'})
        result=cls(value['itemId'], value['sourceAlias'], value['sourceRevision'], value['content'],
            locator=value['locator'], label=value['label'], labels=value['labels'], derived_from=value['derivedFrom'])
        if result.to_dict() != value:
            raise ContextPackError()
        return result


def _hash(value):
    import re
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ContextPackError()
    return value


class ContextSnapshot(_Record):
    @classmethod
    def from_items(cls, items, *, sources, scope_binding):
        if (type(scope_binding) is not ContextScope or type(items) not in (list,tuple)
                or type(sources) not in (list,tuple) or not 1 <= len(sources) <= 16 or len(items) > 128
                or any(type(i) is not ContextItem for i in items)
                or any(type(s) is not ContextSource for s in sources)):
            raise ContextPackError()
        source_map = {s.alias:s for s in sources}
        if len(source_map) != len(sources): raise ContextPackError()
        seen=set(); size=0
        for item in items:
            key=(item.source_alias,item.item_id)
            source=source_map.get(item.source_alias)
            if key in seen or source is None or source.revision != item.source_revision or source.outcome == 'unavailable':
                raise ContextPackError()
            seen.add(key)
            size += len(item.content.encode('utf-8')) if item.content_kind == 'text' else len(encode(item.content))
        if size > 2097152: raise ContextPackError('contextSnapshotLimit')
        if any((s.alias,i) not in seen for s in sources for i in s.ranked_item_ids):
            raise ContextPackError()
        result=object.__new__(cls)
        result._own(dict(version=1, scopeBinding=scope_binding.to_dict(),
            sources=[source_map[k].to_dict() for k in sorted(source_map)],
            items=[i.to_dict() for i in sorted(items,key=lambda i:(i.source_alias,i.item_id))]), maximum=3145728, depth=40)
        return result

    @property
    def items(self): return tuple(ContextItem.from_dict(v) for v in self.to_dict()['items'])

    @property
    def sources(self): return tuple(ContextSource.from_dict(v) for v in self.to_dict()['sources'])

    @property
    def scope_binding(self): return ContextScope.from_dict(self.to_dict()['scopeBinding'])

    @classmethod
    def from_dict(cls, value):
        closed(value, {'version','scopeBinding','sources','items'})
        encode(value, maximum=3145728, depth=40, nodes=65536)
        if type(value['version']) is not int or value['version'] != 1 or type(value['items']) is not list or type(value['sources']) is not list:
            raise ContextPackError()
        return cls.from_items([ContextItem.from_dict(v) for v in value['items']],
            sources=[ContextSource.from_dict(v) for v in value['sources']], scope_binding=ContextScope.from_dict(value['scopeBinding']))


class ContextSlot(_Record):
    def __init__(self, source, *, item_ids=(), labels=None, required=False, min_items=None,
                 max_items=1, priority=0, representation=None, availability='inline', allow_partial=False):
        reference(source)
        if type(required) is not bool or type(allow_partial) is not bool:
            raise ContextPackError()
        minimum=(1 if required else 0) if min_items is None else min_items
        integer(minimum,0,128); integer(max_items,1,128); integer(priority,-2**31,2**31-1)
        if minimum>max_items or (not required and minimum != 0): raise ContextPackError()
        if type(availability) is not str or availability not in {'inline','discoverable'} or (required and availability!='inline'):
            raise ContextPackError()
        self._own(dict(source=source, itemIds=_references(item_ids,128), labels=_labels(labels,filters=True),
            required=required,minItems=minimum,maxItems=max_items,priority=priority,
            representation=admit_locator(representation,representation=True), availability=availability,allowPartial=allow_partial))

    @property
    def item_ids(self): return tuple(self.to_dict()['itemIds'])

    @classmethod
    def from_dict(cls, value):
        closed(value, {'source','itemIds','labels','required','minItems','maxItems','priority','representation','availability','allowPartial'})
        if value['minItems'] is None: raise ContextPackError()
        return cls(value['source'], item_ids=value['itemIds'],labels=value['labels'],required=value['required'],
            min_items=value['minItems'],max_items=value['maxItems'],priority=value['priority'],
            representation=value['representation'],availability=value['availability'],allow_partial=value['allowPartial'])


class ContextPackSpec(_Record):
    def __init__(self, identity, version, slots, *, task_source=None):
        reference(identity); reference(version)
        if type(slots) not in (tuple,list) or not slots or len(slots)>32 or any(type(s) is not ContextSlot for s in slots):
            raise ContextPackError()
        if task_source is not None:
            reference(task_source)
            task=[s for s in slots if s.source == task_source]
            if (len(task)!=1 or not task[0].required or task[0].min_items!=1 or task[0].max_items!=1
                    or task[0].availability!='inline' or task[0].representation!={'kind':'whole'}):
                raise ContextPackError()
        self._own(dict(specIdentity=identity,version=version,slots=[s.to_dict() for s in slots],taskSource=task_source))

    @property
    def spec_identity(self): return self.to_dict()['specIdentity']

    @property
    def slots(self): return tuple(ContextSlot.from_dict(v) for v in self.to_dict()['slots'])

    @classmethod
    def from_dict(cls,value):
        closed(value, {'specIdentity','version','slots','taskSource'})
        if type(value['slots']) is not list: raise ContextPackError()
        return cls(value['specIdentity'],value['version'],[ContextSlot.from_dict(v) for v in value['slots']],task_source=value['taskSource'])


class InputSource(_Record):
    def __init__(self, pointer):
        from .codec import pointer as admit_pointer
        self._own({'kind':'input','pointer':admit_pointer(pointer)})

    @classmethod
    def from_dict(cls,value):
        closed(value, {'kind','pointer'})
        if value['kind']!='input': raise ContextPackError()
        return cls(value['pointer'])


class EvidenceSource(_Record):
    def __init__(self, path):
        reference(path,4096)
        if PurePosixPath(path).is_absolute() or '\\' in path or any(p in {'','..','.'} for p in path.split('/')):
            raise ContextPackError()
        self._own({'kind':'evidence','path':path})

    @classmethod
    def from_dict(cls,value):
        closed(value, {'kind','path'})
        if value['kind']!='evidence': raise ContextPackError()
        return cls(value['path'])


class ArtifactSource(_Record):
    def __init__(self, step):
        self._own({'kind':'artifact','step':reference(step)})

    @classmethod
    def from_dict(cls,value):
        closed(value, {'kind','step'})
        if value['kind']!='artifact': raise ContextPackError()
        return cls(value['step'])
