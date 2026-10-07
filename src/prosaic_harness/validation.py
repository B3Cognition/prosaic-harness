"""Host-supplied deterministic checks; workflow YAML never imports code."""
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from .store import read_bytes


@dataclass(frozen=True)
class Validator:
    version: str
    check: object

    def __post_init__(self):
        if not isinstance(self.version, str) or not self.version or not callable(self.check):
            raise ValueError('validator needs an explicit version and callable check')


@dataclass(frozen=True)
class CheckContext:
    step: str
    request: object
    artifacts: dict
    evidence: dict
    bindings: dict
    human_responses: dict = field(default_factory=dict)


def load_validators(path):
    """Explicit CLI opt-in executes a trusted local Python file, never model code."""
    path = Path(path).absolute()
    content = read_bytes(path, maximum=100_000)
    version = hashlib.sha256(content).hexdigest()
    namespace = {'__file__': str(path), '__name__': 'prosaic_harness_checks'}
    exec(compile(content, str(path), 'exec'), namespace)
    checks = namespace.get('CHECKS')
    if not isinstance(checks, dict) or not checks:
        raise ValueError('trusted checks file must export a nonempty CHECKS mapping')
    return {name: Validator(version, check) for name, check in checks.items()}
