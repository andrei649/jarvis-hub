"""Isolated real routes/worker and browser assets; provider transport is mocked."""
import contextlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'agents')]
from tests.test_cloud_image import cloud as cloud_fixture

home = tempfile.TemporaryDirectory(prefix='nerva-cloud-hud-')
patch = pytest.MonkeyPatch()
patch.setenv("JARVIS_HOME", str(Path(home.name).resolve()))
fixture = cloud_fixture.__wrapped__(Path(home.name).resolve(), patch)
cloud = next(fixture)
from agents import web

web.USER_TOKEN = 'cloud-hud-user'
web.ADMIN_TOKEN = 'cloud-hud-owner'
web.orch = SimpleNamespace(cloud_images=cloud.runtime, autonomy=cloud.worker,
                          autonomy_queue=cloud.queue, channels={})
web.HERE = Path(sys.argv[2])
web.app.root_path = '/nerva'
for route in web.app.routes:
    if getattr(route, 'name', '') == 'v2-assets':
        route.app = StaticFiles(directory=web.HERE / 'v2' / 'assets')

async def fixture_app(scope, receive, send):
    path = scope['path']
    if not path.startswith('/nerva/'):
        return await JSONResponse({}, status_code=404)(scope, receive, send)
    path = path[len('/nerva'):]
    scope = {**scope, 'path':path, 'raw_path':path.encode()}
    if path == '/_test/state':
        return await JSONResponse({'requests':len(cloud.requests), 'tasks':len(cloud.queue.list())})(scope,receive,send)
    actual = (path.startswith(('/v2', '/api/media', '/api/artifacts', '/autonomy/tasks')))
    if not actual:
        return await JSONResponse({})(scope,receive,send)
    if path.startswith('/api/media/generation-tasks/'):
        await cloud.worker.tick()
    await web.app(scope, receive, send)

try:
    uvicorn.run(fixture_app, host='127.0.0.1', port=int(sys.argv[1]), lifespan='off', log_level='error')
finally:
    with contextlib.suppress(StopIteration):
        next(fixture)
    patch.undo()
    home.cleanup()
