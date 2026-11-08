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
