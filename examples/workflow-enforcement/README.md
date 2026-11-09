# Workflow enforcement with accepted earlier outputs

Copy this directory from the Harness 0.9.12 source archive, install
`b3-prosaic-harness==0.9.13` and `b3-prosaic-runtime==0.9.19`, then configure
`runtime.yml`. The public SDK lives in the wheel; these application resources
ship in the source archive. No call is made by loading or constructing a workflow.

The trusted `host.py` registers a content-versioned final Guard. The final agent
contains `<!-- enforce: review_scope(stage=final, on_violation=retry) -->` and
explicitly requires the accepted `first_review` and `revision` outputs. Its
Guard reads `context.input_data['workflow']`: version, step, nested original
request, declared accepted artifacts/bindings, evidence projection and feedback.
Only current revised insight IDs that were flagged initially or have changed
text/are new may receive findings. Model-supplied `changed_ids` grant no authority.
This application-owned text/ID predicate is an example, not semantic certification.

Run from the configured copy with the same Python that owns the installed SDK:

```sh
python run.py --live --mode yaml --run-dir ./private-run
python run.py --live --mode native --run-dir ./other-private-run
```

`--live` explicitly authorizes model calls. The runner selects that Python's
Core executable without relying on ambient PATH. Trusted request-shape validation
precedes execution. The YAML and native factory demonstrate the same application
flow; their distinct native admission/project declarations have distinct identities.

There are at most three Harness invocations (`max_calls: 3`), not three HTTP
requests. Each invocation has an explicit maximum of two provider requests and
zero tool calls; at most six provider requests are permitted overall. The final
step has one Harness attempt. Runtime can repair one rule failure within its
remaining request/token/deadline budget. Cap1 cannot authorize request2. A final
rule failure/fault/exhaustion blocks with `rule_violation`; Harness does not open
another invocation to bypass it. Schema and V1 validators still gate acceptance.

A successful review pauses for explicit human accept/reject. Nothing publishes
or mutates an external system. Durable receipts retain bounded rule IDs, binding
fingerprint, fact hash and prepared context identity. Saved receipts recover
without another provider call. Missing receipts remain uncertain; explicit retry
consent never creates missing token-budget evidence. Changed Guard code/version,
prose, schema or accepted dependency bindings refuses reuse or marks outputs stale.

Guarded workflows use the supported Runtime API turn path. Acquisition, terminal
tools, `{{args}}` interpolation and required file-read receipts refuse admission.
Use the existing untagged paths for those contracts. Custom native tools support
all four rule phases; use explicit host permissions and finite caps.

The existing `examples/revision-review` Validator V1 remains unchanged and
supported. No live endpoint has been certified by synthetic acceptance tests.
