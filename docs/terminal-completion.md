# Host-owned completion of native tool loops

Runtime 0.9.11 and Harness 0.9.6 add explicit host-owned completion after a native
tool has produced the verified result. The host supplies the workflow output and
its separate inline artifact; Runtime does not request another model response.

Create a fresh environment and install the coherent SDK versions:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install 'b3-prosaic==0.4.1' \
  'b3-prosaic-runtime==0.9.11' 'b3-prosaic-harness==0.9.6'
.venv/bin/python -m pip check
```

Existing optional PostgreSQL packages remain Runtime recorder 0.3.0 and Harness
store 0.4.1. No adapter migration or Core release is required. These version pins
describe this release candidate until its public release qualification completes.

## Integration

Update the host callback that actually completes the task. Validate the real
backend result before constructing TerminalCompletion; never use model-rendered
rows or an HTTP success code as the artifact.

```python
from prosaic_runtime import CustomTool, TerminalCompletion

def lookup(arguments):
    # backend and validate_result are trusted application code.
    result = backend.lookup(arguments['query'])
    artifact = validate_result(result, executed_query=arguments['query'])
    return TerminalCompletion({'complete': True}, artifact=artifact)

tool = CustomTool('lookup', 'Look up the requested entities', {
    'type': 'object', 'properties': {'query': {'type': 'string'}},
    'required': ['query'], 'additionalProperties': False,
}, lookup, 'lookup-terminal-v2', terminal=True)
```

Registration does not grant execution or completion. Retain existing agent,
Runtime configuration and step grants, then add the host-only policy permission:

```python
policy = WorkflowPolicy(
    allowed_agents={'finder'}, allowed_schemas={'ack'},
    allowed_tools={'lookup'}, allowed_terminal_tools={'lookup'},
    allowed_validators={'verified'},
)
```

Register the tool in WorkflowBindings and a versioned Validator under `verified`.
Require that validator on the agent step. Keep its existing acknowledgement
schema if desired; the actual artifact is independently available to checks:

```python
def verified(output, context):
    artifact = context.terminal_completion['artifact']
    # Check actual executed criteria, ownership and completeness against the
    # trusted request/context. Validators are read-only and may run on recovery.
    return validate_against_request(artifact, context.request)
```

For direct Runtime integration, supply the same permission through
RunPolicy(allowed_tools=frozenset({'lookup'}),
allowed_terminal_tools=frozenset({'lookup'})). Runtime's Result is an execution
candidate. A host using Runtime without Harness owns its persistence and final
admission; exit code zero alone is not durable product success.

When an agent step has effective terminal grants, ordinary model-final JSON is
insufficient even if its schema is valid. A terminal-capable handler may return
ordinary JSON for incomplete work and continue the loop, but successful final
completion requires TerminalCompletion(output, artifact=...).

## Durability and retrieval

Harness saves the immutable receipt before schema/tool checks, semantic
validation and output binding. Both the acknowledgement and actual artifact are
stored. The versioned private metadata key is terminalCompletion, containing
tool/invocation identity, argument/output/artifact digests and the inline artifact.
artifactIncluded indicates whether that document contains the artifact; it does
not claim that an in-memory Runtime result has already been durably stored.

After successful completion, retrieve through the public operator API:

```python
evidence = harness.recovery_evidence()
accepted_id = evidence['checkpoint']['bindings']['find']['id']
receipt = next(r for r in evidence['receipts'] if r['id'] == accepted_id)
artifact = receipt['result']['metadata']['terminalCompletion']['artifact']
```

Authorize the run before using this private API, and project only approved
product fields into the response. A receipt existing, a tool status of ok or a
completed invocation ledger entry does not imply accepted output. Rejected and
cancelled receipts may retain artifacts; never surface them as accepted results.

A restart after receipt save adopts that receipt without executing the provider
or tools again. Before-receipt crashes retain interrupted/uncertain status and
do not automatically rerun the task. This is not an atomic transaction with an
external API or a cross-run business idempotency mechanism.

## First-release boundaries

- A provider batch containing a terminal tool must contain exactly one call.
  The entire unsafe batch is rejected before sibling dispatch.
- Inline artifacts are required. External artifact references and journaled
  terminal tools are not supported. Ordinary journaled prerequisite tools work.
- Use ProsaicRuntime.run, including an admitted RuntimeAdapter. Conversation
  turns, StructuredToolLoop, native CLI agents, UnifiedRuntime and run_tool do
  not support terminal-capable tools through this new contract.
- Cancellation, timeouts, authorization failures and unknown effects never
  become success. Known completion evidence can remain in a failed receipt.
- Artifact/result/event/receipt bounds still apply. A limit failure may retain
  only a digest breadcrumb with artifactIncluded=false and actual usage counts;
  it cannot be recovered as success.
- Failure receipts retain frozen accounting attribution and actual provider IDs
  when space permits. If the complete ID list cannot fit, providerCallBinding
  retains its version, count and SHA-256 digest instead of claiming an empty
  list. Correlate its namespace/environment and invocation context with the
  durable accounting recorder; this linkage never authorizes effect replay.
- Semantic/schema rejection blocks this terminal candidate even when the agent
  step would ordinarily allow more attempts. RuntimeAdapter also blocks further
  delegate dispatch after completion or an effectful terminal failure.

The credential-free installed-wheel witness is
`python -I scripts/terminal_completion_smoke.py`. It exercises a real loopback
provider, a separate durable artifact, simulated process interruption after
receipt save and fresh Harness adoption with one provider request/tool effect.

ALWAYS bind actual backend results and enforce product authorization/validation.
NEVER treat a dictionary field, model acknowledgement or digest breadcrumb as a
host-authorized successful completion.
