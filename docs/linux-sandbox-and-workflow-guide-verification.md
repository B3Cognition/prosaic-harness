# Linux sandbox and service guide follow-up

Local preparation checkpoint: 2026-10-10, based on Harness 0.6.2. This change
updates CI and usage documentation. Production code, test cases, package
versions and dependency pins match the released tag.

## Why the five cases skipped

The original Harness Linux jobs installed Python dependencies but no Bubblewrap.
Five existing cases in `tests/test_cli_sandbox.py` require `/usr/bin/bwrap` on
Linux: the sandboxed blueprint, outside-secret confinement and three required-
sandbox downgrade cases. The tests are unchanged from the released baseline.
They passed locally through macOS Seatbelt; the original Linux jobs reported
332 passes and five skips. Native Runtime had its own operational Linux sandbox
gates, but those did not execute these Harness cases.

The local Docker Desktop Linux context is configured. An escalated read-only
server request timed out after 15 seconds during this follow-up. Local container
qualification could not proceed. Native Linux ARM64 runners avoid that engine
dependency and exercise the real Linux kernel and userspace.

## Mandatory Linux qualification

Harness now configures Ubuntu 24.04 AMD64 and ARM64 with Python 3.11/3.12/3.13.
Each job installs Runtime's already-qualified immutable Bubblewrap source commit
and its narrowly scoped AppArmor broker profile, then requires an operational
kernel sandbox. It does not disable host-wide AppArmor or kernel protections.

Every job runs all seven CLI sandbox cases and rejects JUnit reports with any
skip, failure, error, missing/extra case or duplicate replacing a required case.
The full Harness suite and build follow that gate. PostgreSQL 16/18 owned
crash/standby and clean-wheel gates remain configured unchanged.

At this source checkpoint, the local full suite passed 337 tests; all seven
sandbox cases passed and their real JUnit report satisfied the new gate. Ten
controlled reports verified acceptance of all seven passes and rejection of
invalid coverage/outcomes. Workflow YAML, shell/Python syntax, exact Runtime
AppArmor profile and two existing database CI/metadata checks passed. Native
qualification is recorded by the pull request's GitHub checks and the release's
follow-up verification asset, rather than inferred from these local results.

## Usage documentation

[The workflow factory guide](workflow-factory.md) now contains complete examples
for host setup, client/LLM JSON admission, approved two-agent composition, inline
instructions and embedded prompt resources, safe rejection, policy bounds,
run/pause/resume, worker reconstruction and installed-wheel verification.

Every construction example was executed against installed Core 0.3.2, Runtime
0.7.1 and Harness 0.6.2. Model calls, preflight and host callbacks were forbidden
and none occurred. The safe rejection branch and independent composition/inline
permission failures passed. The existing installed smoke covers execution and
human resume; no live provider was used.
