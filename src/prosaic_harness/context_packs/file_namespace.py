"""Explicit workflow directory migration with a barrier for released writers."""
from contextlib import ExitStack
import fcntl
import os
import secrets
import stat
from ..store import parent_descriptor,locked,read_bytes
from ..run_store import StoreBusy,StoreIncompatible,StoreUnavailable,StoreCorrupt,validate_id

MARKER=b'{"layout":"context-packs-v1","storageContract":2,"version":2}'
SUB_AGENT_MARKER=b'{"layout":"sub-agents-v1","storageContract":5,"version":5}'
PARALLEL_MARKER=b'{"layout":"parallel-tools-v1","storageContract":4,"version":4}'
TOOL_MARKER=b'{"layout":"tool-contracts-v1","storageContract":3,"version":3}'
INTENT='.workflow-pack-data.json'


def address(store): return store.root if store._legacy else store.root/store.namespace


def data_address(store):
    path=address(store)
    return path.with_name('.'+path.name+'.context-packs-v1')


def _private_file(value):
    if (not stat.S_ISREG(value.st_mode) or value.st_nlink!=1 or value.st_uid!=os.getuid()
            or stat.S_IMODE(value.st_mode)!=0o600): raise StoreUnavailable()


def _read_marker(parent,name):
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
    try:
        value=os.fstat(fd);_private_file(value)
        data=os.read(fd,1025)
        named=os.stat(name,dir_fd=parent,follow_symlinks=False)
        if (value.st_dev,value.st_ino)!=(named.st_dev,named.st_ino): raise StoreUnavailable()
        if data not in (MARKER,TOOL_MARKER,PARALLEL_MARKER,SUB_AGENT_MARKER): raise StoreIncompatible()
        return value.st_dev,value.st_ino,data
    finally: os.close(fd)


def inspect_namespace(store):
    """Read-only discovery. Missing legacy directories remain lazy as before."""
    path=address(store);data=data_address(store)
    try:
        with parent_descriptor(path) as (parent,name):
            try: value=os.stat(name,dir_fd=parent,follow_symlinks=False)
            except FileNotFoundError:
                try: os.stat(data.name,dir_fd=parent,follow_symlinks=False)
                except FileNotFoundError: return False,path
                raise StoreIncompatible('finish explicit workflow storage migration') from None
            if stat.S_ISDIR(value.st_mode):
                store._tool_contract_storage=False
                return False,path
            marker_identity=_read_marker(parent,name)
            fd=os.open(data.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
            try:
                value=os.fstat(fd)
                if value.st_uid!=os.getuid() or stat.S_IMODE(value.st_mode)!=0o700: raise StoreUnavailable()
                intent=_read_marker(fd,INTENT)
                if marker_identity[2]!=intent[2]: raise StoreIncompatible('finish explicit workflow storage migration')
                store._tool_contract_storage=marker_identity[2] in (TOOL_MARKER,PARALLEL_MARKER,SUB_AGENT_MARKER)
                store._parallel_tool_storage=marker_identity[2] in (PARALLEL_MARKER,SUB_AGENT_MARKER)
                store._sub_agent_storage=marker_identity[2]==SUB_AGENT_MARKER
                incarnation=(marker_identity,(value.st_dev,value.st_ino))
                previous=getattr(store,'_pack_incarnation',None)
                if previous is not None and previous!=incarnation: raise StoreUnavailable()
                store._pack_incarnation=incarnation
            finally: os.close(fd)
            return True,data
    except FileNotFoundError: return False,path
    except OSError: raise StoreUnavailable() from None


def _install_marker(parent,name,*,tool_contracts=False,parallel_tools=False,sub_agents=False):
    temporary='.pack-marker-'+secrets.token_hex(16)
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(SUB_AGENT_MARKER if sub_agents else PARALLEL_MARKER if parallel_tools else TOOL_MARKER if tool_contracts else MARKER);handle.flush();os.fsync(handle.fileno())
        # A concurrently created old directory must never be overwritten.
        os.link(temporary,name,src_dir_fd=parent,dst_dir_fd=parent,follow_symlinks=False)
    finally:
        os.unlink(temporary,dir_fd=parent)
        os.fsync(parent)


def _replace_marker(parent,name,target=TOOL_MARKER):
    _read_marker(parent,name)
    temporary='.pack-upgrade-'+secrets.token_hex(16)
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(target);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,name,src_dir_fd=parent,dst_dir_fd=parent);os.fsync(parent)
    finally:
        try:os.unlink(temporary,dir_fd=parent)
        except FileNotFoundError:pass


