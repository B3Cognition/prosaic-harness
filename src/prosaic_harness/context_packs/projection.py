"""Declared model evidence and a separately frozen complete validation view."""
from .codec import ContextPackError,closed,decode,digest,encode,reference,integer
from .types import _Record,ArtifactSource,InputSource,ContextPackSpec,_hash
from .selection import ContextPackCandidates,project
from .sources import source_identity,artifact_revision

MODEL_PROFILE='workflow-pack-input-v1'
AUTHORITATIVE_PROFILE='workflow-guard-input-v1'


class FrozenCheckContext(_Record):
    @classmethod
    def from_context(cls,context):
        from ..validation import CheckContext
        if type(context) is not CheckContext: raise ContextPackError('contextBindingMismatch')
        return cls.from_dict(dict(version=1,step=context.step,request=context.request,artifacts=context.artifacts,
            evidence=context.evidence,bindings=context.bindings,humanResponses=context.human_responses,
            terminalCompletion=context.terminal_completion))

    @classmethod
    def from_dict(cls,value):
        closed(value,{'version','step','request','artifacts','evidence','bindings','humanResponses','terminalCompletion'})
        if type(value['version']) is not int or value['version']!=1: raise ContextPackError()
        reference(value['step'])
        if any(type(value[k]) is not dict for k in ('artifacts','evidence','bindings','humanResponses')):
            raise ContextPackError()
        if value['terminalCompletion'] is not None and type(value['terminalCompletion']) is not dict: raise ContextPackError()
        result=object.__new__(cls);result._own(value,maximum=8388608)
        return result

    def to_check_context(self):
        from ..validation import CheckContext
        value=self.to_dict()
        return CheckContext(value['step'],value['request'],value['artifacts'],value['evidence'],value['bindings'],value['humanResponses'],value['terminalCompletion'])


def validation_exposures(bindings,context):
    """Describe every declared origin in the wider private controller view.

    This is metadata-only validation over already retained facts, independent
    of the model pack's slot/source limits. It never reads a file or producer.
    """
    import hashlib
    from .bindings import ContextPackBindings
    from .types import EvidenceSource,ContextSource
    from .authorization import ExposureBindings,_entry
    from .selection import _content_bytes
    if type(bindings) is not ContextPackBindings: raise ContextPackError()
    bindings.readmit();value=FrozenCheckContext.from_context(context).to_dict()
    entries=[]
    for alias,source in bindings.sources.items():
        revision=digest(source.to_dict());outcome='unavailable';content=None;origin={'kind':'whole'}
        if type(source) is InputSource:
            origin={'kind':'jsonPointer','pointer':source.pointer}
            try: content=project(value['request'],origin)
            except ContextPackError: pass
            else: revision=digest(content);outcome='complete'
        elif type(source) is EvidenceSource:
            record=value['evidence'].get(source.path)
            if record is not None:
                if type(record) is not dict or type(record.get('text')) is not str: raise ContextPackError('contextBindingMismatch')
                content=record['text'];revision=hashlib.sha256(content.encode('utf-8')).hexdigest()
                if revision!=record.get('sha256'): raise ContextPackError('contextBindingMismatch')
                outcome='complete'
        elif type(source) is ArtifactSource:
            present=source.step in value['artifacts'];bound=source.step in value['bindings']
            if present!=bound: raise ContextPackError('contextBindingMismatch')
            if present:
                from ..workflow import digest as artifact_digest
                binding=value['bindings'][source.step];content=value['artifacts'][source.step]
                if binding.get('sha256')!=artifact_digest(content): raise ContextPackError('contextBindingMismatch')
                revision=artifact_revision(binding);origin={'kind':'record','id':source.step};outcome='complete'
        else: raise ContextPackError()
        if outcome!='complete': continue
        declaration=ContextSource(alias,source_identity(source),revision,outcome).to_dict()
        entries.append(_entry(declaration,disclosure='validation'))
        if outcome=='complete':
            raw=_content_bytes(content)
            entries.append(_entry(declaration,item={'itemId':'root','locator':origin},disclosure='validation',
                representation={'kind':'whole'},content_sha256=hashlib.sha256(raw).hexdigest(),
                content_bytes=len(raw),content_kind='text' if type(content) is str else 'json'))
    return ExposureBindings(bindings.scope,entries)


