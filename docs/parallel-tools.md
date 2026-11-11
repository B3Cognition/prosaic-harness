# Parallel read tools (Harness 0.9.15)

`WorkflowPolicy(parallel_tools=ParallelToolPolicyV1(max_concurrency=4))` grants
an upper bound. Each agent node explicitly selects
`parallel_tools: {max_concurrency: 2}` in native/JSON/YAML definitions.
Omitted nodes remain sequential. Other node kinds reject the field. YAML hosts
pass `parallel_tools=` to `Workflow.load`. Markdown agent prose never grants
concurrency or marks a handler safe. The trusted registration must declare
`CustomTool(..., with_context=True, parallel_read=True)`; this asserts read-only,
independent, concurrent-safe behavior, including repeated calls of itself.

Both workflows and conversations require explicit `ToolContracts` and finite
provider/tool allowances. Conversations select the policy in `RunPolicy`.
Interpretation stays tool-free and sequential. Typed returns/citations remain
separate options. Runtime owns the scheduler; Harness passes prepared inputs
and retains receipts with existing leases and claim fencing. MCP and sub-agents
remain separate follow-ups. Runtime adapters/direct nodes/native CLI execution
do not add parallel support.

Reads run in fixed bounded windows. Unmarked custom, builtin, CLI and context
reader tools are serial barriers. Guards/history/citations reduce in admitted
call order; safe settlement events may report physical completion earlier.
All host callbacks except read handlers run on the invocation owner. Workers
receive fresh context, cannot reenter Runtime, and are joined before return.
Cancellation stops further dispatch and drains callbacks. An uncooperative
Python callback can delay return; there is no forced thread termination.

Enable storage explicitly as its owner: `initialize(parallel_tools=True)` for
fresh Memory/File/PostgreSQL stores, or `migrate_parallel_tool_storage()` for an
existing initialized store after draining writers. PostgreSQL workers cannot
initialize/migrate. CLI: `prosaic-harness-postgres migrate-parallel-tools --store
workflows|conversations --dsn-env NAME` (DSN value stays private). No tables,
columns, size grants or historical documents are changed.

| Enabled record | Version | Previous tool contract version |
| --- | --- | --- |
| Workflow state / receipt | 5 / 4 | 4 / 3 |
| Conversation state / receipt | 5 / 5 | 4 / 4 |
| File/PG workflow storage | 4 | 3 |
| File/PG conversation storage | 5 | 4 |
| Runtime encoding / frozen / evidence | v5 / 3 / 4 | v4 / 2 / 3 |

Known old readers remain supported without rewriting their bytes; old writers
refuse the new storage markers. New records pin the full scheduler policy,
registration and existing tenant/scope bindings. A fresh controller adopts an
accepted receipt without repeating provider/handler work. Unknown dispatch is
reconciled conservatively, never rerun from progress events. Current evidence
and display grants still govern history/read/citation exposure. Journal
settlement uses existing claim tokens independently of stale controller saves.

Build both archives once from a committed head with
`scripts/release_artifacts.py build --ref COMMIT --output NEW_DIRECTORY --expect
b3-prosaic-harness=0.9.15 --expect
b3-prosaic-harness-postgres=0.4.4 --project . --project adapters/postgres`.
Install the original candidate wheels plus the exact Runtime candidate and
retained Core bytes in an isolated environment. Run
`python -I -m pytest -o pythonpath=tests tests/test_parallel_tool_installed.py`
and `python -I scripts/tool_contract_smoke.py`.
This checkpoint does not publish or repin any public release.
