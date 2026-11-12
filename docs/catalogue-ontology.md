# Catalogue ontology

Load a host-selected v1 attachment with Core 0.5.1 or later in the supported
Core range. Attach it to the host's workflow catalogue and explicitly request
the ontology projection.

```python
from prosaic.ontology import load_ontology
from prosaic_harness import WorkflowCatalog, WorkflowFactory

catalog = WorkflowCatalog(agents=agents, schemas=schemas,
                          ontology=load_ontology("ontology.json"))
factory = WorkflowFactory(catalog=catalog, bindings=bindings, policy=policy)
discovery = factory.describe(include_ontology=True)
```

Keep the attachment in trusted application configuration. Register its agent
aliases and non-delegate custom tool aliases before constructing the factory.
Use public ontology IDs, descriptions and relation predicates suitable for
the discovery audience. Harness rejects invalid attachments with
`invalid_definition` and unregistered or delegate aliases with
`unknown_reference`.

The projection includes annotations for visible aliases, their concepts, and
relations whose two endpoints remain visible. It uses the same visibility
policy and response byte limit as ordinary discovery. `include_schemas` can
be selected independently. `describe()` omits ontology, as does an explicit
request with no visible annotations.

Keep workflow definitions and proposal envelopes in their existing format.
Ontology changes leave workflow and bundle identities, grants, prompts,
guards, and saved runs unchanged. Ordinary catalogue discovery and execution
also work with Core 0.5.0. An attachment on that Core version raises
`invalid_definition`.
