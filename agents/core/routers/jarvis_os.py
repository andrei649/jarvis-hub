"""ANDREI OS interface on the hub: the `/os` page and its `/api/os/*` vault routes.

The interface itself is the standalone app in `apps/jarvis-os/` (3D knowledge galaxy,
workshop, HUD). Served from the hub it keeps its look and its vault graph, but not its
own backend: chat goes through the hub's `/chat` (orchestrator, guards, approval gates)
and speech through `/tts`. This router only adds what the hub did not have:

- `GET /os`, `GET /os/{path}` — the page shell and its static assets. Markup and bytes
  only, so they are open like the other HUD shells. The shell is marked with
  `<meta name="jarvis-os-hub">`, which is how the page knows to call the hub.
- `GET /api/os/status|brain|brain/note|brain/retrieve`, `POST /api/os/brain/capture` —
  the Obsidian vault graph, behind `user_guard` because they read and write personal
  notes.

The vault indexer is not copied here: it is loaded from `apps/jarvis-os/server.py`, so
the standalone app and the hub build the same graph from one implementation. That
file's own `config.json` (provider API keys) is never read on this path.
"""

from __future__ import annotations

import asyncio
import html
import importlib.util
import logging
import mimetypes
import re
import threading
from pathlib import Path
from types import ModuleType

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from agents.core.env_config import env_flag, env_str
from agents.core.paths import app_root
from agents.core.routers._deps import user_guard
from agents.core.web_base_path import normalize_root_path
from agents.core.web_helpers import error_json, nocache_json

logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["jarvis-os"])

#: Where a deployment can point the galaxy at a vault other than the auto-detected one.
VAULT_ENV = "JARVIS_OS_VAULT_PATH"
#: Index vault files that have more than one hard link (off by default; see vault_fs).
HARDLINKS_ENV = "JARVIS_OS_ALLOW_HARDLINKS"
#: How much vault text one chat turn may carry as attachments.
_ATTACHMENT_CHARS = 1500
_ATTACHMENT_COUNT = 4
#: Third-party hosts the hub's CSP blocks; the shell drops their tags instead of
#: letting every page load log a refused request.
_BLOCKED_LINK = re.compile(r'[ \t]*<link[^>]+https://fonts\.(?:googleapis|gstatic)\.com[^>]*>\r?\n?')

_NOT_INSTALLED = "the ANDREI OS interface (apps/jarvis-os) is not part of this install"

_module: ModuleType | None = None
_module_lock = threading.Lock()


def _app_dir() -> Path:
    return app_root() / "apps" / "jarvis-os"


def _public_dir() -> Path:
    return _app_dir() / "public"


def _engine() -> ModuleType | None:
    """The standalone app's module, loaded once by path (it is not a package)."""
    global _module
    if _module is not None:
        return _module
    source = _app_dir() / "server.py"
    if not source.is_file():
        return None
    with _module_lock:
        if _module is None:
            spec = importlib.util.spec_from_file_location("jarvis_os_standalone", source)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _module = module
    return _module


def _config(engine: ModuleType) -> dict:
    """The vault settings for the hub. Never the standalone `config.json`."""
    vault = env_str(VAULT_ENV).strip() or engine.DEFAULT_VAULT_PATH
    return {
        "vaultMode": "andrei_plus_nerva",
        "vaultPath": str(Path(vault).expanduser()),
        "nervaPath": str(app_root()),
        "allowHardLinks": env_flag(HARDLINKS_ENV),
    }


def _vault_available(cfg: dict) -> bool:
    return Path(cfg["vaultPath"]).is_dir()


# ── page shell + static assets ───────────────────────────────────

def _render_shell(root_path: str) -> str:
    page = (_public_dir() / "index.html").read_text(encoding="utf-8")
    page = _BLOCKED_LINK.sub("", page)
    marker = f'<meta name="jarvis-os-hub" content="{html.escape(root_path, quote=True)}" />'
    return page.replace("<head>", "<head>\n  " + marker, 1)


@router.get("/os", include_in_schema=False)
async def os_redirect(request: Request):
    # The page's assets are relative URLs, so it must be served with the trailing slash.
    return RedirectResponse(normalize_root_path(request.app.root_path) + "/os/", status_code=307)


@router.get("/os/{path:path}", include_in_schema=False)
async def os_asset(request: Request, path: str = ""):
    public = _public_dir().resolve()
    if not (public / "index.html").is_file():
        return HTMLResponse(f"<h1>Not available</h1><p>{html.escape(_NOT_INSTALLED)}.</p>", status_code=503)
    if path in ("", "index.html"):
        shell = _render_shell(normalize_root_path(request.app.root_path))
        return HTMLResponse(shell, headers={"Cache-Control": "no-store"})
    target = (public / path).resolve()
    if not target.is_relative_to(public) or not target.is_file():
        return HTMLResponse("Not found", status_code=404)
    media_type = "text/javascript" if target.suffix == ".js" else mimetypes.guess_type(target.name)[0]
    return FileResponse(str(target), media_type=media_type, headers={"Cache-Control": "no-cache"})


