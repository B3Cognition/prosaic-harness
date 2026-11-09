"""Normalize admitted input, captured files and accepted outputs without I/O."""
import hashlib
import re
from .bindings import ContextPackBindings
from .codec import ContextPackError,decode,digest,encode,reference
from .types import ContextPackSpec,ContextItem,ContextSource,ContextSnapshot,InputSource,EvidenceSource,ArtifactSource
from .selection import project


def source_identity(source):
    return 'source_'+digest(source.to_dict())


def resolve_pack(step,agent,bindings):
    if bindings is None:
        if type(step) is dict and 'contextPack' in step: raise ContextPackError('contextCapabilityMissing')
        return None
    if type(bindings) is not ContextPackBindings: raise ContextPackError()
    if type(step) is str:
        node=step;definition={'kind':'agent','agent':agent}
    elif type(step) is dict:
        if step.get('agent',agent)!=agent: raise ContextPackError('contextBindingMismatch')
        if 'id' not in step and bindings.required_packs['nodes']: raise ContextPackError('contextBindingMismatch')
        node=step.get('id',agent);definition={**step,'agent':agent}
    else: raise ContextPackError()
    alias=bindings.resolve(node,definition)
    return bindings.specs[alias] if alias is not None else None


def artifact_revision(binding):
    return digest(binding)


def capture_sources(spec,original_arguments,evidence,bindings):
    if type(spec) is not ContextPackSpec or type(bindings) is not ContextPackBindings:
        raise ContextPackError()
    bindings.readmit()
    arguments=decode(encode(original_arguments))
    ledger=decode(encode(evidence))
    if type(arguments) is not dict or 'request' not in arguments or type(ledger) is not dict:
        raise ContextPackError()
    sources=bindings.sources
    if spec.task_source is not None and type(sources.get(spec.task_source)) is not InputSource:
        raise ContextPackError('requiredContextMissing')
    items=[];captures=[]
    for alias in sorted({slot.source for slot in spec.slots}):
        source=sources.get(alias)
        if source is None: raise ContextPackError('contextBindingMismatch')
        identity=source_identity(source)
        revision=digest(source.to_dict());outcome='unavailable';content=None;locator={'kind':'whole'}
        if type(source) is InputSource:
            locator={'kind':'jsonPointer','pointer':source.pointer}
            try:
                content=project(arguments['request'],locator)
                revision=digest(content)
                outcome='complete'
            except ContextPackError:
                pass  # Missing is captured explicitly; it never starts a resolver.
        elif type(source) is EvidenceSource:
            capture=ledger.get(source.path)
            if capture is not None:
                if type(capture) is not dict or type(capture.get('text')) is not str:
                    raise ContextPackError('contextBindingMismatch')
                content=capture['text']
                try: revision=hashlib.sha256(content.encode('utf-8',errors='strict')).hexdigest()
                except UnicodeError: raise ContextPackError() from None
                if capture.get('sha256')!=revision: raise ContextPackError('contextBindingMismatch')
                outcome='complete'
        elif type(source) is ArtifactSource:
            artifacts=arguments.get('artifacts',{});accepted=arguments.get('artifact_bindings',{})
            if type(artifacts) is not dict or type(accepted) is not dict: raise ContextPackError()
            has_value=source.step in artifacts;has_binding=source.step in accepted
            if has_value!=has_binding: raise ContextPackError('contextBindingMismatch')
            if has_value:
                binding=accepted[source.step]
                if (type(binding) is not dict or type(binding.get('id')) is not str
                        or not re.fullmatch('[0-9a-f]{32}',binding['id']) or type(binding.get('dependencies')) is not dict):
                    raise ContextPackError('contextBindingMismatch')
                from ..workflow import digest as workflow_digest
                content=artifacts[source.step]
                if binding.get('sha256')!=workflow_digest(content): raise ContextPackError('contextBindingMismatch')
                revision=artifact_revision(binding)
                locator={'kind':'record','id':source.step}
                outcome='complete'
        captures.append(ContextSource(alias,identity,revision,outcome))
        if outcome=='complete':
            items.append(ContextItem('root',alias,revision,content,locator=locator))
    return ContextSnapshot.from_items(items,sources=captures,scope_binding=bindings.scope)
