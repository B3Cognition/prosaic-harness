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

## Client or LLM-generated proposals

The authenticated application chooses the factory and its host policy before
admitting a proposal. A client or LLM supplies only JSON graph data and logical
aliases from the permitted catalogue. It cannot supply policy, registrations,
Runtime configuration or credentials. Application-generated definitions use the
same admission boundary.

`build_json` accepts a strict JSON envelope with `definition` and optional
`inline_agents`. Send the JSON itself, without Markdown fences. For example,
this proposal uses the host's `finder`, `entity` schema and native lookup:

```python
proposal_text = '''{
  "definition": {
    "version": 1,
    "start": "find",
    "steps": {
      "find": {"kind": "agent", "agent": "finder", "schema": "entity",
               "tools": ["lookup_item"], "require_tools": ["lookup_item"],
               "next": "done"},
      "done": {"kind": "finish", "requires": ["find"]}
    }
  }
}'''

from prosaic_harness import WorkflowAdmissionError

try:
    proposed_workflow = factory.build_json(proposal_text)
except WorkflowAdmissionError as error:
    admission_response = {
        "accepted": False,
        "error": {"code": error.code, "location": error.location},
    }
else:
    admission_response = {"accepted": True}
```

The response contains only safe admission fields. Create the Harness and run
storage after successful admission, then use `run`/`resume` as above. Run inputs
are separate from the graph proposal. Keep raw workflow objects, configuration
and operator checkpoints inside the application. Codes such as `policy_denied`,
`unknown_reference`, `invalid_definition` and `limit_exceeded` let the service
explain rejected proposals without exposing parser exceptions or host data.

## Composing approved agents

Approve each specialist and its output schema in the host catalogue, then enable
`allow_agent_composition=True`. This example extends the same trusted finder
with a reviewer. Inline instruction permission remains disabled.

```python
reviewer = ProsaicArtifact("subagents/reviewer.md", "subagent", {
    "name": "reviewer", "description": "Review the supplied synthetic entity",
}, "ALWAYS review artifacts.find from the invocation arguments.\n"
   "ALWAYS preserve its entity_id and return entity_id plus approved as JSON.\n"
   "NEVER invent an entity or emit prose outside the JSON object.")
review_schema = {
    "type": "object", "properties": {
        "entity_id": {"type": "string", "maxLength": 64},
        "approved": {"type": "boolean"},
    }, "required": ["entity_id", "approved"], "additionalProperties": False,
}
composition_factory = WorkflowFactory(
    catalog=WorkflowCatalog(agents={"finder": agent, "reviewer": reviewer},
                           schemas={"entity": entity_schema, "review": review_schema}),
    bindings=WorkflowBindings(config=config, custom_tools={"lookup_item": tool}),
    policy=WorkflowPolicy(
        allowed_agents=frozenset({"finder", "reviewer"}),
        allowed_schemas=frozenset({"entity", "review"}),
        allowed_tools=frozenset({"lookup_item"}),
        allowed_model_tiers=frozenset({"fast"}),
        allow_agent_composition=True, max_calls=2, max_tokens=128, max_run_s=60,
    ),
)
composition_definition = {"version": 1, "start": "find", "steps": {
    "find": {"kind": "agent", "agent": "finder", "schema": "entity",
             "tools": ["lookup_item"], "require_tools": ["lookup_item"], "next": "review"},
    "review": {"kind": "agent", "agent": "reviewer", "schema": "review",
               "inputs": ["find"], "next": "approved"},
    "approved": {"kind": "gate", "from": "review", "field": ["approved"],
                 "equals": True, "pass": "done", "fail": "rejected"},
    "done": {"kind": "finish", "requires": ["find", "review"]},
    "rejected": {"kind": "finish", "outcome": "rejected"},
}}
composed_workflow = composition_factory.build(composition_definition)
```

`inputs` names graph **step IDs**, such as `find`, rather than catalogue aliases
or canonical Markdown IDs. The second agent receives the first accepted output
in `artifacts.find` and its provenance in `artifact_bindings.find`, alongside
the original `request`. Required inputs must be present and fresh; a later
revisit that changes `find` makes the old dependent review stale. Use
`optional_inputs` for feedback that may be absent on a first pass. Optional
inputs may contain stale feedback and cannot establish a fresh approval.
Agent instructions are separate; the factory does not concatenate their prose.

