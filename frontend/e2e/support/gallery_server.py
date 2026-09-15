"""Real gallery/export routes and production HUD over a disposable 220-row catalog.

No app lifespan, orchestrator or provider runs. All files and settings are in an
isolated temporary home; only explicit browser export invokes the real ZIP route.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'agents')]
TEST_HOME = tempfile.TemporaryDirectory(prefix='nerva-h518-')
home = Path(TEST_HOME.name).resolve()
os.environ.update(JARVIS_HOME=str(home), JARVIS_USER_HOME=str(home), JARVIS_ROOT_PATH='',
                  JARVIS_MEDIA_CATALOG='1', JARVIS_BINARY_ARTIFACTS='0', JARVIS_TESTING='1')
cache = home / 'media' / 'cache'
cache.mkdir(parents=True)
artifact = cache / 'fixture.pdf'
artifact.write_bytes(b'%PDF-1.7\nsmall document\n%%EOF')
rows = [{'id': f'md-{i:012x}', 'kind': 'image', 'created_at': i,
         'prompt': 'oldest browser needle' if i == 0 else f'recent fixture {i}',
         'path': str(artifact)} for i in range(220)]
(home / 'media' / 'catalog.json').write_text(json.dumps(rows))

import uvicorn

from agents import web

uvicorn.run(web.app, host='127.0.0.1', port=45138, lifespan='off', log_level='error')
