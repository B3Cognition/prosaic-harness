"""Host integration: supply authenticated scope and a current-use authorizer.

The host chooses its provider config and executes the returned Workflow with
Harness. Loading a declaration does not run inference or authorize a user.
"""
from pathlib import Path
from prosaic_harness import (
    Workflow, ContextPackBindings, ContextScope, ContextAuthorizer,
    InputSource, EvidenceSource, ArtifactSource,
)


def load(path: Path, *, scope: ContextScope, authorizer: ContextAuthorizer):
    bindings = ContextPackBindings(
        specs={},
        sources={
            'task': InputSource('/task'),
            'requirements': EvidenceSource('requirements.md'),
            'constraints': EvidenceSource('constraints.md'),
            'candidate': ArtifactSource('build'),
        },
        scope=scope, authorizer=authorizer,
    )
    return Workflow.load(path.resolve(), context_packs=bindings)
