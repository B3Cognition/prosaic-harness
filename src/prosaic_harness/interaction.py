"""Owned public views, projected from a single verified checkpoint.

ALWAYS retain complete selected semantic content within the host bounds.
NEVER include operator state or implicitly select all agent outputs.
"""
from dataclasses import dataclass
import json

from .admission_data import snapshot_json
from .errors import WorkflowAdmissionError
from .store import MAX_BYTES
from .workflow import digest


@dataclass(frozen=True)
class PendingInteraction:
    """An immutable encoded view; every decoded nested value has its own owner."""
    _json: str

    def to_dict(self):
        return json.loads(self._json)

    @property
    def run_id(self):
        return self.to_dict()['runId']

    @property
    def revision(self):
        return self.to_dict()['revision']

    @property
    def step_id(self):
        return self.to_dict()['stepId']

    @property
    def question(self):
        return self.to_dict()['question']

    @property
    def choices(self):
        return tuple(self.to_dict()['choices'])

    @property
    def deadline(self):
        return self.to_dict()['deadline']

    @property
    def response_schema_digest(self):
        return self.to_dict().get('responseSchemaDigest')

    @property
    def response_schema(self):
        return self.to_dict().get('responseSchema')

    @property
    def review_outputs(self):
        return self.to_dict().get('reviewOutputs')


def project_interaction(workflow, snapshot, *, review_outputs, include_response_schema,
                        maximum_bytes, policy):
    if type(maximum_bytes) is not int or maximum_bytes <= 0:
        raise ValueError('maximum_bytes must be a positive integer')
    if type(include_response_schema) is not bool:
        raise ValueError('include_response_schema must be a boolean')
    if type(review_outputs) not in (tuple, list):
        raise WorkflowAdmissionError('unknown_reference')
    state = snapshot.state
    if state['status'] != 'waiting':
        return None
    steps = workflow.definition['steps']
    # Bound the selection before iterating, without accepting arbitrary iterators.
    if len(review_outputs) > len(steps):
        raise WorkflowAdmissionError('limit_exceeded')
    for alias in review_outputs:
        if (type(alias) is not str or alias not in steps or steps[alias]['kind'] != 'agent'
                or alias not in state['outputs']):
            raise WorkflowAdmissionError('unknown_reference')
    step = steps[state['current']]
    document = {'version': 1, 'runId': state['run_id'], 'revision': snapshot.revision,
                'stepId': state['current'], 'question': step['question'],
                'choices': list(step['choices']), 'deadline': state['deadline']}
    if 'response_schema' in step:
        schema = workflow.schemas[state['current']]
        document['responseSchemaDigest'] = digest(schema)
        if include_response_schema:
            document['responseSchema'] = schema
    if review_outputs:
        document['reviewOutputs'] = {alias: state['outputs'][alias] for alias in review_outputs}
    owned = snapshot_json(document, maximum_bytes=min(maximum_bytes, MAX_BYTES,
                          policy.max_state_bytes if policy else MAX_BYTES),
                          maximum_depth=policy.max_json_depth if policy else 64,
                          maximum_nodes=policy.max_json_nodes if policy else 65536)
    return PendingInteraction(json.dumps(owned, sort_keys=True, allow_nan=False))