## Optional inline instructions

Enable `allow_inline_agents=True` only for a host policy that permits new
instructions. This permission is independent of composition: one inline agent
needs inline permission, while a graph with multiple agent steps also needs
composition permission. Tools, model tiers, schemas and resource bounds still
follow the host policy.

Each `inline_agents` entry has `type`, `frontmatter` and `body`, with optional
embedded `resources`. Supported execution types are `command` and `subagent`;
a subagent's canonical frontmatter requires `name` and `description`.
This single-agent example reuses the host-approved `entity` schema:

```python
inline_factory = WorkflowFactory(
    catalog=WorkflowCatalog(schemas={"entity": entity_schema}),
    bindings=WorkflowBindings(config=config),
    policy=WorkflowPolicy(allowed_schemas=frozenset({"entity"}), allow_inline_agents=True),
)
inline_agents = {
    "custom_reply": {
        "type": "command",
        "frontmatter": {},
        "body": "ALWAYS return entity_id and label from request as one JSON object.\n"
                "NEVER invent fields or emit prose outside that object.",
        "resources": [{
            "relPath": "output-notes.md",
            "content": "ALWAYS preserve the supplied identifiers.\nNEVER invent identifiers.",
        }],
    },
}
inline_definition = {"version": 1, "start": "reply", "steps": {
    "reply": {"kind": "agent", "agent": "custom_reply", "schema": "entity", "next": "done"},
    "done": {"kind": "finish", "requires": ["reply"]},
}}
inline_workflow = inline_factory.build(inline_definition, inline_agents=inline_agents)

# The same data may arrive as a raw client/LLM JSON envelope.
import json
inline_workflow_from_json = inline_factory.build_json(json.dumps({
    "definition": inline_definition, "inline_agents": inline_agents,
}))
```

For this inline example, supply `{"entity_id": "sample-1", "label": "Synthetic item"}`
as the run input, using a new run ID and the same Harness execution pattern.
The factory assigns the artifact's logical ID from the inline alias
(`custom_reply` here); clients do not provide an `id` field. Inline aliases
must not collide with host catalogue aliases, and every supplied inline entry
must be referenced. `allowed_agents` selects approved catalogue agents;
inline content is authorized separately by `allow_inline_agents`.
Schemas remain host catalogue entries. Embedded resource names and string
content are prompt data, never host file lookups or filesystem grants.

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

The host chooses limits through `WorkflowPolicy` fields such as `max_steps`,
`max_proposal_bytes`, `max_json_depth`, `max_calls`, `max_tokens` and `max_run_s`.
See the versioned [default bounds and admission profile](superpowers/specs/2026-10-09-workflow-mvp-design.md#bounded-snapshots-and-admission-profile)
for the complete defaults. Missing graph limits inherit the policy; lower
requested limits are retained, and requests above the host caps fail admission.
Clients cannot change the host's policy by adding fields to the JSON envelope.

Admission raises `WorkflowAdmissionError`, with safe `code` and `location`
attributes. Services should project logical summaries and safe errors rather
than serialize workflow bindings, private configuration or raw checkpoints.
Consumer authentication and request-specific policy selection remain host duties.

## Offline installed-wheel check

Use a tagged checkout for the smoke script and a clean environment for the
released Harness wheel. Its immutable dependencies install Core and Runtime:

```sh
git clone https://github.com/B3Cognition/prosaic-harness.git
cd prosaic-harness
git checkout v0.6.2
python3 -m venv .wheel-check
.wheel-check/bin/python -m pip install \
  https://github.com/B3Cognition/prosaic-harness/releases/download/v0.6.2/prosaic_harness-0.6.2-py3-none-any.whl
.wheel-check/bin/python -I scripts/workflow_factory_smoke.py
```

[The smoke script](../scripts/workflow_factory_smoke.py) checks installed module
origins and public prerequisite APIs, clears Node/Prosaic executables from PATH,
and uses a disposable loopback endpoint with synthetic responses. It exercises
the native tool, confirmation schema/validator, read-only status, fresh-factory
reconstruction and resume, unchanged receipt identity and one completed Harness
invocation. No live model service is contacted.
