import pytest
from prosaic_harness import FileSessionStore,FileRunStore,StoreIncompatible,StoreBusy
from support.conversations import binding_factory,scope
from prosaic_harness.session_contracts import new_session


def test_session_migration_preserves_record_bytes_and_new_process_readiness(tmp_path,scope,binding_factory):
    store=FileSessionStore(tmp_path/'private',namespace='test');store.initialize()
    state=new_session('a'*32,scope,binding_factory())
    with store.lease('a'*32,scope=scope) as lease: store.create_session('a'*32,state,lease,scope=scope)
    path=tmp_path/'private'/'test'/('a'*32)/'session.json';before=path.read_bytes()
    store.migrate_context_pack_storage()
    assert path.read_bytes()==before
    restarted=FileSessionStore(store.root,namespace='test')
    assert 'context_packs_v1' in restarted.capabilities
    assert restarted.load_session('a'*32,scope=scope).state==state
    marker=tmp_path/'private'/'test'/'.conversation-store.json'
    assert marker.read_bytes()==b'{"storageContract":3,"version":3}'


def test_workflow_opt_in_has_explicit_capability_and_blocks_old_layout(tmp_path):
    root=tmp_path/'runs';store=FileRunStore(root,namespace='test')
    assert 'context_packs_v1' not in store.capabilities
    store.initialize(context_packs=True)
    assert 'context_packs_v1' in store.capabilities
    # Released FileRunStore has no marker reader. Its old directory address
    # must be a regular marker file so its first lease/write fails closed.
    assert (root/'test').is_file()
    with pytest.raises(OSError): (root/'test'/('a'*32)).mkdir(parents=True)
    assert 'context_packs_v1' in FileRunStore(root,namespace='test').capabilities


def test_workflow_legacy_namespace_requires_explicit_migration(tmp_path):
    store=FileRunStore(tmp_path/'runs',namespace='test')
    with store.lease('a'*32): pass
    with pytest.raises(StoreIncompatible): store.initialize(context_packs=True)
    with store.lease('a'*32):
        with pytest.raises(StoreBusy): store.migrate_context_pack_storage()
    store.migrate_context_pack_storage();store.migrate_context_pack_storage()
    assert 'context_packs_v1' in store.capabilities


def test_workflow_migration_preserves_legacy_bytes_and_pack_writer_is_canonical(tmp_path):
    from test_context_pack_workflow_records import allocated
    from prosaic_harness.context_packs.codec import encode
    from prosaic_harness.contracts import seal
    workflow,state,arguments,frame=allocated();run=state['run_id']
    store=FileRunStore(tmp_path/'runs',namespace='test')
    legacy=seal({'version':2,'run_id':run,'historic':'ž\n'})
    with store.lease(run) as lease: store.create_run(run,legacy,lease)
    before=store._directory(run).joinpath('run.json').read_bytes()
    store.migrate_context_pack_storage()
    assert store._directory(run).joinpath('run.json').read_bytes()==before
    with store.lease(run) as lease:
        revision=store.load_run(run).revision
        store.save_run(run,state,revision,lease)
    assert store._directory(run).joinpath('run.json').read_bytes()==encode(state)
    restarted=FileRunStore(store.root,namespace='test')
    assert restarted.load_run(run).state==state


def test_workflow_pack_write_requires_migration_and_complete_reservation(tmp_path):
    from test_context_pack_workflow_records import allocated
    from prosaic_harness import StoreCorrupt
    from prosaic_harness.contracts import seal
    workflow,state,arguments,frame=allocated();run=state['run_id']
    store=FileRunStore(tmp_path/'runs',namespace='test')
    with store.lease(run) as lease:
        with pytest.raises(StoreIncompatible): store.create_run(run,state,lease)
    store.migrate_context_pack_storage()
    state['contextPacks']['reservations'][frame.invocation_id]=None
    with store.lease(run) as lease:
        with pytest.raises(StoreCorrupt): store.create_run(run,seal(state),lease)


@pytest.mark.parametrize('kind',['symlink','hardlink'])
def test_workflow_marker_cannot_be_aliased(tmp_path,kind):
    from prosaic_harness import StoreUnavailable
    store=FileRunStore(tmp_path/'runs',namespace='test');store.initialize(context_packs=True)
    marker=store.root/'test';other=tmp_path/'other'
    if kind=='symlink':
        marker.rename(other);marker.symlink_to(other)
    else: other.hardlink_to(marker)
    with pytest.raises(StoreUnavailable): FileRunStore(store.root,namespace='test').check_ready()


def test_workflow_migration_unknown_ack_is_resumed_only_explicitly(tmp_path,monkeypatch):
    from prosaic_harness import StoreUnavailable
    import prosaic_harness.context_packs.file_namespace as migration
    store=FileRunStore(tmp_path/'runs',namespace='test')
    with store.lease('a'*32): pass
    actual=migration._install_marker
    def interrupted(parent,name):
        if name=='test': raise OSError('injected marker acknowledgement fault')
        return actual(parent,name)
    monkeypatch.setattr(migration,'_install_marker',interrupted)
    with pytest.raises(StoreUnavailable) as failure: store.migrate_context_pack_storage()
    assert failure.value.outcome_unknown
    restarted=FileRunStore(store.root,namespace='test')
    with pytest.raises(StoreIncompatible): restarted.check_ready()
    assert not (store.root/'test').exists()
    monkeypatch.setattr(migration,'_install_marker',actual)
    restarted.migrate_context_pack_storage()
    assert 'context_packs_v1' in restarted.capabilities
