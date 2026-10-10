# Workflows assembled in memory

`WorkflowFactory` validates and seals graphs assembled by trusted application code
or proposed by a client. A proposal references host-approved agents and schemas
by logical aliases. The host supplies Runtime configuration, native tools,
validators and a mandatory policy separately.

The factory returns the existing runnable workflow interface. It creates no
workspace, discovers no CLI manifests, and invokes no models, callbacks or
validators during construction. Native execution needs Python and the installed
packages; neither Node nor the Prosaic executable is required.

## Host construction

This synthetic example uses one approved specialist, a registered native lookup,
and an explicit confirmation pause. `endpoint_url` comes from host configuration;
the offline smoke script supplies its own loopback fixture.

```python
from prosaic_runtime import CustomTool, EndpointConfig, ProsaicArtifact, RuntimeConfig
from prosaic_harness import (
    WorkflowBindings, WorkflowCatalog, WorkflowFactory, WorkflowPolicy, Validator,
)

agent = ProsaicArtifact("subagents/finder.md", "subagent", {
    "name": "finder", "description": "Find a synthetic entity",
    "model_tier": "fast", "tools": ["lookup_item"],
}, "ALWAYS use lookup_item to obtain the requested entity.\n"
   "NEVER invent an entity or claim a tool was used without using it.\n"
   "ALWAYS return one JSON object with entity_id and label.\n"
   "NEVER include prose outside the JSON object.")

entity_schema = {
    "type": "object", "properties": {
        "entity_id": {"type": "string", "maxLength": 64},
        "label": {"type": "string", "maxLength": 128},
    }, "required": ["entity_id", "label"], "additionalProperties": False,
}
confirmation_schema = {
    "type": "object", "properties": {
        "entity_id": {"type": "string", "maxLength": 64},
    }, "required": ["entity_id"], "additionalProperties": False,
}

def lookup(arguments):
    return {"entity_id": "sample-1", "label": "Synthetic item"}

def selection(value, context):
    return ([] if value["response"]["entity_id"] == context.artifacts["find"]["entity_id"]
            else ["Confirm the entity displayed by this run"])

tool = CustomTool("lookup_item", "Find a synthetic entity", {
    "type": "object", "properties": {"query": {"type": "string", "maxLength": 128}},
    "required": ["query"], "additionalProperties": False,
}, lookup, "v1")
config = RuntimeConfig({
    "local": EndpointConfig(endpoint_url, "synthetic-model", features={"streaming": False}),
}, {"fast": "local"}, "local", allowed_tools=frozenset({"lookup_item"}))

factory = WorkflowFactory(
    catalog=WorkflowCatalog(agents={"finder": agent}, schemas={
        "entity": entity_schema, "confirmation": confirmation_schema,
    }),
    bindings=WorkflowBindings(config=config, custom_tools={"lookup_item": tool},
                              validators={"selection": Validator("v1", selection)}),
    policy=WorkflowPolicy(
        allowed_agents=frozenset({"finder"}),
        allowed_schemas=frozenset({"entity", "confirmation"}),
        allowed_tools=frozenset({"lookup_item"}),
        allowed_validators=frozenset({"selection"}),
        allowed_model_tiers=frozenset({"fast"}),
        max_calls=2, max_tokens=128, max_run_s=60,
    ),
)
```

Registration provides an implementation. The effective tool grant also requires
the agent prose, step, host configuration and policy to allow it. Consequential
handlers must enforce the caller's domain authorization themselves. Change tool
and validator versions when their behavior or captured fixed data changes.
Creating catalogue, bindings and factory objects, and building a graph, never
calls registered tool handlers, authorizers or validators. These callbacks run
only during execution when required by the workflow.

## Proposal and execution

