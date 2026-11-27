"""Disposable loopback hub for the packaged ChatGPT plan browser journey.

The account service uses the existing signed synthetic provider fixture. No real
provider socket is opened; only the production HUD and mounted account routes run.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import uvicorn
from starlette.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]
from workspace_hub import scrubbed  # noqa: E402

port = int(sys.argv[1])
if not 1024 <= port <= 65535 or port == 8080:
    sys.exit("chatgpt_plan_hub.py: use a disposable high port other than 8080")
profile = tempfile.TemporaryDirectory(prefix="nerva-chatgpt-plan-browser-")
run = Path(profile.name)
for name in ("home", "keys", "config", "cache", "data", "state", "runtime", "tmp", "vault"):
    (run / name).mkdir()
safe = scrubbed(dict(os.environ))
safe.update({
    "PYTHON_DOTENV_DISABLED": "1",
    "HOME": str(run / "home"), "USERPROFILE": str(run / "home"),
    "APPDATA": str(run / "config"), "LOCALAPPDATA": str(run / "config"),
    "XDG_CONFIG_HOME": str(run / "config"), "XDG_CACHE_HOME": str(run / "cache"),
    "XDG_DATA_HOME": str(run / "data"), "XDG_STATE_HOME": str(run / "state"),
    "XDG_RUNTIME_DIR": str(run / "runtime"),
    "TMP": str(run / "tmp"), "TEMP": str(run / "tmp"), "TMPDIR": str(run / "tmp"),
    "JARVIS_HOME": str(run / "home"), "JARVIS_KEY_DIR": str(run / "keys"),
    "JARVIS_OS_VAULT_PATH": str(run / "vault"), "JARVIS_OS_REPOSITORY_DOCS": "0",
    "JARVIS_ADMIN_TOKEN": "synthetic-plan-owner", "JARVIS_TESTING": "1",
    "JARVIS_SAFE_MODE": "1", "JARVIS_LLM_WARMUP": "0",
    "JARVIS_LM_STUDIO_URL": "http://127.0.0.1:9", "JARVIS_OLLAMA_URL": "http://127.0.0.1:9",
    "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
})
for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
             "HOMEDRIVE", "HOMEPATH"):
    safe.pop(name, None)
os.environ.clear()
os.environ.update(safe)

from agents.core import chatgpt_connection as connection  # noqa: E402
from tests import test_chatgpt_connection as signed_fixture  # noqa: E402

patch = pytest.MonkeyPatch()
signed_fixture.CALLBACK = f"http://127.0.0.1:{port}/api/oauth/chatgpt/callback"
scenario = signed_fixture.provider.__wrapped__(run, patch)
actual_start = connection.start


def capture_start(redirect_uri, binding):
    result = actual_start(redirect_uri, binding)
    scenario.query = parse_qs(urlsplit(result["url"]).query)
    return result


patch.setattr(connection, "start", capture_start)
from agents import web  # noqa: E402
from agents.core.llm.hybrid_router import HybridRouter  # noqa: E402
from agents.core.security.audit import AuditLogger  # noqa: E402

web.ADMIN_TOKEN = os.environ["JARVIS_ADMIN_TOKEN"]
web.USER_TOKEN = ""
web.orch = SimpleNamespace(audit=AuditLogger(str(run / "audit.db")), llm_router=HybridRouter())
generation_requests = []


async def fixture_app(scope, receive, send):
    path = scope["path"]
    method = scope["method"] if scope["type"] == "http" else ""
    if method == "POST" and (path.startswith("/api/chat") or path.startswith("/chat")
                             or path.endswith("/responses") or path.endswith("/chat/completions")):
        generation_requests.append(path)
    if path == "/_test/state":
        return await JSONResponse({"provider_calls": scenario.calls,
                                   "generation_requests": generation_requests})(scope, receive, send)
    if path.startswith(("/v2", "/api/admin/chatgpt-plan", "/api/admin/integrations")) \
            or path == "/api/oauth/chatgpt/callback":
        return await web.app(scope, receive, send)
    return await JSONResponse({})(scope, receive, send)


try:
    uvicorn.run(fixture_app, host="127.0.0.1", port=port, lifespan="off", log_level="error")
finally:
    web.orch.audit.close()
    patch.undo()
    profile.cleanup()
