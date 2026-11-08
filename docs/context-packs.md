# Context packs

Context packs define the evidence available to an agent invocation. Register
sources and named packs in trusted host code; choose a default for an agent or
override it on a workflow node. Markdown files work without a database. Accepted
producer outputs and host-captured application records use the same selection API.

This is an opt-in feature. Existing pack-free workflows and conversation v1/v2
records keep their existing payloads, fingerprints and recovery behavior.

## Per-node Markdown authoring

The runnable [example](../examples/context-packs/workflow.yml) uses one agent
three times: implementation evidence, review evidence, then a task-only brief.

```yaml
contextPacks:
  implementation:
    version: '1'
    taskSource: task
    slots:
      - {source: task, required: true}
      - {source: requirements, required: true}
      - {source: constraints, required: true}
  review:
    version: '1'
    taskSource: task
    slots:
      - {source: task, required: true}
      - {source: requirements, required: true}
      - {source: candidate, required: true}
  task-only:
    version: '1'
    taskSource: task
    slots: [{source: task, required: true}]
agentContextPacks:
  subagents/worker.md: implementation
```

Set `contextPack: review` on the reviewer node and `contextPack: task-only` on
the brief node. The reviewer declares `inputs: [build]`; its required accepted
artifact must be represented inline. The brief has no required artifact input.
Changing a pack never silently removes an existing dependency requirement.

The host binds aliases independently of those declarations:

```python
from pathlib import Path
from prosaic_harness import (
    Workflow, ContextPackBindings, ContextAuthorizer, ContextScope,
    InputSource, EvidenceSource, ArtifactSource,
)

scope = ContextScope("review", "production", "my-app", tenant_id, actor_id)
packs = ContextPackBindings(
    specs={},  # trusted workflow YAML supplies the named definitions
    sources={
        "task": InputSource("/task"),
        "requirements": EvidenceSource("requirements.md"),
        "constraints": EvidenceSource("constraints.md"),
        "candidate": ArtifactSource("build"),
    },
    scope=scope,
    authorizer=ContextAuthorizer("evidence-access", "1", authorize_current_use),
)
workflow = Workflow.load(Path("workflow.yml").resolve(), context_packs=packs)
```

Declare the Markdown paths under the workflow's existing `evidence` list.
`EvidenceSource` reads that admitted snapshot; it cannot discover another file.
`InputSource` is a JSON pointer within the original request. `ArtifactSource`
uses an accepted, freshly bound producer output. Neither selection nor restoration
runs a query, refreshes a source, or executes a catalogue manifest.

Native `WorkflowFactory` consumers register `ContextPackBindings` through
`WorkflowBindings(context_packs=...)`. Named specs are `ContextPackSpec` values;
slots are `ContextSlot` values. Model-proposed workflows can select only explicitly
public host catalogue aliases. They cannot define packs, sources or authorization.

## Moving from files to application records

Keep an alias such as `requirements` and replace its host binding with
`ArtifactSource("load-requirements")`. An explicit granted producer tool performs
the application read and returns a structured record. The consuming node's pack
declaration stays the same. Put completeness, pagination and conflicting observations
inside that record; generic infrastructure does not infer business completeness
from an arbitrary JSON field. Capture completion and domain completeness differ.

For graph-free use, the host can construct a `ContextSnapshot` from already
retrieved records, including explicit source outcomes `complete`, `partial`, or
`unavailable`, then compose it with `ContextPacker`. A completed empty lookup is
different from an unavailable source. Required slots refuse missing context;
partial sources need the slot's explicit `allow_partial=True` permission.

## Conversations

```python
from prosaic_harness import ContextPacker
from prosaic_harness.context_packs import capture_sources

# chat.bindings was created with context_packs=packs. The host authenticates
# this request and owns these values; HTTP/model clients do not submit packs.
spec = packs.specs["impact"]
snapshot = capture_sources(spec, {"request": captured_records}, {}, packs)
candidates = ContextPacker().compose(spec, snapshot)
reply = chat.send(
    session_id, message_id=message_id, message=user_message,
    expected_revision=revision, context_pack=candidates,
)
```

The message remains exact and separate from the selected envelope. Message
idempotency includes the complete candidate identity, even if only an optional
or private fact changed. Exact replay does not compose, count, dispatch or read
again. Packs are rejected during attached-workflow interpretation; they cannot
overwrite interaction identity or supply authenticated human consent.

Portable history retains actual user, assistant and tool exchanges. Old inline
pack bodies remain private receipt data and are not automatically inserted into
later messages. Deliberately attach evidence again when a later turn needs it.
Answers and reader results retain a conservative provenance union, including the
history supplied to their invocation.

## Selection, counting and reading

Composition is pure and bounded. It produces a monotone sequence ending with
mandatory context. Without a qualified counter, controllers select that mandatory
candidate and report byte-based selection. They do not claim token counts or
token savings. Harness accepts host-only `context_policy` and `token_counters`;
conversations bind these through `ConversationBindings`.

