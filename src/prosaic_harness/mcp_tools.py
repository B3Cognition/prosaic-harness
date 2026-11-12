"""Pure admission for selected Runtime MCP registrations."""

from prosaic_runtime import ProsaicRuntime

try:
    from prosaic_runtime.mcp import is_mcp_tool
except ModuleNotFoundError as exc:
    if exc.name != "prosaic_runtime.mcp":
        raise

    def is_mcp_tool(_tool):
        return False


def selected_mcp(tools, names):
    return {name for name in names if is_mcp_tool(tools.get(name))}


def require_capability(runtime):
    if "mcp_client_v1" not in getattr(runtime, "capabilities", ()):
        raise ValueError("MCP Runtime capability missing")


def validate_workflow_mcp(workflow, selected, runtime=ProsaicRuntime):
    names = selected_mcp(workflow.custom_tools, selected)
    if names:
        require_capability(runtime)
        if workflow._tool_contracts is None:
            raise ValueError("MCP requires tool contracts")
    return names


def workflow_operation(workflow):
    record = getattr(workflow, "_admission", None)
    if record is not None:
        return record.operation_namespace, record.tool_journal
    return getattr(workflow, "_mcp_operation", (None, None))


def yaml_operation_material(workflow):
    from .factory import _operation_bindings
    namespace, journal = getattr(workflow, "_mcp_operation", (None, None))
    return {"mcpOperationV1": _operation_bindings(namespace, journal)} if journal is not None else {}


def validate_conversation_mcp(runtime, agent, tools, namespace, journal):
    from prosaic_runtime.policy import requested_tools
    if selected_mcp(tools, requested_tools(agent.frontmatter.get("tools"))):
        require_capability(runtime)
        if namespace is None or journal is None:
            raise ValueError("MCP requires an owned scope and tool journal")


def conversation_contract_descriptors(agent, tools, descriptors):
    from prosaic_runtime.policy import requested_tools
    requested = requested_tools(agent.frontmatter.get("tools"))
    return {name: descriptor for name, descriptor in descriptors.items()
            if name in requested or not is_mcp_tool(tools.get(name))}
