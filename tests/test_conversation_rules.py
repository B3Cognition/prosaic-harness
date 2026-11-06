"""Guard policy survives Harness admission, execution and durable recovery."""
from dataclasses import replace

import pytest
from prosaic import parse_rules
from prosaic_runtime import Guard, ProsaicArtifact, Verdict
from prosaic_runtime.guards import strict_json
from prosaic_harness import Conversation, ConversationError
from support.conversations import binding_factory, scope
from support.conversation_host import conversation_fixture


def artifact(*, name='strict_json', action='fail', stage='final', settings=''):
    text = f'- ALWAYS obey the host rule. NEVER invent authority. <!-- enforce: {name}({settings}stage={stage}, on_violation={action}) -->\n'
    rules = parse_rules(text, 'companions/check.md')['rules']
    # The body deliberately has no tag: only the composed inspection carries this rule.
    return ProsaicArtifact('approved', 'subagent', {'name': 'approved', 'description': 'Synthetic guarded agent'},
        'ALWAYS answer from evidence. NEVER invent authority.', rules=tuple(rules), rule_issues=())


def test_required_policy_cannot_disappear_during_config_snapshot(binding_factory):
    config = replace(binding_factory().config, required_guards={'strict_json': 'fail'})
    with pytest.raises(ConversationError):
        binding_factory(config=config)


def test_composed_rule_cannot_disappear_during_artifact_snapshot(binding_factory):
    with pytest.raises(ConversationError):
        binding_factory(agent=artifact())


def test_inspection_issues_are_not_erased(binding_factory):
    bad = replace(artifact(), rules=(), rule_issues=({'code': 'invalidTag'},))
    with pytest.raises(ConversationError):
        binding_factory(agent=bad)


def test_policy_and_rules_are_owned_and_part_of_identity(binding_factory):
    settings = {'strict_json': 'fail'}
    config = replace(binding_factory().config, required_guards=settings)
    agent = artifact()
    registered = [strict_json()]
    binding = binding_factory(agent=agent, config=config, guards=registered)
    original = binding.identity
    settings.clear()
    agent.rules[0]['action'] = 'retry'
    registered.clear()
    binding.readmit()
    assert binding.config.required_guards == {'strict_json': 'fail'}
    assert binding.agent.rules[0]['action'] == 'fail'
    assert binding.identity == original
    assert binding_factory(agent=artifact(action='retry'), guards=[strict_json()]).identity != original


def test_guard_version_and_descriptor_are_identity_material(binding_factory):
    first = strict_json()
    second = Guard(first.name, 'strict-json-new', first.stages, first.check, settings_schema=first.settings_schema)
    left = binding_factory(agent=artifact(), guards=[first])
    right = binding_factory(agent=artifact(), guards=[second])
    assert left.identity != right.identity
    # Guard constructor snapshots the schema; caller mutation cannot alter admitted policy.
    first.settings_schema['additionalProperties'] = True
    left.readmit()


def test_mutated_registered_guard_is_refused_on_readmission(binding_factory):
    binding = binding_factory(agent=artifact(), guards=[strict_json()])
    # Simulate host declaration drift, including mutation bypassing frozen dataclass protection.
    object.__setattr__(binding._guards[0], 'version', 'changed')
    with pytest.raises(ConversationError):
        binding.readmit()


@pytest.mark.parametrize('guards', [[strict_json(), strict_json()], [object()]])
def test_invalid_or_duplicate_registrations_fail_before_execution(binding_factory, guards):
    with pytest.raises(ConversationError):
        binding_factory(agent=artifact(), guards=guards)


def test_interpreter_composed_rules_are_preserved(binding_factory):
    binding = binding_factory(interpreter=artifact(), guards=[strict_json()])
    assert binding.readmit()['interpreter']['artifact']['rules'][0]['guard'] == 'strict_json'
    with pytest.raises(ConversationError):
        binding_factory(interpreter=artifact())


