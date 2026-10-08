"""Synthetic loopback inference with observable real HTTP request counts."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading


class ModelServer:
    def __init__(self):
        self.request_count = 0
        self.received = threading.Event()
        self.delay = threading.Event()
        self.delay.set()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                owner.request_count += 1
                owner.received.set()
                if not owner.delay.wait(15):
                    return
                content = json.dumps({'id': 'synthetic', 'object': 'chat.completion',
                    'model': 'synthetic', 'choices': [{'index': 0, 'message': {'role': 'assistant',
                    'content': '{"approved":true}'}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}).encode()
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.delay.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
