"""Two real provider wire fixtures with multi-call replies and no inference."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
import json
import pytest
from prosaic_runtime import RuntimeConfig,EndpointConfig


@pytest.fixture(params=['openai-compatible','anthropic'])
def parallel_endpoint(request):
    provider=request.param;requests=[];replies=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            answer=replies.pop(0)
            if callable(answer):answer=answer(requests[-1])
            calls=answer['calls'] if type(answer) is dict else None
            if provider=='anthropic':
                body=dict(id='fixture',type='message',role='assistant',model='fixture',content=[dict(type='tool_use',**c) for c in calls] if calls else [dict(type='text',text=answer)],stop_reason='tool_use' if calls else 'end_turn',usage=dict(input_tokens=2,output_tokens=3))
            else:
                msg=dict(role='assistant',content=None if calls else answer)
                if calls:msg['tool_calls']=[dict(id=c['id'],type='function',function=dict(name=c['name'],arguments=json.dumps(c['input']))) for c in calls]
                body=dict(choices=[dict(message=msg,finish_reason='tool_calls' if calls else 'stop')],usage=dict(total_tokens=5))
            data=json.dumps(body).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=Thread(target=server.serve_forever,daemon=True);worker.start()
    config=RuntimeConfig({'local':EndpointConfig(f'http://127.0.0.1:{server.server_port}/v1','synthetic',provider=provider,features={'streaming':False})},{},'local',frozenset())
    try:yield config,requests,replies
    finally:server.shutdown();server.server_close();worker.join(timeout=5);assert not worker.is_alive()


def queue_batch(replies,n=2):
    replies.append(dict(calls=[dict(id='call'+str(i),name='lookup',input={}) for i in range(n)]))
    replies.append('{"ok":true}')