@pytest.mark.parametrize('kind', ['memory', 'file'])
@pytest.mark.parametrize('answer,want', [('not JSON', 'ruleViolation'), ('{"ok": true}', None)])
def test_guarded_turn_is_durable_and_exact_replay_never_dispatches(conversation_fixture, kind, answer, want):
    from prosaic_harness import ConversationBindings, ConversationPolicy
    with conversation_fixture(kind) as fx:
        fx.bindings = ConversationBindings(artifact(), version='guard-v1', config=fx.bindings.config,
            policy=ConversationPolicy(), run_policy=fx.bindings.run_policy, guards=[strict_json()])
        fx.controller = fx.fresh_controller()
        session = fx.controller.create()
        fx.queue_text(answer)
        args = dict(message_id='guarded', message='Answer', expected_revision=session.revision)
        reply = fx.controller.send(session.session_id, **args).document
        assert reply['failureCode'] == want
        assert reply['status'] == ('failed' if want else 'completed')
        state = fx.store.load_session(session.session_id, scope=fx.scope).state
        aid = state['turns'][-1]['attempts'][-1]
        receipt = fx.store.load_receipt(session.session_id, aid, scope=fx.scope)
        rules = receipt['rules']
        assert rules['evaluated'] == ['companions/check.md:1:strict_json']
        assert rules['violated'] == (['companions/check.md:1:strict_json'] if want else [])
        assert len(rules['fingerprint']) == 64
        assert fx.fresh_controller().send(session.session_id, **args).document == reply
        assert fx.fresh_controller().recover(session.session_id).document == reply
        assert fx.provider_calls == 1


def test_changed_guard_version_cannot_resume_a_session(conversation_fixture):
    from prosaic_harness import ConversationBindings, ConversationPolicy
    with conversation_fixture() as fx:
        guard = strict_json()
        def bindings(registration):
            return ConversationBindings(artifact(), version='guard-v1', config=fx.bindings.config,
                policy=ConversationPolicy(), run_policy=fx.bindings.run_policy, guards=[registration])
        first = bindings(guard)
        controller = Conversation(first, store=fx.store, scope=fx.scope)
        session = controller.create()
        changed = Guard(guard.name, 'new', guard.stages, guard.check, settings_schema=guard.settings_schema)
        other = Conversation(bindings(changed), store=fx.store, scope=fx.scope)
        with pytest.raises(ConversationError, match='bindingMismatch'):
            other.send(session.session_id, message_id='new', message='Hello', expected_revision=session.revision)
        assert fx.provider_calls == 0


@pytest.mark.parametrize('change', ['extra', 'bad-hash', 'unknown-id', 'duplicate', 'non-string', 'too-many'])
def test_receipts_refuse_malformed_rule_metadata(change):
    from prosaic_harness import StoreCorrupt
    from prosaic_harness.session_contracts import verify_receipt, seal
    # A real legacy receipt supplies all correlation fields; only the rule extension is hostile.
    from test_session_contracts import reserve, receipt
    from prosaic_harness.session_contracts import new_session, mark_dispatch
    from prosaic_harness import ConversationBindings, ConversationPolicy, ConversationScope
    from prosaic_runtime import RuntimeConfig, EndpointConfig, RunPolicy
    config = RuntimeConfig({'local': EndpointConfig('http://127.0.0.1:9/v1', 'fixture')}, {}, 'local', frozenset())
    binding = ConversationBindings(replace(artifact(), rules=None), version='v1', config=config,
        policy=ConversationPolicy(), run_policy=RunPolicy(max_provider_requests=2, max_tool_calls=0))
    state = mark_dispatch(reserve(new_session('a'*32, ConversationScope('test','test','app','tenant','actor'), binding)), 'b'*32)
    packet = receipt(state)
    rules = {'version': 1, 'evaluated': ['a:1:check'], 'violated': [], 'fixed': [], 'faulted': [], 'fingerprint': 'f'*64}
    if change == 'extra': rules['text'] = 'private rule'
    elif change == 'bad-hash': rules['fingerprint'] = 'invalid'
    elif change == 'unknown-id': rules['violated'] = ['other']
    elif change == 'duplicate': rules['evaluated'] *= 2
    elif change == 'non-string': rules['evaluated'] = [12]
    else: rules['evaluated'] = [f'check-{i}' for i in range(257)]
    with pytest.raises(StoreCorrupt):
        verify_receipt(seal({**packet, 'rules': rules}))


def test_rule_receipt_capacity_is_checked_before_dispatch(binding_factory):
    agent = artifact()
    agent.rules[0]['id'] = 'x' * 70_000
    with pytest.raises(ConversationError):
        binding_factory(agent=agent, guards=[strict_json()])


