# Harness 0.9.17rc1

This candidate adds experimental catalogue ontology discovery. Attach a validated
Core ontology document with `WorkflowCatalog(ontology=attachment, ...)` and
request it through `WorkflowFactory.describe(include_ontology=True)`.
Use Core 0.5.1rc1 for the attachment. The existing supported Core family
continues to provide ordinary discovery.

The projection follows the existing agent and tool visibility rules. It leaves
workflow identity, admission, execution, and stored state unchanged.
