"""Citations derive from selected/read captured representations, never pack indexes."""
from dataclasses import replace
import hashlib
import time

from prosaic_runtime import (EvidenceAuthorizerV1, EvidenceDraftV1, HostEvidenceImportV1,
    ToolContractBindingsV1, TurnEvidence)
from ..tool_contracts import ToolContracts
from .codec import ContextPackError, encode, decode, digest
from .selection import PreparedContextPack, project, _content_bytes
from .authorization import ExposureBindings, ContextUse, authorize_context_use
from .bindings import ContextPackBindings

MODEL_PROFILE = 'workflow-pack-citations-input-v1'
CONVERSATION_PROFILE = 'context-pack-citations-input-v1'


def _public_entry(entry, *, index=False):
    keys = {'citationId', 'contentKind', 'representation'} | ({'label', 'contentBytes'} if index else {'content'})
    return {key: value for key, value in entry.items() if key in keys}


def public_pack_input(value):
    value = decode(encode(value))
    pack = value.get('contextPack') if type(value) is dict else None
    if type(pack) is not dict or type(pack.get('items')) is not list or type(pack.get('index')) is not list:
        raise ContextPackError('contextBindingMismatch')
    pack['items'] = [_public_entry(entry) for entry in pack['items']]
    pack['index'] = [_public_entry(entry, index=True) for entry in pack['index']]
    return value


def source_locator(entry):
    # Retain the original locator in the pack receipt. The generic bounded
    # contract needs only a stable private reference back to that exact origin.
    return 'pack_' + digest({key: entry[key] for key in ('sourceIdentity', 'sourceLocator', 'itemId')})


def read_data(body):
    return {key: body[key] for key in ('citationId', 'representation', 'content', 'contentKind',
        'complete', 'nextOffset', 'continuationAvailable')}


def read_source(body):
    return EvidenceDraftV1(body['citationId'], body['sourceRevision'], source_locator(body), '/content', 'Captured context')


