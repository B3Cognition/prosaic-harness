# Model-free tool steps

ALWAYS admit direct execution through trusted host policy. NEVER treat registration,
ordinary agent tool grants, or proposed workflow fields as direct permission.

A `tool` step executes one registered host `CustomTool` through Runtime's public
`run_tool` method and `direct_tool_v1` capability. Builtin and CLI tools are not
supported. The host must set `WorkflowPolicy.allowed_direct_tools`, which defaults
to empty and must be a subset of `allowed_tools`. The YAML adapter takes the same
separate permission as `Workflow.load(path, custom_tools=registry,
allowed_direct_tools={'lookup_entity'})`; YAML cannot grant this permission itself.

```yaml
lookup:
  kind: tool
  tool: lookup_entity
  arguments: {query: literal-host-admitted-reference}
  schema: result
  validators: [verify_result]
  next: review
```

The fields are `kind`, `tool`, `arguments`, `schema`, `next`, with optional `inputs`,
`optional_inputs`, `validators`, and `max_visits`. Native schema aliases refer to
the trusted catalogue; YAML schemas refer to confined local files. Arguments must
be a literal JSON object. Strings have no reference, template, or evaluation
semantics. The callback receives only that literal object; it does not receive
run input or dependency values implicitly. The trusted consumer constructs an
opaque task reference when dynamic host state must be accessed.

ALWAYS validate returned JSON and host validators before accepting output. NEVER
repair or retry a tool step after output, schema, or validator rejection. It makes
one Runtime invocation per visit, consuming one `max_calls` slot, zero model tokens,
and zero provider requests. Existing limits are not increased. Accepted tool
outputs support dependencies, gates, checks, pause/finish requirements and explicit
review-output projections in the same way as accepted agent outputs. Required
input freshness is checked before invocation and acceptance. The durable receipt
retains a host envelope with dependency bindings and `tool_arguments`; Runtime
receives only `tool_arguments`.

ALWAYS save pending state before execution and an actual receipt before advancing.
NEVER automatically replay interrupted work whose receipt is missing. Resume
reuses a stored receipt without another callback. A missing receipt stays
`interrupted_call`, including when `retry_interrupted=True` is supplied for a tool
step. The host must reconcile uncertain effects before starting a new run; use a
stable journal operation key where the tool contract supports reconciliation.
Cancellation, deadlines and lease loss fence advancement; a trusted running
callback remains cooperative and cannot be forcibly preempted.

Literal arguments, used tool descriptors and explicit direct permissions are bound
into workflow identity. Empty direct permissions add no identity material, keeping
existing agent-only fingerprints unchanged. Discovery describes `tool` and
`allowedDirectTools`; its proposal schema offers only host-permitted direct names
and never grants authority.