def _feedback(arguments):
    # Raw validator diagnostics can contain private facts. The safe-feedback
    # policy adds admitted static catalogue text separately; never copy raw text.
    value=arguments.get('validation_feedback')
    if not value: return None
    from .feedback import SafeFeedback,safe_feedback
    if type(value) is SafeFeedback: return value.to_dict()
    if type(value) is dict: return SafeFeedback.from_dict(value).to_dict()
    return safe_feedback('validationFailed',None,1,{}).to_dict()


def _choices(arguments):
    responses=arguments.get('human_responses',{})
    if type(responses) is not dict: raise ContextPackError()
    choices={}
    for step,value in responses.items():
        reference(step)
        if type(value) is not dict or type(value.get('choice')) is not str: raise ContextPackError()
        choices[step]={'choice':reference(value['choice'])}
    return choices


def _model_root(step,arguments,envelope,spec,required):
    closed(envelope,{'version','format','items','index','coverage'})
    if type(envelope['items']) is not list or type(envelope['index']) is not list: raise ContextPackError()
    task=[i for i in envelope['items'] if i['sourceAlias']==spec.task_source]
    if len(task)!=1: raise ContextPackError('requiredContextMissing')
    locator=task[0]['sourceLocator']
    if (type(locator) is not dict or locator.get('kind')!='jsonPointer'
            or task[0]['representation']!={'kind':'whole'} or task[0]['sourceOutcome']!='complete'
            or task[0]['sourceIdentity']!=source_identity(InputSource(locator.get('pointer')))
            or task[0]['sourceRevision']!=digest(task[0]['content'])
            or encode(project(arguments['request'],locator))!=encode(task[0]['content'])):
        raise ContextPackError('contextBindingMismatch')
    selected=[*envelope['items'],*envelope['index']]
    for entry in selected:
        indexes=entry.get('slotIndexes')
        if type(indexes) is not list or not indexes: raise ContextPackError()
        for n in indexes: integer(n,0,len(spec.slots)-1)
        if len(set(indexes))!=len(indexes): raise ContextPackError()
    artifacts={}
    for producer in arguments['artifacts']:
        expected_identity=source_identity(ArtifactSource(producer))
        entries=[i for i in selected if i['sourceIdentity']==expected_identity and i['sourceLocator']=={'kind':'record','id':producer}]
        if producer in required:
            inline=[i for i in envelope['items'] if i in entries and any(spec.slots[n].required for n in i['slotIndexes'])]
            if not inline: raise ContextPackError('requiredContextMissing')
        if not entries: continue
        binding=arguments['artifact_bindings'].get(producer)
        if type(binding) is not dict: raise ContextPackError('contextBindingMismatch')
        for entry in entries:
            if entry['sourceRevision']!=artifact_revision(binding): raise ContextPackError('contextBindingMismatch')
            if 'content' in entry and encode(project(arguments['artifacts'][producer],entry['representation']))!=encode(entry['content']):
                raise ContextPackError('contextBindingMismatch')
        artifacts[producer]={'id':binding['id'],'sha256':binding['sha256']}
    if set(required)-artifacts.keys(): raise ContextPackError('requiredContextMissing')
    descriptors={}
    for entry in selected:
        descriptors[entry['sourceAlias']]={'sourceIdentity':entry['sourceIdentity'],'revision':entry['sourceRevision'],'outcome':entry['sourceOutcome']}
    header=dict(version=1,step=step,request={'citationId':task[0]['citationId']},artifacts=artifacts,
        sources=descriptors,validationFeedback=_feedback(arguments),humanChoices=_choices(arguments))
    return {'workflow':header,'contextPack':envelope}


