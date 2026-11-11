from dataclasses import replace

import pytest

import prosaic_harness as h
import prosaic_runtime as rt
from prosaic_runtime.mcp import McpClientV1, McpServerV1, McpToolSpecV1
from prosaic_runtime.mcp_catalog import digest
from test_parallel_tool_workflow import proposal
from test_runtime_boundaries import MemoryJournal
from test_workflow_rules_execution import rule_endpoint


def registry(host=None, *, version="1", alias="lookup", existing=None):
    if host is None:
        def pure(*_):
            pytest.fail("pure admission invoked an MCP callback")
        host = McpClientV1(McpServerV1("graph", "1", "https://graph.invalid/mcp",
                                      "2026-07-28"), allow_destination=pure,
                           credentials=pure, scope_key=pure, authorize=pure)
    schema = {"type": "object", "additionalProperties": False}
    document = {"version": 1, "binding": host._catalog_binding("test-scope"),
                "server": host._server_binding(),
                "tools": [{"name": "dependents", "inputSchema": schema, "outputSchema": None}]}
    catalog = host.restore_catalog(document, access_scope="test-scope", expected_sha256=digest(document))
    spec = McpToolSpecV1(alias=alias, remote_name="dependents", description="Read graph",
                         binding_version=version, result_mode="structured", read_only=True,
                         projector=lambda value, _: rt.ToolResultV1(data=value),
                         result_contract=rt.ToolResultContractV1("1"))
    return host.bind_tools(catalog, [spec], existing=existing)


def make_factory(cfg, *, journal=True, tools=None, contracts=True, ledger=None):
    tools = registry() if tools is None else tools
    config = replace(cfg, allowed_tools=frozenset(tools))
    agent = rt.ProsaicArtifact("approved", "subagent", {
        "name": "analyst", "description": "Read graph", "tools": ["lookup"]}, "Return JSON.")
    return h.WorkflowFactory(
        catalog=h.WorkflowCatalog(agents={"analyst": agent}, schemas={"result": {"type": "object"}}),
        bindings=h.WorkflowBindings(config=config, custom_tools=tools,
                                    tool_contracts=contract() if contracts else None,
                                    operation_namespace="tenant" if journal else None,
                                    tool_journal=(ledger if ledger is not None else MemoryJournal()) if journal else None),
        policy=h.WorkflowPolicy(allowed_agents={"analyst"}, allowed_schemas={"result"},
                                allowed_tools=set(tools), max_provider_requests_per_invocation=2,
                                max_tool_calls_per_invocation=2))


def contract():
    return h.ToolContracts("graph", "1", evidence_authorizer=rt.EvidenceAuthorizerV1("source", "1", lambda _: True))


def test_factory_freeze_preserves_mcp_and_neighbor_descriptors(rule_endpoint):
    cfg, _, _ = rule_endpoint
    tools = registry()
    tools["nearby"] = rt.CustomTool("nearby", "Read locally", tools["lookup"].parameters,
                                    lambda a, c: a, "1", with_context=True, parallel_read=True)
    factory = make_factory(cfg, tools=tools)
    original = factory.build(proposal(None))
    frozen = factory._frozen_copy().build(proposal(None))
    assert frozen.fingerprint == original.fingerprint
    assert rt.custom_descriptors(frozen.custom_tools) == rt.custom_descriptors(tools)


@pytest.mark.parametrize("problem", ["journal", "contracts", "initial"])
def test_factory_refuses_unsupported_mcp_without_callbacks(rule_endpoint, problem):
    cfg, _, _ = rule_endpoint
    definition = proposal(None)
    if problem == "initial":
        definition["steps"]["review"]["initial_tool"] = "lookup"
    with pytest.raises(ValueError):
        make_factory(cfg, journal=problem != "journal",
                     contracts=problem != "contracts").build(definition)


def test_yaml_operation_binding_is_explicit_and_sealed(rule_endpoint, tmp_path):
    import json
    import sys
    from pathlib import Path
    import yaml

    config, _, _ = rule_endpoint
    original = make_factory(config).build(proposal(None))
    endpoint = config.profiles["local"]
    source = tmp_path / ".prosaic" / "subagents"
    source.mkdir(parents=True)
    agent = original.artifacts["review"]
    (source / "analyst.md").write_text(
        "---\n" + yaml.safe_dump(agent.frontmatter) + "---\n" + agent.body + "\n")
    (tmp_path / "result.json").write_text(json.dumps(original.schemas["review"]))
    (tmp_path / "runtime.yml").write_text(yaml.safe_dump({
        "default_profile": "local", "allowed_tools": ["lookup"], "profiles": {
            "local": {"base_url": endpoint.base_url, "model": endpoint.model,
                      "provider": endpoint.provider, "features": {"streaming": False}}}}))
    graph = json.loads(json.dumps(original.definition))
    graph.update(source=".prosaic", runtime="runtime.yml")
    graph["limits"].pop("max_tokens")
    graph["steps"]["review"].update(agent="subagents/analyst.md", schema="result.json")
    path = tmp_path / "workflow.yml"
    path.write_text(yaml.safe_dump(graph))
    options = dict(executable=str(Path(sys.executable).with_name("prosaic")),
                   custom_tools=original.custom_tools, tool_contracts=contract())
    with pytest.raises(ValueError):
        h.Workflow.load(path, **options)
    journal = MemoryJournal()
    first = h.Workflow.load(path, operation_namespace="tenant", tool_journal=journal, **options)
    changed = h.Workflow.load(path, operation_namespace="other", tool_journal=journal, **options)
    assert first.current_fingerprint() == first.fingerprint != changed.fingerprint