def test_guard_capability_is_required_only_when_rules_are_used(binding_factory, monkeypatch):
    from prosaic_runtime import ProsaicRuntime
    monkeypatch.setattr(ProsaicRuntime, 'capabilities', ProsaicRuntime.capabilities - {'rule_admission_v1'})
    binding_factory().readmit()
    with pytest.raises(ConversationError, match='capabilityMissing'):
        binding_factory(agent=artifact(), guards=[strict_json()])


@pytest.mark.parametrize('kind', ['memory', 'file'])
def test_guard_failure_receipt_recovers_after_lost_ack(conversation_fixture, kind):
    from prosaic_harness import ConversationBindings
    from test_conversation_recovery import Crash
    with conversation_fixture(kind) as fx:
        fx.bindings = ConversationBindings(artifact(), version='guard-v1', config=fx.bindings.config,
            policy=fx.bindings.policy, run_policy=fx.bindings.run_policy, guards=[strict_json()])
        fx.controller = fx.fresh_controller()
        session = fx.controller.create()
        fx.queue_text('invalid JSON')
        def crash(event):
            if event['event'] == 'receiptSaved':
                raise Crash()
        with pytest.raises(Crash):
            fx.controller.send(session.session_id, message_id='one', message='Hello',
                expected_revision=session.revision, on_event=crash)
        reply = fx.fresh_controller().recover(session.session_id).document
        assert reply['status'] == 'failed' and reply['failureCode'] == 'ruleViolation'
        assert fx.fresh_controller().recover(session.session_id).document == reply
        assert fx.provider_calls == 1


def test_guard_failure_context_receipt_is_recoverable(conversation_fixture):
    from prosaic_harness import ConversationBindings
    from support.context_counter import fixture_context
    context_policy, counters = fixture_context()
    with conversation_fixture() as fx:
        fx.bindings = ConversationBindings(artifact(), version='guard-v1', config=fx.bindings.config,
            policy=fx.bindings.policy, run_policy=fx.bindings.run_policy, guards=[strict_json()],
            context_policy=context_policy, token_counters=counters)
        fx.controller = fx.fresh_controller()
        session = fx.controller.create()
        fx.queue_text('invalid JSON')
        reply = fx.controller.send(session.session_id, message_id='one', message='Hello',
            expected_revision=session.revision).document
        assert reply['failureCode'] == 'ruleViolation'
        state = fx.store.load_session(session.session_id, scope=fx.scope).state
        aid = state['turns'][-1]['attempts'][-1]
        packet = fx.store.load_receipt(session.session_id, aid, scope=fx.scope)
        assert packet['version'] == 2 and packet['rules']['violated'] == ['companions/check.md:1:strict_json']
        assert fx.fresh_controller().recover(session.session_id).document == reply


def file_guard():
    from pathlib import Path
    return Guard('file_policy', 'file-v1', ('final',),
        lambda stage, ctx: Verdict(ctx.draft == Path(ctx.paths['file']).read_text()),
        path_settings=('file',), settings_schema={'type': 'object', 'additionalProperties': False,
            'required': ['file'], 'properties': {'file': {'type': 'string'}}})


def test_guard_path_root_survives_cwd_changes(binding_factory, conversation_fixture, tmp_path, monkeypatch):
    project = tmp_path / 'policy-project'
    project.mkdir()
    (project / 'policy.txt').write_text('approved')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (elsewhere / 'policy.txt').write_text('wrong')
    monkeypatch.chdir(elsewhere)
    with conversation_fixture() as fx:
        binding = binding_factory(agent=artifact(name='file_policy', settings='file="policy.txt", '),
            guards=[file_guard()], rule_project=project, rule_project_identity='policy-v1',
            config=fx.bindings.config, tool_journal=None)
        monkeypatch.chdir(tmp_path)
        binding.readmit()
        controller = Conversation(binding, store=fx.store, scope=fx.scope)
        session = controller.create()
        fx.queue_text('approved')
        reply = controller.send(session.session_id, message_id='one', message='Check policy',
            expected_revision=session.revision).document
        assert reply['status'] == 'completed' and reply['answer'] == 'approved'


def test_path_guard_requires_explicit_project_and_refuses_escape(binding_factory, tmp_path):
    with pytest.raises(ConversationError):
        binding_factory(agent=artifact(name='file_policy', settings='file="policy.txt", '), guards=[file_guard()])
    with pytest.raises(ConversationError):
        binding_factory(agent=artifact(name='file_policy', settings='file="../outside.txt", '),
            guards=[file_guard()], rule_project=tmp_path, rule_project_identity='policy-v1')


