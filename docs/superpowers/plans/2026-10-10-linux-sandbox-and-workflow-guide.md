# Linux sandbox qualification and workflow service guide

The release qualification passed the native workflow and database checks, but
Harness's Linux jobs skipped five existing CLI sandbox cases because Bubblewrap
was absent. The user requested an explanation and usable documentation for the
new workflow factory. Close the avoidable CI gap and supply tested examples.

The local Docker Desktop context is configured, but an escalated read-only
engine request timed out after 15 seconds on 2026-10-10. No engine restart,
container security downgrade or mutation of shared fixtures is authorized by
this follow-up. Use native GitHub Linux AMD64 and ARM64 runners instead.

- [x] Install the same pinned Bubblewrap backend and narrowly scoped AppArmor
  profile already qualified by Runtime. Require an operational kernel sandbox.
- [x] Configure every CLI sandbox case with a JUnit gate requiring seven passes and
  zero skips, failures or errors, then the complete Harness suite on both Linux
  architectures and Python 3.11/3.12/3.13. Preserve PostgreSQL 16/18 gates.
- [x] Add concrete generated-JSON, approved-composition and inline-instruction
  examples, safe admission errors, host ownership and default-limit guidance.
- [x] Validate guide examples against the released installed API without model
  calls or callbacks, check local sandbox and packaging wiring, review changes.
- [x] Prepare a reviewable CI/documentation change for publication and native
  qualification. Keep existing release tags and distributions unchanged.

This source checkpoint records local preparation, before native dispatch. The
API and production behavior do not change. Record actual native results in the
pull request's GitHub checks and follow-up verification asset after the required
matrix completes. The 0.6.2 release's original receipts remain historical evidence.
