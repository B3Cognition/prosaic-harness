# Harness 0.9.11 — versioned cross-step review blueprint V1

The release source archive includes `examples/revision-review`: a copyable
application-owned policy using the existing public Validator/CheckContext and
Harness workflow APIs. Obtain it from the versioned source archive or immutable
v 0.9.11 tag, not from site-packages. The wheel supplies the existing SDK APIs.

The revised-review step requires accepted first-review and revision outputs.
A finding must reference a current revised insight that was previously flagged
or whose text changed/is new relative to original trusted input. Duplicate IDs,
malformed dependencies, removed targets and model-claimed change authority refuse.
This simple text/ID predicate is a policy example for Cerebro to adapt, not a
claim that generic infrastructure understands semantic changes.

The trusted validator's semantic+content version is saved with the run. Changed
code refuses resume; declared dependencies retain receipt identity/freshness.
Feedback can repair one final-review refusal within two attempts/four total
calls; exhaustion blocks without accepting the output. Human acceptance and
existing explicit interrupted-call recovery remain in force. Workflow enforcement
tags are a deferred V2 and the existing validator API remains supported.

**Identity impact:** no production engine/API, artifact digest, workflow or
conversation identity fields change. Existing flows are unaffected. The new
blueprint has its own schema, prose and versioned validator identity as expected.
The Runtime dependency floor remains `>=0.9.14,<0.10`; final qualification uses the
actually published Runtime 0.9.16 and Core 0.5.0 with exact immutable lineage.
PostgreSQL store 0.4.1 is an unchanged qualification witness, not republished.

Required qualification includes complete source tests, installed SDK blueprint
integration, OS/Python and real PostgreSQL 16/18 gates, dependency floors, exact-head
CI SUCCESS and equal tested/merged trees. Publish original qualified archives only;
verify public PyPI/GitHub bytes and fresh wheel+source consumers. Synthetic tests
are credential-free and do not establish live-provider certification.

[Cerebro follow-ups](cerebro-requests.md) record all other requests for future work.

## Published release

Published on PyPI and [GitHub](https://github.com/B3Cognition/prosaic-harness/releases/tag/v0.9.11) from source `294e935f70e2cfcce2c4ca80dbed5d8aa3977b83`.
The [immutable candidate qualification](https://github.com/B3Cognition/prosaic-harness/actions/runs/42374644545) passed before promotion. Public wheel/source hashes and isolated installed
consumer checks were verified after publication. These are synthetic SDK
checks, not live-provider certification.

See [all releases and compatibility](releases.md) for dependency floors,
qualified trains, identity/readmission notes and independently versioned adapters.
