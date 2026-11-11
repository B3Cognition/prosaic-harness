"""Host ceilings and explicit per-agent parallel read admission."""
from dataclasses import replace
from prosaic_runtime import ParallelToolPolicyV1
from prosaic_runtime.tool_parallel_contracts import parallel_binding


def parallel_policy(workflow,step_name):
    step=workflow.definition['steps'][step_name]
    request=step.get('parallel_tools')
    if request is None:return None
    host=getattr(workflow,'_parallel_tool_policy',None)
    if (step.get('kind')!='agent' or type(host) is not ParallelToolPolicyV1 or type(request) is not dict or
            set(request)!={'max_concurrency'} or type(request['max_concurrency']) is not int or
            not 1<=request['max_concurrency']<=host.max_concurrency):raise ValueError('parallel tool request exceeds host authority')
    host.__post_init__()
    return replace(host,max_concurrency=request['max_concurrency'])


def parallel_material(workflow,runtime=None):
    policies={name:parallel_policy(workflow,name) for name,step in workflow.definition['steps'].items() if 'parallel_tools' in step}
    if not policies:return {}
    if getattr(workflow,'_tool_contracts',None) is None:raise ValueError('parallel tools require tool contracts')
    if runtime is None:
        from prosaic_runtime import ProsaicRuntime
        runtime=ProsaicRuntime(workflow.config,custom_tools=workflow.custom_tools,**workflow._rule_bindings.runtime_options())
    if 'parallel_tool_calls_v1' not in getattr(runtime,'capabilities',()):raise ValueError('parallel tool Runtime capability missing')
    if getattr(workflow,'_runtime_adapter',None) is not None:raise ValueError('parallel tools require role-aware Runtime')
    limits=workflow.definition['limits']
    if any(type(limits.get(k)) is not int or limits[k]<0 for k in ('max_provider_requests_per_invocation','max_tool_calls_per_invocation')):
        raise ValueError('parallel tools require finite attempt caps')
    return {'parallelToolsV1':dict(version=1,host=workflow._parallel_tool_policy.to_dict(),nodes={k:parallel_binding(p) for k,p in policies.items()})}


def conversation_parallel(runtime,policy,contracts):
    if policy.parallel_tools is None:return {}
    if contracts is None or 'parallel_tool_calls_v1' not in getattr(runtime,'capabilities',()):raise ValueError('parallel tool binding missing')
    return {'parallelToolsV1':parallel_binding(policy.parallel_tools)}
