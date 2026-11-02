"""Installed public-API terminal workflow, durable artifact and fresh-worker adoption."""
import json
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
import uuid

from prosaic_runtime import CustomTool, EndpointConfig, ProsaicArtifact, RuntimeConfig, TerminalCompletion
from prosaic_harness import (FileRunStore, Harness, Validator, WorkflowBindings,
    WorkflowCatalog, WorkflowFactory, WorkflowPolicy)


class SimulatedCrash(Exception):
    pass


class CrashAfterReceipt:
    """Test host store wrapper: crash only after a genuine immutable receipt save."""
    def __init__(self, store): self.store = store
    def __getattr__(self, name): return getattr(self.store, name)
    def save_receipt(self, *args):
        self.store.save_receipt(*args)
        raise SimulatedCrash()


def main():
    helpers = runpy.run_path(str(Path(__file__).with_name('workflow_factory_smoke.py')))
    helpers['installed_origins']()
    with TemporaryDirectory(prefix='terminal-harness-wheel-') as directory:
        with helpers['synthetic_endpoint']() as (url, requests, replies):
            effects, checked = [], []
            artifact = {'entityId': 'sample-1', 'label': 'Synthetic item'}
            def lookup(arguments):
                effects.append(arguments)
                return TerminalCompletion({'complete': True}, artifact=artifact)
            def validate(output, context):
                checked.append(1)
                return [] if context.terminal_completion['artifact'] == artifact else ['artifact mismatch']
            tool = CustomTool('lookup_item', 'Find a synthetic entity', {
                'type': 'object', 'properties': {'query': {'type': 'string'}},
                'required': ['query'], 'additionalProperties': False}, lookup, 'terminal-v1', terminal=True)
            agent = ProsaicArtifact('approved', 'subagent', {'name': 'finder',
                'description': 'Find a synthetic entity', 'tools': ['lookup_item']},
                'ALWAYS use the admitted lookup. NEVER invent an entity.')
            config = RuntimeConfig({'local': EndpointConfig(url, 'fixture', features={'streaming': False})},
                {}, 'local', frozenset({'lookup_item'}))
            factory = WorkflowFactory(catalog=WorkflowCatalog(agents={'finder': agent}, schemas={'ack': {
                'type': 'object', 'properties': {'complete': {'const': True}},
                'required': ['complete'], 'additionalProperties': False}}),
                bindings=WorkflowBindings(config=config, custom_tools={'lookup_item': tool},
                    validators={'verified': Validator('artifact-v1', validate)}),
                policy=WorkflowPolicy(allowed_agents={'finder'}, allowed_schemas={'ack'},
                    allowed_tools={'lookup_item'}, allowed_terminal_tools={'lookup_item'},
                    allowed_validators={'verified'}))
            graph = {'version': 1, 'start': 'find', 'steps': {
                'find': {'kind': 'agent', 'agent': 'finder', 'schema': 'ack',
                    'tools': ['lookup_item'], 'require_tools': ['lookup_item'],
                    'validators': ['verified'], 'next': 'done'},
                'done': {'kind': 'finish', 'requires': ['find']}}}
            store, run_id = FileRunStore(Path(directory).resolve() / 'store'), uuid.uuid4().hex
            store.initialize()
            harness = Harness(factory.build(graph), store=CrashAfterReceipt(store), run_id=run_id)
            try:
                harness.run({'query': 'sample'})
            except SimulatedCrash:
                pass
            else:
                raise AssertionError('crash boundary was not exercised')
            receipt_before = harness.recovery_evidence()['receipts'][0]
            recovered = Harness(factory.build(graph), store=store, run_id=run_id)
            state = recovered.resume()
            assert state['status'] == 'completed' and len(requests) == 1 and len(replies) == 1
            assert effects == [{'query': 'sample'}] and checked == [1]
            accepted = state['bindings']['find']['id']
            receipt = next(r for r in recovered.recovery_evidence()['receipts'] if r['id'] == accepted)
            assert receipt['sha256'] == receipt_before['sha256']
            assert receipt['result']['metadata']['terminalCompletion']['artifact'] == artifact
            assert state['invocations'][0]['token_usage'] == 7
            print(json.dumps({'terminalCompletion': 'passed', 'restartAdoption': 'passed',
                              'providerRequests': 1, 'toolCalls': 1}))


if __name__ == '__main__':
    main()
