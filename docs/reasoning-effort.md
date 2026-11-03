# Reasoning effort in workflows

Harness admits existing canonical Prosaic agents and delegates model execution
to Runtime. Put behavioral instructions and neutral `effort` in agent Markdown;
keep model IDs, native account profiles, server URLs and credentials in trusted
Runtime configuration. Prose grants no execution permission.

Runtime 0.9.12 maps supported values `none`, `low`, `medium`, `high`, `xhigh`,
`max` and Codex-only `ultra` to the selected provider/model's native control.
The selected model's metadata or exact documented defaults determine support;
every profile does not need `supported_efforts`. Explicit declarations remain
available for custom aliases or restricted deployments.

Explicit agent effort overrides profile defaults. Omitted effort preserves the
profile default; unsupported effort fails admission/execution rather than being
silently reduced. Keep capability declarations and workflow bindings aligned.
Changing agent metadata or bound configuration changes workflow identity; start
a fresh run instead of trying to resume a differently admitted workflow.

Gemma exposes one thinking switch: `none` is off, and all supported positive
levels are on. The verified local ThinkingCap Qwen 3.8 model supports none,
low, medium and xhigh. Claude Code native and direct Anthropic API execution
are separate adapters; the direct API does not gain effort support merely
because Claude Code supports an effort flag. Native `ultra` can enable vendor
subagents and is not a portable reasoning-token budget.

The Integration Lab's [reasoning blueprints](https://github.com/B3Cognition/prosaic-integration-lab/tree/main/lab_runner/reasoning_eval/data)
contain seven canonical agents, API/native profile examples, a strict answer
schema and a one-call API-backed workflow. The workflow validates offline with
`prosaic-harness validate workflow.yml`. Its `run` command makes a real API call
after host configuration and credential setup.

Native execution consumes Prosaic prose directly; there is no need to copy it
into Claude/Codex folders. Harness workflow execution still requires explicit
host adapter bindings and policy. Do not substitute native YAML into an API
workflow and assume that this supplies those bindings.

Follow the [Lab guide](https://github.com/B3Cognition/prosaic-integration-lab/blob/main/docs/reasoning-effort.md)
for credential-free wire checks, persistent bounded live allowances and separate
format/answer grading. A correct result or successful HTTP response alone cannot
prove that a server honored thinking. Usage accounting and PostgreSQL persistence
do not enable effort or certify provider controls.
