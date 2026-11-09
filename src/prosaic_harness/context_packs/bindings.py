"""Trusted, inert source registrations and per-node declaration admission."""
from dataclasses import dataclass
from types import MappingProxyType
from .codec import ContextPackError,closed,decode,encode,reference
from .types import (ContextScope,ContextPackSpec,ContextSlot,InputSource,EvidenceSource,
                    ArtifactSource,_Record)


@dataclass(frozen=True)
class ContextAuthorizer:
    identity: str
    version: str
    authorize: object

    def __post_init__(self):
        reference(self.identity);reference(self.version)
        if not callable(self.authorize): raise ContextPackError()

    def descriptor(self):
        self.__post_init__()
        return dict(identity=self.identity,version=self.version)


def _map(values,maximum=128):
    if values is None: return {}
    if type(values) is not dict or len(values)>maximum: raise ContextPackError()
    return {reference(k):reference(v) for k,v in values.items()}


class ContextPackBindings(_Record):
    def __init__(self,*,specs,sources,scope,authorizer,agent_defaults=None,required_packs=None):
        if (type(specs) is not dict or len(specs)>32 or type(sources) is not dict or not 1<=len(sources)<=256
                or type(scope) is not ContextScope or type(authorizer) is not ContextAuthorizer):
            raise ContextPackError()
        owned_specs={};owned_sources={}
        for alias,spec in specs.items():
            reference(alias)
            if type(spec) is not ContextPackSpec: raise ContextPackError()
            owned_specs[alias]=ContextPackSpec.from_dict(spec.to_dict())
        for alias,source in sources.items():
            reference(alias)
            if type(source) not in (InputSource,EvidenceSource,ArtifactSource): raise ContextPackError()
            owned_sources[alias]=type(source).from_dict(source.to_dict())
        defaults=_map(agent_defaults)
        pins={'agents':{},'nodes':{}} if required_packs is None else required_packs
        closed(pins,{'agents','nodes'})
        pins={k:_map(v) for k,v in pins.items()}
        if any(alias not in owned_specs for alias in [*defaults.values(),*pins['agents'].values(),*pins['nodes'].values()]):
            raise ContextPackError('contextBindingMismatch')
        self._own(dict(version=1,specs={k:v.to_dict() for k,v in owned_specs.items()},
            sources={k:v.to_dict() for k,v in owned_sources.items()},scope=scope.to_dict(),
            authorizer=authorizer.descriptor(),agentDefaults=defaults,requiredPacks=pins),maximum=8388608)
        object.__setattr__(self,'_specs',MappingProxyType(owned_specs))
        object.__setattr__(self,'_sources',MappingProxyType(owned_sources))
        object.__setattr__(self,'_authorizer',authorizer)

    @property
    def specs(self): return dict(self._specs)

    @property
    def sources(self): return dict(self._sources)

    @property
    def scope(self): return ContextScope.from_dict(self.to_dict()['scope'])

    @property
    def authorizer(self): return self._authorizer

    def readmit(self):
        if self._authorizer.descriptor()!=self.to_dict()['authorizer']:
            raise ContextPackError('contextBindingMismatch')
        return self.to_dict()

    def frozen_copy(self):
        document=self.readmit()
        return ContextPackBindings(specs=self.specs,sources=self.sources,scope=self.scope,
            authorizer=ContextAuthorizer(self._authorizer.identity,self._authorizer.version,self._authorizer.authorize),
            agent_defaults=document['agentDefaults'],required_packs=document['requiredPacks'])

    def resolve(self,node,step,*,agent_defaults=None):
        document=self.readmit()
        explicit='contextPack' in step
        if step.get('kind')!='agent':
            if explicit: raise ContextPackError()
            return None
        agent=step.get('agent');reference(node);reference(agent)
        defaults=document['agentDefaults'] if agent_defaults is None else _map(agent_defaults)
        selected=step['contextPack'] if explicit else defaults.get(agent)
        if explicit: reference(selected)
        pins=document['requiredPacks']
        required={v for v in (pins['agents'].get(agent),pins['nodes'].get(node)) if v is not None}
        if len(required)>1: raise ContextPackError('contextBindingMismatch')
        pinned=next(iter(required),None)
        if selected is None: selected=pinned
        if selected is not None and selected not in self._specs: raise ContextPackError('contextBindingMismatch')
        if pinned is not None and selected!=pinned: raise ContextPackError('contextBindingMismatch')
        return selected


def _yaml_spec(alias,value):
    closed(value,{'version','slots','taskSource'})
    if type(value['slots']) is not list or len(value['slots'])>32: raise ContextPackError()
    slots=[]
    fields={'itemIds':'item_ids','labels':'labels','required':'required','minItems':'min_items',
            'maxItems':'max_items','priority':'priority','representation':'representation',
            'availability':'availability','allowPartial':'allow_partial'}
    for raw in value['slots']:
        closed(raw,{'source'},fields)
        if 'minItems' in raw and raw['minItems'] is None: raise ContextPackError()
        slots.append(ContextSlot(raw['source'],**{fields[k]:v for k,v in raw.items() if k!='source'}))
    return ContextPackSpec(alias,value['version'],slots,task_source=value['taskSource'])