class StepPackProjection(_Record):
    @classmethod
    def from_dict(cls,value):
        closed(value,{'version','profile','step','originalArguments','originalArgumentsDigest',
            'authoritativeInputData','authoritativeInputProfile','controllerValidationContext',
            'variants','packIndexMapping','candidateIdentity','requiredDependencies','spec'})
        data=decode(encode(value,maximum=8388608))
        if type(data['version']) is not int or data['version']!=1 or data['profile']!=MODEL_PROFILE or data['authoritativeInputProfile']!=AUTHORITATIVE_PROFILE:
            raise ContextPackError()
        reference(data['step'])
        _hash(data['candidateIdentity'])
        spec=ContextPackSpec.from_dict(data['spec'])
        from ..workflow import digest as workflow_digest
        from ..workflow_rules import facts
        if workflow_digest(data['originalArguments'])!=data['originalArgumentsDigest'] or encode(facts(data['step'],data['originalArguments']))!=encode(data['authoritativeInputData']):
            raise ContextPackError('contextBindingMismatch')
        context=FrozenCheckContext.from_dict(data['controllerValidationContext'])
        _validate_context(data['step'],data['originalArguments'],context.to_dict())
        if type(data['variants']) is not list or not 1<=len(data['variants'])<=8 or type(data['packIndexMapping']) is not list or len(data['variants'])!=len(data['packIndexMapping']):
            raise ContextPackError()
        if type(data['requiredDependencies']) is not list or len(set(data['requiredDependencies']))!=len(data['requiredDependencies']): raise ContextPackError()
        for dep in data['requiredDependencies']: reference(dep)
        for index,(root,mapping) in enumerate(zip(data['variants'],data['packIndexMapping'])):
            closed(root,{'workflow','contextPack'})
            closed(mapping,{'inputIndex','packIndex','envelopeDigest','inputDataDigest'})
            integer(mapping['inputIndex'],0,7);integer(mapping['packIndex'],0,7)
            if mapping!=dict(inputIndex=index,packIndex=index,envelopeDigest=digest(root['contextPack']),inputDataDigest=digest(root)):
                raise ContextPackError('contextBindingMismatch')
            expected=_model_root(data['step'],data['originalArguments'],root['contextPack'],spec,data['requiredDependencies'])
            if encode(expected)!=encode(root): raise ContextPackError('contextBindingMismatch')
        result=object.__new__(cls);result._own(data,maximum=8388608)
        return result


def _validate_context(step,arguments,context):
    if context['step']!=step or encode(context['request'])!=encode(arguments['request']):
        raise ContextPackError('contextBindingMismatch')
    for key,field in (('artifacts','artifacts'),('artifact_bindings','bindings')):
        for name,value in arguments[key].items():
            if name not in context[field] or encode(value)!=encode(context[field][name]):
                raise ContextPackError('contextBindingMismatch')
    for key,field in (('sources','evidence'),('human_responses','humanResponses')):
        values=arguments.get(key,{})
        if type(values) is not dict: raise ContextPackError()
        for name,value in values.items():
            if name not in context[field] or encode(value)!=encode(context[field][name]):
                raise ContextPackError('contextBindingMismatch')


def project_step(step,original_arguments,candidates,*,controller_validation_context=None,required_dependencies=None):
    reference(step)
    if type(candidates) is not ContextPackCandidates: raise ContextPackError()
    arguments=decode(encode(original_arguments))
    if (type(arguments) is not dict or 'request' not in arguments or
            any(type(arguments.get(k)) is not dict for k in ('artifacts','artifact_bindings'))):
        raise ContextPackError()
    context=FrozenCheckContext.from_context(controller_validation_context).to_dict()
    _validate_context(step,arguments,context)
    required=list(arguments['artifact_bindings']) if required_dependencies is None else required_dependencies
    if type(required) not in (tuple,list) or len(required)>128: raise ContextPackError()
    required=[reference(v) for v in required]
    if len(set(required))!=len(required): raise ContextPackError()
    roots=[_model_root(step,arguments,envelope,candidates.spec,required) for envelope in candidates.variants]
    mapping=[dict(inputIndex=index,packIndex=index,envelopeDigest=digest(root['contextPack']),inputDataDigest=digest(root)) for index,root in enumerate(roots)]
    from ..workflow import digest as workflow_digest
    from ..workflow_rules import facts
    return StepPackProjection.from_dict(dict(version=1,profile=MODEL_PROFILE,step=step,
        originalArguments=arguments,originalArgumentsDigest=workflow_digest(arguments),
        authoritativeInputData=facts(step,arguments),authoritativeInputProfile=AUTHORITATIVE_PROFILE,
        controllerValidationContext=context,variants=roots,packIndexMapping=mapping,
        candidateIdentity=candidates.candidate_identity,requiredDependencies=required,spec=candidates.spec.to_dict()))