class PackEvidenceBindings:
    def __init__(self, pack, bindings, contracts, scope, *, deadline, session_id=None):
        if type(pack) is not PreparedContextPack or type(bindings) is not ContextPackBindings or type(contracts) is not ToolContracts:
            raise ContextPackError('contextBindingMismatch')
        pack = PreparedContextPack.from_dict(pack.to_dict())
        self.pack, self.bindings, self.contracts = pack, bindings.frozen_copy(), contracts.frozen_copy()
        self.scope, self.deadline, self.session_id = scope, deadline, session_id
        self.entries = {}
        grants = ExposureBindings.from_pack(pack)
        if grants.scope.to_dict() != bindings.scope.to_dict():
            raise ContextPackError('contextScopeMismatch')
        self.grants = grants
        imports = []
        for item in pack.envelope['items']:
            grant = next(entry for entry in grants.entries if entry['citationId'] == item['citationId'] and entry['disclosure'] == 'inline')
            source = EvidenceDraftV1(item['citationId'], grant['sourceRevision'], source_locator(grant), '', grant['sourceAlias'])
            imported = HostEvidenceImportV1(scope, source, evidence_id=item['citationId'], origin_kind='contextPack',
                origin_receipt_sha256=pack.pack_identity, model_view=_public_entry(item),
                content_pointer='/content', reference_pointer='/citationId')
            self.entries[(source.source_key, source.selector, imported.to_dict()['contentSha256'])] = grant
            imports.append(imported)
        generic = contracts.evidence_authorizer
        if generic is None:
            raise ContextPackError('contextCapabilityMissing')
        identity = 'pack_' + digest(dict(host=generic.to_dict(), pack=bindings.authorizer.descriptor()))
        self.runtime_bindings = ToolContractBindingsV1(contracts.identity, contracts.version, scope,
            evidence_authorizer=EvidenceAuthorizerV1(identity, '1', self.authorize),
            display_authorizer=contracts.display_authorizer, citations=contracts.citations,
            retained=tuple(imports), limits=contracts.limits)

    def authorize(self, use):
        try:
            self.contracts.descriptor(); self.bindings.readmit()
            if use.scope != self.scope or self.contracts.evidence_authorizer.authorize(use) is not True:
                return False
            entry = self.entries.get((use.source_key, use.selector, use.content_sha256))
            if entry is None:
                # Other registered tool producers retain the generic host grant.
                # A claim to a pack identifier must have a captured pack origin.
                return not use.source_key.startswith('ctx_')
            if use.source_revision != entry['sourceRevision'] or use.locator != source_locator(entry):
                return False
            purpose = {'modelUse': 'invocation', 'cite': 'citation', 'retainedRead': 'retainedRead'}[use.purpose]
            exposures = ExposureBindings(self.bindings.scope, [entry])
            authorize_context_use(self.bindings, ContextUse(purpose, scope=self.bindings.scope,
                operation_id=self.scope.invocation_id, run_id=self.scope.run_id, session_id=self.session_id,
                exposures=exposures, deadline=None if purpose == 'retainedRead' else self.deadline))
            return True
        except Exception:
            return False

    def capture_read(self, body):
        body = decode(encode(body))
        grant = next((entry for entry in self.grants.entries if entry['citationId'] == body.get('citationId') and
            entry['disclosure'] == 'discoverable'), None)
        if grant is None or body.get('snapshotDigest') != self.pack.snapshot.identity or body.get('packReference') != self.pack.reference:
            raise ContextPackError('contextBindingMismatch')
        if any(body.get(key) != grant[key] for key in ('sourceAlias', 'sourceIdentity', 'sourceRevision', 'sourceLocator', 'itemId')):
            raise ContextPackError('contextBindingMismatch')
        item = next(item for item in self.pack.snapshot.to_dict()['items'] if
            item['sourceAlias'] == grant['sourceAlias'] and item['itemId'] == grant['itemId'])
        selected = project(item['content'], body['representation'])
        raw = _content_bytes(selected)
        if encode(selected) != encode(body['content']) or hashlib.sha256(raw).hexdigest() != body['contentSha256']:
            raise ContextPackError('contextBindingMismatch')
        entry = {**grant, 'disclosure': 'read', 'representation': body['representation'],
            'contentSha256': body['contentSha256'], 'contentBytes': len(raw), 'contentKind': body['contentKind']}
        if not self.grants.contains(ExposureBindings(self.bindings.scope, [entry])):
            raise ContextPackError('contextBindingMismatch')
        key = (grant['citationId'], '/content', digest(selected))
        if key not in self.entries and len(self.entries) >= self.contracts.limits.max_registry_items:
            raise ContextPackError('contextPackLimit')
        self.entries[key] = entry


def pack_evidence_bindings(frame, runtime_evidence, bindings, *, tool_contracts, scope, deadline=None, session_id=None):
    from .records import ContextPackInvocation, reader_exposures
    pack = frame if type(frame) is PreparedContextPack else ContextPackInvocation.from_dict(frame.to_dict()).prepared_pack
    result = PackEvidenceBindings(pack, bindings, tool_contracts, scope,
        deadline=deadline if deadline is not None else time.monotonic() + 60, session_id=session_id)
    if runtime_evidence is not None:
        evidence = TurnEvidence.from_dict(runtime_evidence).to_dict()
        if type(frame) is not ContextPackInvocation:
            raise ContextPackError('contextBindingMismatch')
        reader_exposures(frame, evidence)
        for outcome in evidence['toolOutcomes']:
            from .reader import NAME
            value = outcome.get('outcome', {})
            if outcome.get('name') != NAME or value.get('status') != 'ok':
                continue
            tagged = value.get('result')
            if type(tagged) is dict and tagged.get('version') == 1 and 'sources' in tagged:
                data = tagged['data']
                grant = next(entry for entry in result.grants.entries if entry['citationId'] == data['citationId'] and entry['disclosure'] == 'discoverable')
                result.capture_read({**grant, **data, 'snapshotDigest': pack.snapshot.identity, 'packReference': pack.reference,
                    'contentSha256': hashlib.sha256(_content_bytes(data['content'])).hexdigest()})
    return result
