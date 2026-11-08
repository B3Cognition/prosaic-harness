from prosaic_harness.context_packs import (
    ContextScope, ContextSource, ContextItem, ContextSnapshot, ContextSlot, ContextPackSpec)


def scope_case():
    return ContextScope('test', 'sandbox', 'app', 'tenant', 'actor')


def snapshot_case():
    return ContextSnapshot.from_items(
        [ContextItem('root', 'task', 'v1', {'task': 'Review the document'})],
        sources=[ContextSource('task', 'admitted-task', 'v1', 'complete')], scope_binding=scope_case())


def spec_case():
    return ContextPackSpec('review', 'v1', [ContextSlot('task', required=True)], task_source='task')


def two_source_case():
    sources=[ContextSource(s, s+'-identity', 'v1', 'complete') for s in ('a','b')]
    snapshot=ContextSnapshot.from_items([ContextItem('root',s,'v1','same') for s in ('a','b')], sources=sources,scope_binding=scope_case())
    return ContextPackSpec('review','v1',[ContextSlot(s,required=True) for s in ('a','b')]),snapshot


def required_optional_case():
    sources=[ContextSource(s,s+'-identity','v1','complete') for s in ('task','facts')]
    snapshot=ContextSnapshot.from_items([ContextItem('root',s,'v1',s+' content') for s in ('task','facts')],sources=sources,scope_binding=scope_case())
    return ContextPackSpec('review','v1',[ContextSlot('task',required=True),ContextSlot('facts')],task_source='task'),snapshot
