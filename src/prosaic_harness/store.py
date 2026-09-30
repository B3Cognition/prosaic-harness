"""Bounded JSON and descriptor-pinned local storage (Linux/macOS)."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat

MAX_BYTES = 8 * 1024 * 1024


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def parse_json(text):
    return json.loads(text, object_pairs_hook=unique_pairs,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


@contextmanager
def parent_descriptor(path, *, create=False):
    path = Path(os.path.abspath(path))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parent.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, path.name
    finally:
        os.close(fd)


def read_bytes(path, *, maximum=MAX_BYTES):
    with parent_descriptor(path) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
                raise ValueError('evidence/checkpoint is not a bounded regular file')
            content = handle.read(maximum + 1)
            after = os.fstat(handle.fileno())
            if len(content) > maximum or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('file changed while reading or exceeds size limit')
            return content


def read_json(path):
    return parse_json(read_bytes(path).decode('utf-8'))


def write_json(path, value):
    content = json.dumps(value, indent=2, allow_nan=False).encode()
    if len(content) > MAX_BYTES:
        raise ValueError('checkpoint exceeds size limit')
    with parent_descriptor(path, create=True) as (parent, name):
        try:
            existing = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(existing.st_mode):
                raise ValueError('checkpoint destination must be a regular file')
        except FileNotFoundError:
            pass
        temporary = '.checkpoint-' + secrets.token_hex(16)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


@contextmanager
def locked(directory):
    with parent_descriptor(Path(directory) / 'run.lock', create=True) as (parent, name):
        fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'a') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError('run lock must be a regular file')
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('run is locked by another process') from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
