# Bounded sub-agents

Use `SubAgentBindingsV1` to register named specialists for a conversation or an authored workflow node. Each binding ties a reviewed Runtime artifact to its allowed local reads, an independent Harness context pack, and an output schema. The parent selects a registered alias as a tool, with a task and, if configured, a schema-checked draft. The parent receives the validated finding and any approved observations and writes the final answer.

In an authored YAML workflow, list the specialist aliases under the existing agent node's `tools`. List the same names in the parent agent's Markdown front matter. The host maps each alias to a different context pack with `SubAgentBindingsV1` and passes the bindings to `Workflow.load(..., sub_agents=bindings)` together with the tool contract, operation namespace, and journal. Native authored workflows use `WorkflowBindings(sub_agents=bindings)` and `WorkflowFactory.build(...)`. Model-proposed workflows cannot select these aliases.

```yaml
steps:
  coordinate:
    kind: agent
    agent: subagents/coordinator.md
    schema: answer.json
    tools: [analyze, review]
    next: done
  done:
    kind: finish
```

Use the same host-owned accounting scope, fenced journal, and lease for the parent and its children. Supply an exact operation namespace and current launch and result grants. Protect the full input footprint of each child, including sources it used without citing them. Result grants run during dispatch, before replay or delivery, and before retained reads. During execution the callback receives the parent tool context. For retained use it receives a `SubAgentRetainedUseV1` with the trusted viewer and the originating invocation. The result grant receives both inline citation references and opaque references for pack status disclosures. Its current policy must cover both.

Provision the workflow or session store with `initialize(sub_agents=True)` for a new store. Drain writers before `migrate_sub_agent_storage()` on an existing store. On PostgreSQL run `prosaic-harness-postgres migrate-sub-agents --store workflows|conversations --dsn-env NAME` as the schema owner. The workflow marker advances to 5 and the session marker to 6. Existing runs and sessions keep their original encodings.

| Last durable record | Recovery |
| --- | --- |
| Prepared parent and no dispatch marker | Resume the exact parent input under a current lease and grants. |
| Dispatched parent and no parent receipt | Leave the parent interrupted. Inspect the host journal when reconciling it. |
| Saved parent receipt | Reopen with the same bindings and adopt the receipt without contacting the provider. |

Provider and tool limits are enforced across the parent and children. Reported tokens are a stopping threshold for further dispatch. An already accepted provider response can exceed that threshold. The recorder keeps provider charges under the original attribution and records the parent invocation link on child calls.
