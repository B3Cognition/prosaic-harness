# Harness 0.9.20

This release qualifies the default CLI sandbox policy in Runtime 0.9.27.
Earlier supported Runtime releases use their own default. Explicit
`cli_sandbox: {mode: required}` selects confinement on either release.

An existing CLI workflow changing from off to required needs a fresh run
directory. File workflows and conversation bindings without CLI manifest
directories or extra runtime roots use the historical off-mode identity.
Checkpoints that explicitly selected required with neither setting need a
fresh run or session. Reconstruct a native bundle using its original sandbox
mode. Bundles created with the former default use
`CliSandboxConfig(mode='off')` for reconstruction.

The PostgreSQL adapter remains on its existing release.
