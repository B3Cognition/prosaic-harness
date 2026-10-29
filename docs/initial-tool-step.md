# Explicit first native tool

An agent step may declare `initial_tool: lookup_entity` in addition to its `tools` and optional `require_tools`. The named tool must already be registered, permitted by host policy/configuration, and granted by the agent and step. It changes workflow identity. Omit it to preserve existing behavior and fingerprints.

ALWAYS use this setting for a host-admitted operation whose first tool is known and mandatory. Runtime forces only the first native function choice, then resumes normal tool selection; schema, budgets, authorization, receipt and output validation remain enforced.
NEVER use it to grant a tool, accept a textual tool envelope, bypass an unavailable provider, or replay an uncertain effect. It cannot be combined with acquisition or a conflicting required file read. Execution fails before dispatch if Runtime lacks initial-tool enforcement.

`require_tools` verifies successful tool receipts after an invocation. `initial_tool` also constrains the first provider choice; use both when success is required for advancement. No new retries or limits are introduced.

With the explicit `bounded_tool_recovery` policy, a completed provider refusal of the first-tool choice may consume the step's existing validation-repair allowance. Runtime must report the matching enforced choice, zero executed tools and tool rounds, known usage, and no tool/acquisition events. The next invocation receives validation feedback; normal attempt, call, token, deadline and cancellation limits still apply.

ALWAYS retain the failed invocation and usage receipt and require successful native-tool receipts before advancement.
NEVER infer zero effects from model text or a missing answer. Timeout, interruption, cancellation, unknown usage, pending/started work, mismatched evidence and any executed tool are not eligible for this repair. It never increases the configured attempt allowance or applies a draft.