# ── vault routes ─────────────────────────────────────────────────

class CaptureBody(BaseModel):
    title: str = Field("", max_length=200)
    content: str = Field("", max_length=100_000)
    links: list[str] = Field(default_factory=lambda: ["Acasa"], max_length=16)


def _unavailable():
    return nocache_json({"ok": False, "error": _NOT_INSTALLED}, status_code=503)


@router.get("/api/os/status", dependencies=[Depends(user_guard)])
async def os_status():
    engine = _engine()
    if engine is None:
        return _unavailable()
    cfg = _config(engine)
    return nocache_json({
        "ok": True,
        "backend": "hub",
        "activeEngine": "nerva hub",
        "preferredProvider": "auto",
        "vaultMode": cfg["vaultMode"] if _vault_available(cfg) else "demo_550",
        "vaultPath": cfg["vaultPath"],
        "nervaPath": cfg["nervaPath"],
        "vaultAvailable": _vault_available(cfg),
        "vaultEnv": VAULT_ENV,
    })


@router.get("/api/os/brain", dependencies=[Depends(user_guard)])
async def os_brain(reindex: int = 0):
    engine = _engine()
    if engine is None:
        return _unavailable()
    cfg = _config(engine)
    if not _vault_available(cfg):
        # Same answer the standalone app gives: the page falls back to its demo galaxy.
        return nocache_json({"ok": True, "mode": "demo_550", "brandTitle": "ANDREI OS",
                             "reason": "no vault found", "vaultEnv": VAULT_ENV})
    if reindex:
        engine.invalidate_brain_cache()
    return nocache_json(await asyncio.to_thread(engine.build_real_brain_graph, cfg))


@router.get("/api/os/brain/note", dependencies=[Depends(user_guard)])
async def os_brain_note(relPath: str = ""):  # noqa: N803 — the page's query name
    engine = _engine()
    if engine is None:
        return _unavailable()
    # An allowlist, not a path check: only Markdown the graph itself indexed is served
    # (never config.json, .env or a *.local.md), read without following any link.
    try:
        title, tags, body, wikilinks = await asyncio.to_thread(
            engine.read_indexed_note, _config(engine), relPath)
    except (OSError, ValueError) as exc:
        return error_json(exc, 404, "note not found", extra={"ok": False})
    return nocache_json({"ok": True, "title": title, "tags": tags, "body": body[:6000], "wikilinks": wikilinks})


@router.get("/api/os/brain/retrieve", dependencies=[Depends(user_guard)])
async def os_brain_retrieve(q: str = ""):
    """The vault notes that match a question, shaped as `/chat` attachments.

    The page sends them beside the owner's message, so the orchestrator receives vault
    text as fenced content and never as the owner's own words. `focus` is the title the
    galaxy should fly to, and only when the best match is named in the question.
    """
    engine = _engine()
    if engine is None:
        return _unavailable()
    cfg = _config(engine)
    query = q.strip()[:4096]
    if not query or not _vault_available(cfg):
        return nocache_json({"ok": True, "attachments": [], "focus": None})
    _text, nodes = await asyncio.to_thread(engine.retrieve_vault_context, query, cfg, _ATTACHMENT_COUNT)
    attachments = [
        {"name": str(node.get("relPath") or node.get("title") or "note")[:200],
         "text": str(node.get("body") or "")[:_ATTACHMENT_CHARS]}
        for node in nodes if str(node.get("body") or "").strip()
    ]
    focus = None
    if nodes:
        title = str(nodes[0].get("title") or "")
        words = re.findall(r"[\wăâîșț]{3,}", engine.nfc(query).lower())
        if title and any(word in title.lower() for word in words):
            focus = title
    return nocache_json({"ok": True, "attachments": attachments, "focus": focus})


@router.post("/api/os/brain/capture", dependencies=[Depends(user_guard)])
async def os_brain_capture(body: CaptureBody):
    """Write a new note into the vault's `08 Inbox/`."""
    engine = _engine()
    if engine is None:
        return _unavailable()
    cfg = _config(engine)
    if not _vault_available(cfg):
        return nocache_json({"ok": False, "error": "no vault found to capture into"}, status_code=409)
    if not body.title.strip() and not body.content.strip():
        return nocache_json({"ok": False, "error": "a title or content is required"}, status_code=422)
    try:
        result = await asyncio.to_thread(engine.capture_inbox_note, cfg, body.title, body.content, body.links)
    except engine.vault_fs.UnsafePath as exc:
        # The inbox (or a folder above it) is a link out of the vault, or this platform
        # has no handle-relative create. Refused; nothing was written anywhere.
        return error_json(exc, 409, "the vault inbox is not a plain folder inside the vault; "
                                    "capture is refused", extra={"ok": False})
    except OSError as exc:
        return error_json(exc, 500, "could not write the note", extra={"ok": False})
    return nocache_json(result)
