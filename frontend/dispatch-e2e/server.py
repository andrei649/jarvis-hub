"""Actual jobs routes, ephemeral store, no app lifespan/model/channels.

Build the current HUD into a temporary directory; never changes committed assets.
Only jobs routes and static shell are reachable through this fixture wrapper.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'agents')]
TEMP = tempfile.TemporaryDirectory(prefix='nerva-dispatch-browser-')
home = Path(TEMP.name)
os.environ.update(JARVIS_HOME=str(home), JARVIS_USER_HOME=str(home),
                  JARVIS_TESTING='1', JARVIS_ROOT_PATH='', PYTHON_DOTENV_DISABLED='1')
subprocess.run(['node', 'node_modules/vite/bin/vite.js', 'build', '--outDir', str(home / 'v2')],
               cwd=ROOT / 'frontend', check=True, stdout=subprocess.DEVNULL)

import uvicorn
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from agents import web
from agents.core.autonomy.jobs import JobRunner, JobStore

web.HERE = home
web.ADMIN_TOKEN = 'dispatch-fixture-admin'
store = JobStore(home / 'jobs.db')
orch = SimpleNamespace(channels={})
orch.jobs = JobRunner(store, orch=orch, scheduler=lambda: None, quiet=lambda: False)
web.orch = orch
job = orch.jobs.create(name='Browser receipt reminder', schedule_text='0 9 * * *',
                       action={'type':'remind','message':'isolated receipt completed'}, options={'deliver':[]})
for route in web.app.routes:
    if getattr(route, 'path', None) == '/v2/assets':
        route.app = StaticFiles(directory=home / 'v2' / 'assets')


async def isolated(scope, receive, send):
    path = scope.get('path', '')
    if path.startswith('/api/jobs') or path.startswith('/v2'):
        return await web.app(scope, receive, send)
    return await JSONResponse({})(scope, receive, send)


uvicorn.run(isolated, host='127.0.0.1', port=45149, lifespan='off', log_level='error')
