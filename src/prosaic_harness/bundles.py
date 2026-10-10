"""Frozen host material and bounded, reconstructable native proposal references.

ALWAYS readmit retained proposals using their immutable host bundle.
NEVER hydrate callbacks or host configuration from serialized references.
"""
from dataclasses import dataclass, field
import hashlib
import json
import re
import unicodedata

from .errors import WorkflowAdmissionError
from .factory import WorkflowFactory, admit_workflow
from .workflow import Workflow


_CANONICALIZATION = 'json-sort-keys-utf8-v1'
_DIGEST = re.compile(r'[0-9a-f]{64}')
_REFERENCE_KEYS = {
    'version': 'version', 'bundleVersion': 'bundle_version',
    'bundleIdentity': 'bundle_identity', 'canonicalization': 'canonicalization',
    'proposalSha256': 'proposal_sha256', 'workflowFingerprint': 'workflow_fingerprint',
    'admissionVersion': 'admission_version', 'schemaProfile': 'schema_profile',
}


def _fail(code='invalid_definition'):
    raise WorkflowAdmissionError(code) from None


def _label(value):
    if (type(value) is not str or not value or len(value) > 128
            or any(unicodedata.category(char) in {'Cc', 'Cf', 'Cs'} for char in value)
            or len(value.encode('utf-8')) > 128):
        _fail()


def _canonical(value):
    # Only bounded owned plain JSON reaches this encoder.
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        _fail()


def _sha256(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class WorkflowReference:
    version: int
    bundle_version: str
    bundle_identity: str
    canonicalization: str
    proposal_sha256: str
    workflow_fingerprint: str
    admission_version: int
    schema_profile: int

    def __post_init__(self):
        for value in (self.version, self.admission_version, self.schema_profile):
            if type(value) is not int or not 1 <= value <= 2147483647:
                _fail()
        _label(self.bundle_version)
        _label(self.canonicalization)
        for value in (self.bundle_identity, self.proposal_sha256, self.workflow_fingerprint):
            if type(value) is not str or not _DIGEST.fullmatch(value):
                _fail()
        if (self.version != 1 or self.admission_version != 1 or self.schema_profile != 1
                or self.canonicalization != _CANONICALIZATION):
            _fail('identity_mismatch')

    def to_dict(self):
        return {key: getattr(self, name) for key, name in _REFERENCE_KEYS.items()}

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or len(value) != len(_REFERENCE_KEYS):
            _fail()
        if any(type(key) is not str for key in value) or set(value) != _REFERENCE_KEYS.keys():
            _fail()
        return cls(**{name: value[key] for key, name in _REFERENCE_KEYS.items()})


@dataclass(frozen=True)
class PreparedWorkflow:
    workflow: Workflow
    proposal_json: str
    reference: WorkflowReference


@dataclass(frozen=True, init=False)
class WorkflowBundle:
    version: str
    identity: str
    _factory: WorkflowFactory = field(repr=False, compare=False)

    def __init__(self, version: str, factory: WorkflowFactory):
        _label(version)
        if type(factory) is not WorkflowFactory:
            _fail('binding_mismatch')
        frozen = factory._frozen_copy()
        object.__setattr__(self, 'version', version)
        object.__setattr__(self, '_factory', frozen)
        object.__setattr__(self, 'identity', _sha256(_canonical(frozen._bundle_material())))

    def _proposal(self, text):
        envelope = self._factory._proposal_envelope(text)
        proposal_json = _canonical(envelope)
        if len(proposal_json.encode('utf-8')) > self._factory._policy.max_proposal_bytes:
            _fail('limit_exceeded')
        return envelope, proposal_json

    def prepare_json(self, text: str) -> PreparedWorkflow:
        envelope, proposal_json = self._proposal(text)
        workflow = self._factory._admit_envelope(envelope)
        admit_workflow(workflow)
        reference = WorkflowReference(1, self.version, self.identity, _CANONICALIZATION,
                                      _sha256(proposal_json), workflow.fingerprint, 1, 1)
        return PreparedWorkflow(workflow, proposal_json, reference)

    def reconstruct(self, proposal_json: str, reference: WorkflowReference) -> Workflow:
        if type(reference) is not WorkflowReference:
            _fail()
        # Revalidate even an object whose frozen fields were forcibly changed.
        reference = WorkflowReference.from_dict(reference.to_dict())
        if reference.bundle_version != self.version or reference.bundle_identity != self.identity:
            _fail('identity_mismatch')
        envelope, canonical = self._proposal(proposal_json)
        if reference.proposal_sha256 != _sha256(canonical):
            _fail('identity_mismatch')
        workflow = self._factory._admit_envelope(envelope)
        admit_workflow(workflow)
        if reference.workflow_fingerprint != workflow.fingerprint:
            _fail('identity_mismatch')
        return workflow
