import pytest
import prosaic_harness as h
import prosaic_runtime as rt
from prosaic_runtime.mcp import McpClientV1, McpServerV1

from test_mcp_bindings import make_factory, registry
from test_parallel_tool_workflow import proposal
from test_runtime_boundaries import MemoryJournal
from test_workflow_rules_execution import rule_endpoint


def test_file_receipt_adopts_with_an_offline_catalog(rule_endpoint, tmp_path, monkeypatch):
    store = h.FileRunStore(tmp_path / "store", namespace="test")
    store.initialize(tool_contracts=True)
    check_offline_adoption(rule_endpoint, monkeypatch, store, store)


def check_offline_adoption(rule_endpoint, monkeypatch, store, fresh):
    pytest.importorskip("mcp")
    from prosaic_runtime import mcp_transport

    cfg, requests, replies = rule_endpoint
    journal, effects = MemoryJournal(), []
    def make(version="1"):
        host = McpClientV1(McpServerV1("graph", "1", "https://graph.invalid/mcp", "2026-07-28"),
                           allow_destination=lambda _: False, credentials=lambda *_: None,
                           scope_key=lambda _: "test-scope", authorize=lambda *_: True)
        return make_factory(cfg, tools=registry(host, version=version), ledger=journal).build(proposal(None))

    def dispatch(*_):
        effects.append(1)
        return rt.ToolResultV1(data={"count": 14})

    workflow = make()
    run_id = "a" * 32
    controller = h.Harness(workflow, store=store, run_id=run_id)
    replies.extend([{"name": "lookup", "input": {}}, '{"ok": true}'])
    monkeypatch.setattr(mcp_transport, "dispatch", dispatch)
    def crash(*_):
        raise OSError("receipt saved before process loss")
    monkeypatch.setattr(controller, "_accept", crash)
    with pytest.raises(OSError):
        controller.run({})
    assert len(requests) == 2 and effects == [1]
    with pytest.raises(ValueError):
        h.Harness(make("2"), store=fresh, run_id=run_id).resume()
    state = h.Harness(make(), store=fresh, run_id=run_id).resume()
    assert state["status"] == "completed"
    assert state["version"] == 4
    assert len(requests) == 2 and effects == [1]


def test_workflow_nodes_expose_only_their_selected_alias(rule_endpoint, tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from dataclasses import replace
    from prosaic_runtime import mcp_transport
    from test_mcp_bindings import contract

    config, requests, replies = rule_endpoint
    host = McpClientV1(McpServerV1("graph", "1", "https://graph.invalid/mcp", "2026-07-28"),
                       allow_destination=lambda _: False, credentials=lambda *_: None,
                       scope_key=lambda _: "test-scope", authorize=lambda *_: True)
    tools = registry(host, alias="other", existing=registry(host))

    def agent(alias):
        return rt.ProsaicArtifact(alias, "subagent", {
            "name": alias, "description": "Read graph", "tools": [alias]}, "Return JSON.")

    schema = {"type": "object"}
    factory = h.WorkflowFactory(
        catalog=h.WorkflowCatalog(agents={name: agent(name) for name in tools}, schemas={"result": schema}),
        bindings=h.WorkflowBindings(config=replace(config, allowed_tools=frozenset(tools)),
                                    custom_tools=tools, tool_contracts=contract(),
                                    operation_namespace="tenant", tool_journal=MemoryJournal()),
        policy=h.WorkflowPolicy(allowed_agents=set(tools), allowed_schemas={"result"},
                                allowed_tools=set(tools), max_provider_requests_per_invocation=2,
                                max_tool_calls_per_invocation=1, allow_agent_composition=True))
    definition = {"version": 1, "start": "one", "steps": {
        "one": {"kind": "agent", "agent": "lookup", "schema": "result", "tools": ["lookup"], "next": "two"},
        "two": {"kind": "agent", "agent": "other", "schema": "result", "tools": ["other"], "next": "done"},
        "done": {"kind": "finish"}}}
    import json
    workflow = factory.build_json(json.dumps({"definition": definition}))
    monkeypatch.setattr(mcp_transport, "dispatch", lambda *_: rt.ToolResultV1(data={"count": 14}))
    replies.extend([{"name": "lookup", "input": {}}, "{}", {"name": "other", "input": {}}, "{}"])
    store = h.FileRunStore(tmp_path / "store", namespace="test")
    store.initialize(tool_contracts=True)
    assert h.Harness(workflow, store=store, run_id="b" * 32).run({})["status"] == "completed"
    tool_names = [[entry.get("function", entry)["name"] for entry in request["tools"]]
                  for request in requests]
    assert tool_names == [["lookup"], ["lookup"], ["other"], ["other"]]