def test_equivalent_project_relocation_keeps_guard_identity(binding_factory, tmp_path):
    projects = [tmp_path / name for name in ('first', 'second')]
    for project in projects:
        project.mkdir()
        (project / 'policy.txt').write_text('approved')
    def make(project, identity='policy-v1'):
        return binding_factory(agent=artifact(name='file_policy', settings='file="policy.txt", '),
            guards=[file_guard()], rule_project=project, rule_project_identity=identity)
    assert make(projects[0]).identity == make(projects[1]).identity
    assert make(projects[0]).identity != make(projects[1], 'other').identity


def test_missing_runtime_rule_capability_refuses_composed_metadata_before_conversion(binding_factory, monkeypatch):
    from prosaic_runtime import ProsaicRuntime
    monkeypatch.setattr(ProsaicRuntime, 'capabilities', ProsaicRuntime.capabilities - {'rule_admission_v1'})
    convert = ProsaicArtifact.from_inspection
    # Published Runtime 0.9.13's converter has no rule fields. Model that real boundary.
    monkeypatch.setattr(ProsaicArtifact, 'from_inspection', classmethod(lambda cls, data: convert(
        {key: value for key, value in data.items() if key not in {'rules', 'ruleIssues'}})))
    with pytest.raises(ConversationError):
        binding_factory(agent=artifact())
    with pytest.raises(ConversationError):
        binding_factory(interpreter=artifact())


def test_duplicate_rule_ids_are_refused_before_dispatch(binding_factory):
    one, two = artifact(name='first'), artifact(name='second')
    two.rules[0]['id'] = one.rules[0]['id']
    guards = [Guard(name, 'v1', ('final',), lambda stage, ctx: Verdict(True)) for name in ('first', 'second')]
    with pytest.raises(ConversationError):
        binding_factory(agent=replace(one, rules=one.rules + two.rules), guards=guards)


@pytest.mark.parametrize('context_enabled', [False, True])
@pytest.mark.parametrize('failure', ['raise', 'invalid-verdict'])
def test_guard_fault_is_a_durable_rule_failure(conversation_fixture, context_enabled, failure):
    from prosaic_harness import ConversationBindings
    from support.context_counter import fixture_context
    def check(stage, ctx):
        if failure == 'raise': raise RuntimeError('private guard fault')
        return {'invalid': 'not a Verdict'}
    with conversation_fixture('file') as fx:
        cp, counters = fixture_context()
        fx.bindings = ConversationBindings(artifact(name='broken'), version='guard-v1', config=fx.bindings.config,
            policy=fx.bindings.policy, run_policy=fx.bindings.run_policy,
            guards=[Guard('broken', 'v1', ('final',), check)],
            context_policy=cp if context_enabled else None, token_counters=counters if context_enabled else None)
        fx.controller = fx.fresh_controller()
        session = fx.controller.create()
        fx.queue_text('candidate')
        reply = fx.controller.send(session.session_id, message_id='one', message='Hello',
            expected_revision=session.revision).document
        assert reply['status'] == 'failed' and reply['failureCode'] == 'ruleViolation'
        state = fx.store.load_session(session.session_id, scope=fx.scope).state
        aid = state['turns'][-1]['attempts'][-1]
        packet = fx.store.load_receipt(session.session_id, aid, scope=fx.scope)
        assert packet['rules']['faulted'] == ['companions/check.md:1:broken']
        assert fx.fresh_controller().recover(session.session_id).document == reply
        assert fx.provider_calls == 1


@pytest.mark.parametrize('replace_after_admission', [False, True])
def test_rule_project_source_symlink_cannot_redirect_guard_paths(binding_factory, tmp_path, replace_after_admission):
    project, outside = tmp_path / 'project', tmp_path / 'outside'
    project.mkdir()
    (outside / '.prosaic').mkdir(parents=True)
    (project / 'policy.txt').write_text('approved')
    (outside / 'policy.txt').write_text('wrong')
    def make():
        return binding_factory(agent=artifact(name='file_policy', settings='file="policy.txt", '),
            guards=[file_guard()], rule_project=project, rule_project_identity='policy-v1')
    binding = make() if replace_after_admission else None
    (project / '.prosaic').symlink_to(outside / '.prosaic', target_is_directory=True)
    with pytest.raises(ConversationError):
        binding.runtime() if binding is not None else make()
