import pytest
from support.local_cluster import LocalCluster


def test_owned_cluster_records_and_passes_explicit_platform(monkeypatch):
    cluster=LocalCluster('docker','16',platform='linux/amd64')
    commands=[]
    def stop_at_run(*args,**kwargs):
        commands.append(args)
        raise RuntimeError('stop before launching test container')
    monkeypatch.setattr(cluster,'_run',stop_at_run)
    try:
        with pytest.raises(RuntimeError): cluster._container('fixture')
        args=commands[0]
        assert args[args.index('--platform')+1]=='linux/amd64'
        assert LocalCluster.from_manifest(cluster.manifest).platform=='linux/amd64'
    finally: cluster.stop()


def test_owned_platform_is_closed():
    with pytest.raises(ValueError): LocalCluster('docker','16',platform='host-invented')
