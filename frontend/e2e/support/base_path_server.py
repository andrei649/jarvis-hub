"""Real Nerva routing/assets behind a real prefix-stripping HTTP proxy.

No app lifespan/providers run. Three shallow app instances share the actual route
objects, with independent configured roots and middleware stacks. Read-only app
requests reach those routes. Mutations and cognition streaming are fixture-only
responses before dispatch, except the offline schedule parser and appearance
preferences (real guarded routes over the temporary Settings DB). No user data
or model services are involved.
"""
from __future__ import annotations

import copy
import http.client
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'agents')]
TEST_HOME = tempfile.TemporaryDirectory(prefix='nerva-h130-')
os.environ['JARVIS_HOME'] = TEST_HOME.name
os.environ['JARVIS_USER_HOME'] = TEST_HOME.name
os.environ['JARVIS_ROOT_PATH'] = '/one'
os.environ['JARVIS_USER_TOKEN'] = 'h130-isolated-test-token'

import uvicorn
from starlette.responses import JSONResponse, StreamingResponse

from agents import web

assert web.app.root_path == '/one', 'process configuration must configure the real app'

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 45130
APPS = {}
for prefix in ('', '/one', '/two/nerva'):
    app = copy.copy(web.app)
    app.root_path = prefix
    app.middleware_stack = None
    APPS[prefix] = app


async def isolated(scope, receive, send):
    prefix = dict(scope['headers']).get(b'x-test-mount', b'').decode()
    if prefix not in APPS:
        return await JSONResponse({}, status_code=400)(scope, receive, send)
    if scope['path'] == '/api/cognition/stream':
        async def frames():
            yield 'data: {"type":"test","text":"ready"}\n\n'
        return await StreamingResponse(frames(), media_type='text/event-stream')(scope, receive, send)
    if scope['method'] not in ('GET', 'HEAD') and scope['path'] not in ('/api/schedule/parse', '/api/preferences/appearance'):
        # Observe body delivery/streaming without invoking business mutations.
        body = b''
        while True:
            event = await receive()
            body += event.get('body', b'')
            if not event.get('more_body'):
                break
        if scope['path'] == '/chat/stream':
            async def frames():
                yield 'data: {"text":"fixture reply"}\n\n'
            return await StreamingResponse(frames(), media_type='text/event-stream')(scope, receive, send)
        return await JSONResponse({'fixture': True, 'bytes': len(body)})(scope, receive, send)
    await APPS[prefix](scope, receive, send)


class Proxy(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        prefix = next((p for p in ('/two/nerva', '/one') if self.path == p or self.path.startswith(p + '/')), '')
        path = self.path[len(prefix):] or '/'
        conn = http.client.HTTPConnection('127.0.0.1', PORT + 1, timeout=20)
        headers = {key: value for key, value in self.headers.items() if key.lower() not in ('host', 'connection', 'x-test-mount')}
        headers.update({'Host': f'127.0.0.1:{PORT}', 'X-Test-Mount': prefix, 'Connection': 'close'})
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        try:
            conn.request(self.command, path, body=body, headers=headers)
            response = conn.getresponse()
            self.send_response(response.status)
            for name, value in response.getheaders():
                if name.lower() not in ('transfer-encoding', 'connection'):
                    self.send_header(name, value)
            self.end_headers()
            while chunk := response.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()

    do_POST = do_GET
    do_HEAD = do_GET
    do_PUT = do_GET
    do_DELETE = do_GET
    do_PATCH = do_GET


server = uvicorn.Server(uvicorn.Config(isolated, host='127.0.0.1', port=PORT + 1, lifespan='off', log_level='error'))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
import time

while not server.started:
    time.sleep(.02)
ThreadingHTTPServer(('127.0.0.1', PORT), Proxy).serve_forever()
