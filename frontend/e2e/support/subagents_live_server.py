"""Full Nerva lifespan with a disposable home and controlled child runner only."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from workspace_hub import scrubbed

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]
port = int(sys.argv[1]) if len(sys.argv) > 1 else 45178
TEST_HOME = tempfile.TemporaryDirectory(prefix="nerva-parallel-hud-")
home = Path(TEST_HOME.name).resolve()
clean = scrubbed(dict(os.environ))
os.environ.clear()
os.environ.update(clean)
os.environ.update(
    HOME=str(home),
    USERPROFILE=str(home),
    JARVIS_HOME=str(home),
    JARVIS_USER_HOME=str(home),
    JARVIS_KEY_DIR=str(home / "keys"),
    JARVIS_PORT=str(port),
    JARVIS_ROOT_PATH="",
    JARVIS_USER_TOKEN="parallel-hud-user-fixture",
    JARVIS_ADMIN_TOKEN="parallel-hud-admin-fixture",
    JARVIS_TESTING="1",
    PYTHON_DOTENV_DISABLED="1",
    JARVIS_LLM_WARMUP="0",
    JARVIS_OLLAMA_URL="http://127.0.0.1:9",
    JARVIS_LM_STUDIO_URL="http://127.0.0.1:9",
    JARVIS_MCP_AUTOCONNECT="0",
    NERVA_WORKSPACE_SCHEDULER="0",
    MEMORY_EMBED_TURNS="0",
)

import uvicorn
from fastapi import Depends

from agents import web

release_b = asyncio.Event()


async def controlled_child(task: str, session_id: str, agent: str, **_kwargs) -> dict:
    if task == "check a bicycle tire":
        await release_b.wait()
        return {"output": "B genuine bicycle response"}
    await asyncio.Event().wait()
    raise AssertionError("the first child must be stopped")


original_lifespan = web.app.router.lifespan_context


@asynccontextmanager
async def controlled_lifespan(app):
    async with original_lifespan(app) as state:
        # Admission gates, defaults, queue wiring, and shutdown stay native.
        assert web.orch is not None
        assert web.orch.subagents is not None
        assert web.orch.autonomy_queue is not None
        web.orch.subagents._runner = controlled_child
        yield state


web.app.router.lifespan_context = controlled_lifespan


@web.app.post("/__test/release-b", dependencies=[Depends(web._admin_guard)])
async def release_second_child():
    release_b.set()
    return {"ok": True}


if __name__ == "__main__":
    try:
        uvicorn.run(web.app, host="127.0.0.1", port=port, log_level="error")
    finally:
        TEST_HOME.cleanup()
