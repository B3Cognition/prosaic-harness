# Harness 0.9.18 — catalogue ontology

Hosts can attach v1 [catalogue ontology](catalogue-ontology.md) to a
`WorkflowCatalog` and request it with `WorkflowFactory.describe(include_ontology=True)`.
The response includes annotations for visible registered aliases and relations
whose endpoints remain visible. Delegate aliases are excluded. Plain discovery
keeps its existing response shape.

Install `b3-prosaic-harness==0.9.18` with `b3-prosaic==0.5.1` to use ontology.
The declared Core floor remains `>=0.5.0,<0.6` and the Runtime dependency remains
`>=0.9.21,<0.10`. Runtime 0.9.23 is the qualification version. Existing workflow
and bundle identities, admission and saved runs carry forward. The existing
PostgreSQL store 0.4.5 and recorder 0.3.0 need no ontology migration.

The release gate qualifies the same Harness artifacts on the ordinary Core
0.5.0 floor and in a separate installed ontology lane with Core 0.5.1 and the
published Runtime 0.9.23 wheel. The ontology lane covers both direct wheel
installs and wheels rebuilt from the source archives. These checks use synthetic
inputs and cover policy projection and saved-run compatibility.
