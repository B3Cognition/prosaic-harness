"""Loopback-only fault injection against a real disposable PostgreSQL server."""
import socket
import threading
from psycopg.conninfo import conninfo_to_dict, make_conninfo


class TcpProxy:
    def __init__(self, dsn):
        options = conninfo_to_dict(dsn)
        host = options.get('host', '127.0.0.1')
        if host not in {'127.0.0.1', 'localhost'}:
            raise ValueError('fault proxy requires a loopback disposable fixture')
        self.backend = (host, int(options.get('port', 5432)))
        self.stopped = threading.Event()
        self.blocked = threading.Event()
        self.commit_armed = threading.Event()
        self.commit_sent = threading.Event()
        self.sockets = []
        self.threads = []
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(16)
        self.listener.settimeout(0.1)
        self.dsn = make_conninfo(dsn, host='127.0.0.1', port=self.listener.getsockname()[1], sslmode='disable')

    def _pipe(self, source, target, replies):
        try:
            while not self.stopped.is_set():
                try:
                    data = source.recv(65536)
                except socket.timeout:
                    continue
                if not data:
                    break
                if (not replies and self.commit_armed.is_set()
                        and (b'COMMIT\x00' in data or b'COMMIT;\x00' in data)):
                    self.blocked.set()
                    self.commit_sent.set()
                    self.commit_armed.clear()
                if not (replies and self.blocked.is_set()):
                    target.sendall(data)
        except OSError:
            pass
        finally:
            for sock in (source, target):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()

    def _accept(self):
        while not self.stopped.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            backend = socket.create_connection(self.backend, timeout=1)
            client.settimeout(0.1)
            backend.settimeout(0.1)
            self.sockets.extend((client, backend))
            for source, target, replies in ((client, backend, False), (backend, client, True)):
                thread = threading.Thread(target=self._pipe, args=(source, target, replies), daemon=True)
                self.threads.append(thread)
                thread.start()

    def block_server_replies(self):
        self.blocked.set()

    def block_next_commit_reply(self):
        self.commit_armed.set()

    def __enter__(self):
        thread = threading.Thread(target=self._accept, daemon=True)
        self.threads.append(thread)
        thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        self.listener.close()
        for sock in self.sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        for thread in self.threads:
            thread.join(1)