def migrate_namespace(store,*,fresh=False,tool_contracts=False,parallel_tools=False,sub_agents=False):
    tool_contracts=tool_contracts or parallel_tools or sub_agents
    target=SUB_AGENT_MARKER if sub_agents else PARALLEL_MARKER if parallel_tools else TOOL_MARKER
    markers = (MARKER, TOOL_MARKER, PARALLEL_MARKER, SUB_AGENT_MARKER)
    if store._sessions: raise StoreBusy('drain workflow writers before migration')
    path=address(store);data=data_address(store)
    try:
        with parent_descriptor(path,create=True) as (parent,name):
            lock_name='.'+name+'.pack-migration.lock'
            lock_fd=os.open(lock_name,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=parent)
            try:
                _private_file(os.fstat(lock_fd))
                try: fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError: raise StoreBusy() from None
                try: value=os.stat(name,dir_fd=parent,follow_symlinks=False)
                except FileNotFoundError: value=None
                if value is not None and not stat.S_ISDIR(value.st_mode):
                    marker=_read_marker(parent,name)
                    if tool_contracts:
                        if fresh and markers.index(marker[2]) < markers.index(target):raise StoreIncompatible('migrate existing tool contract storage explicitly')
                        with ExitStack() as leases:
                            fd=os.open(data.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
                            try:
                                info=os.fstat(fd)
                                if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:raise StoreUnavailable()
                                intent=_read_marker(fd,INTENT)
                                for child in os.listdir(fd):
                                    if child==INTENT:continue
                                    validate_id(child)
                                    leases.enter_context(locked(data/child))
                                # Complete an interrupted two-marker migration only
                                # under the owner lock and all existing run leases.
                                target = max((intent[2], marker[2], target), key=markers.index)
                                if intent[2] != target: _replace_marker(fd, INTENT, target)
                                if marker[2] != target: _replace_marker(parent, name, target)
                                store._pack_incarnation=None
                            finally:os.close(fd)
                    return inspect_namespace(store)
                if value is not None and fresh: raise StoreIncompatible('migrate existing workflow storage explicitly')
                with ExitStack() as leases:
                    if value is not None:
                        fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
                        try:
                            if store._legacy:
                                leases.enter_context(locked(path))
                            else:
                                for child in os.listdir(fd):
                                    if child==INTENT: continue
                                    validate_id(child)
                                    child_value=os.stat(child,dir_fd=fd,follow_symlinks=False)
                                    if not stat.S_ISDIR(child_value.st_mode): raise StoreCorrupt()
                                    try: leases.enter_context(locked(path/child))
                                    except ValueError: raise StoreBusy('drain workflow writers before migration') from None
                            try: _read_marker(fd,INTENT)
                            except FileNotFoundError: (_install_marker(fd,INTENT,tool_contracts=True,parallel_tools=parallel_tools,sub_agents=sub_agents) if tool_contracts else _install_marker(fd,INTENT))
                            try: os.stat(data.name,dir_fd=parent,follow_symlinks=False)
                            except FileNotFoundError: pass
                            else: raise StoreIncompatible('workflow migration destination already exists')
                            os.rename(name,data.name,src_dir_fd=parent,dst_dir_fd=parent)
                            os.fsync(parent)
                        finally: os.close(fd)
                    else:
                        try: os.mkdir(data.name,mode=0o700,dir_fd=parent)
                        except FileExistsError: pass  # Resume only our fully written intent.
                        fd=os.open(data.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
                        try:
                            try: _read_marker(fd,INTENT)
                            except FileNotFoundError:
                                if os.listdir(fd): raise StoreIncompatible()
                                (_install_marker(fd,INTENT,tool_contracts=True,parallel_tools=parallel_tools,sub_agents=sub_agents) if tool_contracts else _install_marker(fd,INTENT))
                        finally: os.close(fd)
                    (_install_marker(parent,name,tool_contracts=True,parallel_tools=parallel_tools,sub_agents=sub_agents) if tool_contracts else _install_marker(parent,name))
                return inspect_namespace(store)
            finally: os.close(lock_fd)
    except StoreBusy: raise
    except OSError: raise StoreUnavailable(outcome_unknown=True) from None