With a registered Runtime counter, history and evidence variants share one fitting
budget. The retained history suffix is fixed before richer variants are considered.
Restoration uses the selected saved bytes and original work ledger; it never
optimizes again or resets an unknown work reservation.

`availability: discoverable` makes an index entry available. Register the public
`ContextPackReader().as_tool()` as `read_context_item` and grant it in configuration,
agent prose and the node policy. Only that invocation's selected captured items
are readable. UTF-8 byte ranges and JSON pointers can narrow a grant. Text pages
declare continuation; oversized JSON is refused rather than silently truncated.
The default body/result bounds are 16 KiB/24 KiB, including actual wire framing.
Reads use captured bytes and recheck current authorization and cancellation.

## Model context and private validation

Pack selection changes model evidence independently of validation. Workflow
guards retain complete original step facts under `workflow-guard-input-v1`.
Controller validators receive a frozen full `CheckContext`, including broader
accepted artifacts and human responses. Conversation guards receive the complete
supplied snapshot under `context-pack-snapshot-v1`. Private data is not inserted
into provider input, tool arguments, progress events or retry feedback.

Choose each guard's access explicitly when enabling private inputs:

```python
from prosaic_runtime import Guard, Verdict
from prosaic_runtime.guards import value_in_tool_output

guards = [
    value_in_tool_output(input_access="model"),
    Guard("domain-facts", "1", ("final",), check_complete_private_facts,
          input_access="authoritativeAndModel"),
]
```

The private guard reads `context.authoritative_input_data`; `context.input_data`
remains the selected model view. Private guards are fail-only, with no fixes or
value echo. Shared registrations remain the legacy default and are rejected
with separated private input until explicitly audited and rebound. Existing
generic guards accept `input_access="model"`.

Opted-in workflows require `repeatable_validators` declarations. Adoption may
repeat controller validation after a crash, but never repeats Runtime guard,
provider or tool execution from a saved receipt. Every validator gets a fresh
owned copy of the frozen context. Public feedback uses closed safe-feedback-v1
codes and optional sealed host constants. Raw diagnostics remain private.

## Current authorization and durable storage

`ContextAuthorizer` receives bounded `ContextUse` metadata: scope, operation,
source identities/revisions, representations and purpose. It must return literal
`True`. Invocation, private validation, deferred reads, history reuse and retained
viewing are separate purposes. Private uses also identify their full input profile
and digest. The application authenticates callers and defines the policy; a hash
or matching scope is not permission.

Every later inference checks the retained history union, even without a new pack
and even if fitting might omit an old turn. Revocation refuses use before provider
spend. `retainedRead` can permit viewing while denying inference, or deny a public
reply while internal adoption settles a completed receipt. Cancel in-flight work
when faster revocation is needed; already disclosed bytes cannot be withdrawn.

Opt in explicitly on a fresh store:

```python
store.initialize(context_packs=True)
```

For existing stores, drain writers and use `store.migrate_context_pack_storage()`.
PostgreSQL requires the schema owner and checks leases across all namespaces.
Runtime roles do no DDL. CLI migration is:

```sh
prosaic-harness-postgres migrate-context-packs --store workflows --dsn-env MIGRATION_DSN
prosaic-harness-postgres migrate-context-packs --store conversations --dsn-env MIGRATION_DSN
```

Workflow checkpoint/receipt/proof versions become 3/2/2; sessions and every
receipt wrapper become v3, including pack-free and interpreter turns. Local
workflow migration preserves old record bytes in a protected sibling namespace
and puts an old-writer barrier at the former directory address. Use store APIs
and canonical absolute paths rather than constructing internal paths. Conversation
storage uses an explicit v3 marker. Readiness never performs a migration.

Do not downgrade markers or point old writers at an upgraded namespace. Rollback
disables new admission while compatible readers settle existing operations; use a
separate fresh legacy namespace if old binaries must run again. Retain unresolved
evidence. An acknowledged retry uses a new epoch and available allowance; it is
not proof that the previous endpoint or counting callback did nothing.

## Bounds and qualification

Default pack bounds include 16 source aliases, 128 captured items, 48 KiB inline,
8 KiB index, eight variants and a 3 MiB snapshot ceiling. Aggregate workflow
quotas remain 1 MiB per receipt and 4 MiB per checkpoint. Individually legal fields
can exceed those aggregate limits and are refused before the invocation's effects.
Private fact limits and finite provider/tool allowances apply independently.

Embedded projection v2 references only frozen bytes in the same invocation
record, with closed paths and checked digests. Original arguments, reserved-key
overrides and the full controller context restore exactly. Inline projection v1
remains readable. No blob service or source recapture is involved.

The installed synthetic witness exercises 16 items, a 68,055-byte snapshot,
27,646-byte model input, 65,536-byte private facts and two 24,572-byte reader
outcomes. Its receipt is 460,488 bytes under the unchanged quota. These checks
prove contracts and recovery; real-model quality, latency and cost need a separate
explicitly enabled evaluation. See the [local qualification report](verification/2026-11-09-context-packs-qualification.md).
