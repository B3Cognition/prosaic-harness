from support.local_cluster import LocalCluster


def test_crash_restart_refreshes_reassigned_host_port(monkeypatch):
    cluster = LocalCluster.__new__(LocalCluster)
    cluster.primary = {'id': 'owned-id', 'name': 'owned-primary',
                       'dsn': 'postgresql://postgres@127.0.0.1:32769/postgres'}
    cluster.dsn = cluster.primary['dsn']
    commands, persisted, waited = [], [], []
    monkeypatch.setattr(cluster, '_validate_container', lambda entry: commands.append(('validate', entry['id'])))

    def run(*args):
        commands.append(args)
        return '127.0.0.1:32770' if args[0] == 'port' else ''

    monkeypatch.setattr(cluster, '_run', run)
    monkeypatch.setattr(cluster, '_write_manifest', lambda: persisted.append(cluster.primary['dsn']))
    monkeypatch.setattr(cluster, '_wait', lambda dsn: waited.append(dsn))
    cluster.crash_restart()
    expected = 'postgresql://postgres@127.0.0.1:32770/postgres'
    assert waited == [expected]
    assert persisted == [expected]
    assert cluster.dsn == cluster.primary['dsn'] == expected
    assert commands == [('validate', 'owned-id'), ('kill', '--signal', 'KILL', 'owned-id'),
                        ('start', 'owned-id'), ('port', 'owned-id', '5432/tcp')]