```python
definition = {"version": 1, "name": "synthetic-selection", "start": "find", "steps": {
    "find": {"kind": "agent", "agent": "finder", "schema": "entity",
             "tools": ["lookup_item"], "require_tools": ["lookup_item"], "next": "review"},
    "review": {"kind": "pause", "question": "Confirm the displayed entity?",
               "choices": {"accept": "done", "reject": "rejected"}, "requires": ["find"],
               "response_schema": "confirmation", "validators": ["selection"]},
    "done": {"kind": "finish", "requires": ["find"]},
    "rejected": {"kind": "finish", "outcome": "rejected"},
}}
workflow = factory.build(definition)
# For raw client JSON: factory.build_json(text), where text is
# {"definition": definition, "inline_agents": {...}} with inline_agents optional.

from pathlib import Path
import uuid
from prosaic_harness import FileRunStore, Harness

store = FileRunStore(Path("private-runs").resolve(), namespace="application")
run_id = uuid.uuid4().hex
harness = Harness(workflow, store=store, run_id=run_id)
state = harness.run({"query": "sample"})
snapshot = harness.status()
assert snapshot.state["status"] == "waiting"
state = harness.resume(choice="accept", response={"entity_id": "sample-1"},
                       expected_revision=snapshot.revision)
assert state["status"] == "completed"
store.close()
```

Use the revision returned by `status()` for human actions with `store`/`run_id`.
An undeclared choice, invalid response or stale revision cannot authorize graph
advancement. `status()` verifies saved state and receipts without modifying them.

For another worker or process, rebuild the workflow from the same versioned
proposal, approved assets, host bindings and policy, then construct a new Harness
with the same store and run ID. Changes to used content, configuration, policy,
evaluation profile or required callback versions reject resume. A saved receipt
is adopted without another invocation. A request interrupted before its receipt
was committed remains ambiguous and requires an explicit interrupted retry.

## Admission and trust limits

Catalogue aliases are simple identifiers of at most 64 characters. Their names
can differ from canonical artifact IDs. Catalogue, binding and policy inputs are
snapshotted; later caller mutation cannot change an admitted workflow. Returned
workflow mutation is rejected at execution boundaries.

Graphs support `agent`, `gate`, `check`, `pause` and `finish`, with bounded visits
and attempts. Composing more than one agent step requires
`allow_agent_composition=True`. Caller-authored inline agents independently
require `allow_inline_agents=True`; both permissions default to false. Schemas
must come from the host catalogue; client inline schemas are unavailable.

An agent that omits `model_tier` selects the host's `default_profile`, including
when `allowed_model_tiers` is empty or contains only named tiers. An explicit
tier must appear in both the Runtime configuration's `routes` and the policy's
`allowed_model_tiers`. Tier names are Runtime route names, such as `tenant/fast`,
and may contain Unicode; they must be nonempty, at most 64 characters, and contain
no Unicode control, format or surrogate characters.

The native factory accepts no client paths, workspaces, Runtime endpoints,
credentials, filesystem grants, acquisitions or CLI registrations. Each
run/resume operation uses a private temporary execution directory and removes it
on exit. Existing trusted YAML workflows retain their filesystem, CLI and
checkpoint compatibility contracts.

New schema admission supports Draft 2020-12 object/boolean schemas and acyclic
static references to schema resources inside the same document. It rejects
retrieval, dynamic references, reference/evaluation cycles, duplicate resource
IDs/anchors and unsupported nested dialects. Approved regex/combinator schemas
and native tool parameter schemas are a host-vetted trust choice. Trusted
callbacks, validators and in-process schema CPU cannot be forcibly stopped by a
whole-run deadline.

Finite depth, expanded work, bytes, calls and visits are enforced. Tokens are a
reported-usage budget evaluated after invocation: one invocation can overshoot,
and missing usage preserves fail-closed behavior. Whole-run time includes human
waiting. Oversized returned data becomes a bounded failure receipt; it is never
truncated into an accepted artifact. Schema-evaluation failures block without a
model correction retry. Normal invalid model JSON retains bounded correction
attempts.

Admission raises `WorkflowAdmissionError`, with safe `code` and `location`
attributes. Services should project logical summaries and safe errors rather
than serialize workflow bindings, private configuration or raw checkpoints.
Consumer authentication and request-specific policy selection remain host duties.

## Offline installed-wheel check

After installing candidate Core, Runtime and Harness wheels into a clean
environment, run:

```sh
/path/to/wheel-env/bin/python -I /absolute/path/to/scripts/workflow_factory_smoke.py
```

[The smoke script](../scripts/workflow_factory_smoke.py) checks installed module
origins and public prerequisite APIs, clears Node/Prosaic executables from PATH,
and uses a disposable loopback endpoint with synthetic responses. It exercises
the native tool, confirmation schema/validator, read-only status, fresh-factory
reconstruction and resume, unchanged receipt identity and one completed Harness
invocation. No live model service is contacted.
