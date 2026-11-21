# Harness 0.9.20

This release qualifies the default CLI sandbox policy in Runtime 0.9.27.
Earlier supported Runtime releases use their own default. Explicit
`cli_sandbox: {mode: required}` selects confinement on either release.

## Upgrade and resume

1. Upgrade Harness and Runtime together. Core 0.5.0 remains supported for
   ordinary use. The optional catalogue ontology attachment requires Core 0.5.1.
2. Keep the existing configuration and bindings when resuming a CLI-free file
   workflow, session, or native bundle. Retained identities preserve both the
   previous default and any sandbox mode that the operator set explicitly in
   YAML or directly in Python.
3. For saved CLI workflows, keep the policy that the original run sealed.
   If the run used the former off-mode default, the trusted operator can set
   `cli_sandbox: {mode: 'off'}` explicitly to finish it with host execution
   permissions. Switching a workflow to required mode needs a new run directory
   and fresh approvals.

If your Python host clones the nested `CliSandboxConfig` with
`dataclasses.replace` or reconstructs it from a serialized dictionary, pass
the original mode explicitly when reopening saved records. Use
`CliSandboxConfig(mode='off', runtime_roots=...)` for records written with
the former default.

Run [Runtime preflight](https://github.com/B3Cognition/prosaic-runtime/blob/v0.9.27/docs/cli-tools.md#cli-sandbox)
in the target worker before moving CLI traffic. Linux Docker workers can use
the [qualified Bubblewrap policy](https://github.com/B3Cognition/prosaic-integration-lab/blob/8d63e81/docs/sandboxed-tools.md#qualify-the-linux-image).
PostgreSQL store 0.4.5 remains compatible with its existing schema.