def admit_options(feedback_catalog=None,repeatable_validators=None):
    catalog={} if feedback_catalog is None else feedback_catalog
    if type(catalog) is not dict or len(catalog)>64: raise ContextPackError()
    for code,text in catalog.items():
        reference(code)
        if type(text) is not str: raise ContextPackError()
        encode({code:text},maximum=512)
    catalog=decode(encode(catalog,maximum=32768))
    validators=() if repeatable_validators is None else repeatable_validators
    if type(validators) not in (set,frozenset,list,tuple) or len(validators)>128: raise ContextPackError()
    validators=[reference(v) for v in validators]
    if len(set(validators))!=len(validators): raise ContextPackError()
    return catalog,tuple(sorted(validators))


def attach(workflow,bindings,*,feedback_catalog=None,repeatable_validators=None,trusted=True):
    raw=workflow.definition
    declared=raw.get('contextPacks',{})
    defaults=raw.get('agentContextPacks',{})
    if not trusted and ('contextPacks' in raw or 'agentContextPacks' in raw): raise ContextPackError()
    if type(declared) is not dict or len(declared)>32 or type(defaults) is not dict: raise ContextPackError()
    _map(defaults)
    known_agents={step['agent'] for step in raw['steps'].values() if step.get('kind')=='agent'}
    if set(defaults)-known_agents: raise ContextPackError('contextBindingMismatch')
    if bindings is None:
        if declared or defaults or any('contextPack' in s for s in raw['steps'].values()):
            raise ContextPackError('contextCapabilityMissing')
        if feedback_catalog is not None or repeatable_validators is not None: raise ContextPackError()
        return
    if type(bindings) is not ContextPackBindings: raise ContextPackError()
    document=bindings.readmit(); specs=bindings.specs
    for alias,definition in declared.items():
        reference(alias)
        spec=_yaml_spec(alias,definition)
        if alias in specs and spec.to_dict()!=specs[alias].to_dict(): raise ContextPackError('contextBindingMismatch')
        specs[alias]=spec
    merged_defaults={**document['agentDefaults'],**defaults}
    binding=ContextPackBindings(specs=specs,sources=bindings.sources,scope=bindings.scope,authorizer=bindings.authorizer,
        agent_defaults=merged_defaults,required_packs=document['requiredPacks'])
    workflow._context_packs=binding
    workflow._feedback_catalog,workflow._repeatable_validators=admit_options(feedback_catalog,repeatable_validators)
    validate_workflow(workflow)


def validate_workflow(workflow):
    binding=getattr(workflow,'_context_packs',None)
    if binding is None: return {}
    if type(binding) is not ContextPackBindings: raise ContextPackError('contextBindingMismatch')
    document=binding.readmit()
    steps=workflow.definition['steps']
    if any(node not in steps or steps[node].get('kind')!='agent' for node in document['requiredPacks']['nodes']):
        raise ContextPackError('contextBindingMismatch')
    admit_options(getattr(workflow,'_feedback_catalog',None),getattr(workflow,'_repeatable_validators',None))
    resolved={}
    for node,step in workflow.definition['steps'].items():
        alias=binding.resolve(node,step)
        if alias is None: continue
        from ..workflow_rules import CAPS
        limits=workflow.definition['limits']
        if any(type(limits.get(key)) is not int or limits[key]<0 for key in CAPS):
            raise ContextPackError('contextBindingMismatch')
        spec=binding.specs[alias];sources=binding.sources
        if spec.task_source is None or type(sources.get(spec.task_source)) is not InputSource:
            raise ContextPackError('requiredContextMissing')
        dependencies=set(step.get('inputs',[]));optional=set(step.get('optional_inputs',[]))
        coverage=set()
        for slot in spec.slots:
            source=sources.get(slot.source)
            if source is None: raise ContextPackError('contextBindingMismatch')
            if type(source) is EvidenceSource and source.path not in workflow.definition.get('evidence',[]):
                raise ContextPackError('contextBindingMismatch')
            if type(source) is ArtifactSource:
                if source.step not in dependencies|optional: raise ContextPackError('contextBindingMismatch')
                if slot.required and slot.availability=='inline': coverage.add(source.step)
        if dependencies-coverage: raise ContextPackError('requiredContextMissing')
        if step.get('acquisition') or step.get('require_reads'): raise ContextPackError('contextCapabilityMissing')
        artifact=workflow.artifacts[node]
        if '{{args}}' in artifact.body or any('{{args}}' in r['content'] for r in artifact.resources):
            raise ContextPackError('contextCapabilityMissing')
        from prosaic_runtime import ProsaicRuntime
        if not {'conversation_turn_v1','frozen_turn_inputs_v1'}<=getattr(ProsaicRuntime,'capabilities',frozenset()):
            raise ContextPackError('contextCapabilityMissing')
        from ..workflow_rules import compiled
        ruleset=compiled(workflow).get(node)
        if ruleset is not None and not {'rule_admission_v1','guard_input_views_v1'}<=getattr(ProsaicRuntime,'capabilities',frozenset()):
            raise ContextPackError('contextCapabilityMissing')
        if ruleset is not None and any(b.bound and getattr(b.guard,'input_access','shared')=='shared' for b in ruleset.bindings):
            raise ContextPackError('contextCapabilityMissing')
        resolved[node]=alias
    needed={v for step in workflow.definition['steps'].values() for v in step.get('validators',[])}
    if resolved and needed-set(getattr(workflow,'_repeatable_validators',())):
        raise ContextPackError('contextBindingMismatch')
    return resolved


def material(workflow):
    binding=getattr(workflow,'_context_packs',None)
    if binding is None: return {}
    validate_workflow(workflow)
    return {'context_pack_bindings':binding.readmit(),
            'context_feedback':dict(workflow._feedback_catalog),
            'repeatable_validators':list(workflow._repeatable_validators)}
