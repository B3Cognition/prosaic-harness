from dataclasses import replace
import prosaic_runtime as rt
from support.conversations import binding_factory
from test_tool_contract_bindings import contract


def test_conversation_policy_owns_parallel_binding(binding_factory):
    first=binding_factory(tool_contracts=contract());policy=replace(first.run_policy,parallel_tools=rt.ParallelToolPolicyV1(max_concurrency=2))
    b=binding_factory(tool_contracts=contract(),run_policy=policy)
    assert b.run_policy.parallel_tools==policy.parallel_tools and b.identity!=first.identity
    assert b.readmit()['parallelToolsV1']['policy']==policy.parallel_tools.to_dict()
