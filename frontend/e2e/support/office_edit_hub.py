"""Run the Office acceptance in a fresh profile with one installed Ollama model."""
from __future__ import annotations

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
OLLAMA = "http://127.0.0.1:11434"


def main() -> None:
    port = int(sys.argv[1])
    requested = os.environ["NERVA_OFFICE_MODEL"].strip()
    token = os.environ["NERVA_OFFICE_FIXTURE_TOKEN"]
    if not 1024 < port < 65536 or port in {8080, 11434}:
        raise SystemExit("Choose a separate loopback test port")
    if not requested or any(c.isspace() for c in requested) or ":cloud" in requested.lower():
        raise SystemExit("Choose an installed local Ollama model")

    def loopback_only(event, args):
        if event == "socket.getaddrinfo" and args[0] not in {None, "127.0.0.1", "::1", "localhost"}:
            raise PermissionError("Office fixture permits loopback only")
        if event not in {"socket.bind", "socket.connect"} or not isinstance(args[1], tuple):
            return
        host, target = args[1][:2]
        if host in {"127.0.0.1", "::1"} and target != 8080:
            if target == port or (event == "socket.bind" and target == 0):
                return
            # Windows implements the event loop's socket pair on ephemeral loopback ports.
            socketpair = getattr(socket, "_fallback_socketpair", None)
            if sys._getframe(1).f_code is getattr(socketpair, "__code__", None):
                return
        if event == "socket.connect" and (host, target) == ("127.0.0.1", 11434):
            return
        raise PermissionError("Office fixture permits only its own hub and local Ollama")

    with tempfile.TemporaryDirectory(prefix="nerva-office-", ignore_cleanup_errors=True) as folder:
        home = Path(folder).resolve()
        for part in ("profile", "keys", "user", "tmp", "vault"):
            (home / part).mkdir()
        clean = scrubbed(dict(os.environ))
        for name in list(clean):
            if name.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}:
                del clean[name]
        os.environ.clear()
        os.environ.update(clean)
        os.environ.update(
            HOME=str(home / "user"), USERPROFILE=str(home / "user"), APPDATA=str(home / "user"),
            LOCALAPPDATA=str(home / "user"), XDG_CONFIG_HOME=str(home / "user"),
            TEMP=str(home / "tmp"), TMP=str(home / "tmp"), TMPDIR=str(home / "tmp"),
            JARVIS_HOME=str(home / "profile"), JARVIS_USER_HOME=str(home / "user"),
            JARVIS_KEY_DIR=str(home / "keys"), JARVIS_OS_VAULT_PATH=str(home / "vault"),
            JARVIS_HOST="127.0.0.1", JARVIS_PORT=str(port), JARVIS_ADMIN_TOKEN=token,
            JARVIS_USER_TOKEN=token, JARVIS_TESTING="1", JARVIS_STRICT_LOCAL="1",
            JARVIS_OS_REPOSITORY_DOCS="0", JARVIS_DRIVE_AI_SYNC="0",
            JARVIS_OLLAMA_URL=OLLAMA, JARVIS_LM_STUDIO_URL="http://127.0.0.1:9",
            JARVIS_LLM_WARMUP="0", JARVIS_MCP_AUTOCONNECT="0", NERVA_WORKSPACE_SCHEDULER="0",
            PYTHON_DOTENV_DISABLED="1", MEMORY_EMBED_TURNS="0", NO_PROXY="127.0.0.1,localhost,::1",
        )
        sys.addaudithook(loopback_only)
        sys.path.insert(0, str(ROOT))
        from agents.core.llm.physical_local import ollama_local_selector
        selector = ollama_local_selector(requested)
        req = Request(OLLAMA + "/api/show", data=json.dumps({"model": selector}).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
        with build_opener(ProxyHandler({})).open(req, timeout=8) as metadata:
            raw = metadata.read(512 * 1024 + 1)
        shown = json.loads(raw) if len(raw) <= 512 * 1024 else {}
        if shown.get("remote_model") or shown.get("remote_host") or not shown.get("model_info"):
            raise SystemExit("Ollama did not report installed model weights")

        import uvicorn
        from fastapi import Depends

        from agents import web
        from agents.core import agent, paths, settings_db

        agent.soul_path_for = lambda ident: ROOT / "agents" / str(ident) / "SOUL.md"
        agent.identity_path = lambda: ROOT / "agents" / "_identity" / "IDENTITY.md"
        if paths.data_root().resolve() != home / "profile" or settings_db.DB_PATH.parent.resolve() != home / "profile":
            raise SystemExit("Hub data must stay in the disposable profile")
        settings_db.init_db(force=True)
        settings_db.put_category("llm", {"backend_type": "ollama", "default_model": selector,
                                         "cloud_fallback": "never", "tool_loop_enabled": False})
        settings_db.put_category("memory", {"recall_enabled": False})
        calls: list[str] = []

        async def record(response):
            req = response.request
            if (response.status_code == 200 and req.method == "POST" and
                    req.url.host == "127.0.0.1" and req.url.port == 11434 and
                    req.url.path in {"/api/generate", "/api/chat"} and
                    b"Delivery in May." in req.content and b"Apples" in req.content):
                calls.append(json.loads(req.content)["model"])

        startup = web.app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(app):
            async with startup(app) as state:
                router = web.orch.llm_router
                router.set_active_model(selector)
                if router._backend_name != "ollama" or router._cloud_available or router._claude_available:
                    raise RuntimeError("Office acceptance requires the local Ollama backend")
                router.local_backend.client.event_hooks["response"].append(record)
                yield state

        async def observations():
            return {"requested": requested, "selector": selector, "models": list(calls)}

        web.app.router.lifespan_context = lifespan
        web.app.add_api_route("/__test/office-model", observations, methods=["GET"],
                              dependencies=[Depends(web._admin_guard)], include_in_schema=False)
        uvicorn.run(web.app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
