"""Disposable full Nerva lifespan: controlled default or opt-in physical Ollama children."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from workspace_hub import scrubbed

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]
port = int(sys.argv[1]) if len(sys.argv) > 1 else 45178
model = os.environ.get("NERVA_FINISH_PARALLEL_MODEL", "").strip()
if not 1024 < port < 65536 or port == 8080:
    raise SystemExit("unsafe fixture port")
if model and (any(char.isspace() for char in model) or ":cloud" in model.lower()):
    raise SystemExit("NERVA_FINISH_PARALLEL_MODEL must name an installed physical Ollama model")
TEST_HOME = tempfile.TemporaryDirectory(prefix="nerva-parallel-hud-")
home = Path(TEST_HOME.name).resolve()
(home / "tmp").mkdir()
(home / "vault").mkdir()
clean = scrubbed(dict(os.environ))
for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    clean.pop(name, None)
os.environ.clear()
os.environ.update(clean)
os.environ.update(
    HOME=str(home),
    USERPROFILE=str(home),
    JARVIS_HOME=str(home),
    JARVIS_USER_HOME=str(home),
    TEMP=str(home / "tmp"),
    TMP=str(home / "tmp"),
    JARVIS_KEY_DIR=str(home / "keys"),
    JARVIS_OS_VAULT_PATH=str(home / "vault"),
    JARVIS_PORT=str(port),
    JARVIS_ROOT_PATH="",
    JARVIS_USER_TOKEN="parallel-hud-user-fixture",
    JARVIS_ADMIN_TOKEN="parallel-hud-admin-fixture",
    JARVIS_TESTING="1",
    PYTHON_DOTENV_DISABLED="1",
    JARVIS_LLM_WARMUP="0",
    JARVIS_OLLAMA_URL="http://127.0.0.1:11434" if model else "http://127.0.0.1:9",
    JARVIS_LM_STUDIO_URL="http://127.0.0.1:9",
    JARVIS_STRICT_LOCAL="1",
    JARVIS_OS_REPOSITORY_DOCS="0",
    JARVIS_MCP_AUTOCONNECT="0",
    NERVA_WORKSPACE_SCHEDULER="0",
    MEMORY_EMBED_TURNS="0",
    NO_PROXY="127.0.0.1,localhost,::1",
)

if model:
    def loopback_only(event: str, args: tuple) -> None:
        if event == "socket.getaddrinfo" and args[0] not in {"127.0.0.1", "localhost", "::1", None}:
            raise PermissionError("fixture permits loopback only")
        if event == "socket.bind":
            address = args[1]
            if isinstance(address, tuple) and not (
                address[0] in {"127.0.0.1", "::1"} and address[1] == 0
                or address == ("127.0.0.1", port)
            ):
                raise PermissionError("fixture may bind only its listener")
        if event == "socket.connect":
            address = args[1]
            if (isinstance(address, tuple)
                    and sys._getframe(1).f_code is socket._fallback_socketpair.__code__
                    and address[0] in {"127.0.0.1", "::1"} and address[1] != 8080):
                return
            if isinstance(address, tuple) and address not in {
                ("127.0.0.1", port), ("127.0.0.1", 11434),
            }:
                raise PermissionError("fixture may contact only itself and physical Ollama")

    sys.addaudithook(loopback_only)
    # This is metadata only: reject Ollama aliases forwarding to remote hosts.
    request = Request("http://127.0.0.1:11434/api/show",
                      data=json.dumps({"model": model}).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=8) as response:
            raw = response.read(512 * 1024 + 1)
        shown = json.loads(raw) if len(raw) <= 512 * 1024 else {}
        if (not isinstance(shown, dict) or shown.get("remote_model") or shown.get("remote_host")
                or not isinstance(shown.get("model_info"), dict) or not shown["model_info"]):
            raise ValueError("remote or unverified model")
    except (OSError, ValueError) as exc:
        raise SystemExit("physical Ollama model could not be verified") from exc

import uvicorn
from fastapi import Depends

from agents import web
from agents.core import agent, paths, settings_db

if model:
    agent.soul_path_for = lambda ident: ROOT / "agents" / str(ident) / "SOUL.md"
    agent.identity_path = lambda: ROOT / "agents" / "_identity" / "IDENTITY.md"
    if not agent.soul_path_for("jarvis").is_file() or not agent.identity_path().is_file():
        raise SystemExit("public agent templates unavailable")
    if paths.data_root().resolve() != home or settings_db.DB_PATH.parent.resolve() != home:
        raise SystemExit("hub data path escaped fixture")
    settings_db.init_db(force=True)
    settings_db.put_category("llm", {"backend_type": "ollama", "default_model": model,
                                    "cloud_fallback": "never", "tool_loop_enabled": False})
    settings_db.put_category("autonomy", {"subagent_model": model, "subagent_provider": "ollama"})

release_b = asyncio.Event()
physical_generations: list[dict[str, str]] = []


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
        assert web.orch is not None
        assert web.orch.subagents is not None
        assert web.orch.autonomy_queue is not None
        if model:
            from agents.core.llm.base import OllamaBackend
            from agents.core.subagents import current_spawn_id

            if web.orch.subagents.max_concurrent < 2:
                raise RuntimeError("product profile allows fewer than two sub-agent slots")
            router = web.orch.llm_router
            router.set_active_model(model)
            if (not router._local_available or router._cloud_available or router._claude_available
                    or router._backend_name != "ollama" or router.ollama_url != "http://127.0.0.1:11434"):
                raise RuntimeError("fixture requires the physical local Ollama route only")
            seen = set()
            for backend in (router._backend, router._ollama_backend):
                if not isinstance(backend, OllamaBackend):
                    raise RuntimeError("unexpected model backend")
                if id(backend) in seen:
                    continue
                seen.add(id(backend))

                async def record_generation(response):
                    req = response.request
                    if (req.method == "POST" and req.url.host == "127.0.0.1"
                            and req.url.port == 11434 and req.url.path in {"/api/generate", "/api/chat"}
                            and response.status_code == 200):
                        spawn_id = current_spawn_id()
                        if spawn_id:
                            physical_generations.append({"spawn_id": spawn_id,
                                                         "model": json.loads(req.content)["model"]})

                backend.client.event_hooks["response"].append(record_generation)
        else:
            # Admission gates, defaults, queue wiring, and shutdown stay native.
            web.orch.subagents._runner = controlled_child
        yield state


web.app.router.lifespan_context = controlled_lifespan


@web.app.post("/__test/release-b", dependencies=[Depends(web._admin_guard)])
async def release_second_child():
    if model:
        raise RuntimeError("controlled release unavailable in physical lane")
    release_b.set()
    return {"ok": True}


@web.app.get("/__test/physical-generations", dependencies=[Depends(web._admin_guard)])
async def physical_generation_count():
    return {"models": physical_generations}


if __name__ == "__main__":
    try:
        uvicorn.run(web.app, host="127.0.0.1", port=port, log_level="error")
    finally:
        TEST_HOME.cleanup()
