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
import sys
import threading
import uuid
from pathlib import Path
from types import ModuleType
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agents.core import estop, workshop_edit
from agents.core.app_state import get_orch
from agents.core.env_config import env_flag, env_str
from agents.core.paths import app_root, data_root
from agents.core.routers._deps import direct_local_owner, user_guard
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
_workshop_edit_lock = asyncio.Lock()


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
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            _module = module
    return _module


def _config(engine: ModuleType) -> dict:
    """The vault settings for the hub. Never the standalone `config.json`."""
    vault = env_str(VAULT_ENV).strip() or engine.DEFAULT_VAULT_PATH
    return {
        "vaultMode": "andrei_plus_nerva" if env_flag("JARVIS_OS_REPOSITORY_DOCS", True) else "andrei_os",
        "vaultPath": str(Path(vault).expanduser()),
        "vaultInclude": env_str("JARVIS_OS_VAULT_INCLUDE"),
        "vaultExclude": env_str("JARVIS_OS_VAULT_EXCLUDE"),
        "vaultInbox": env_str("JARVIS_OS_INBOX_SUBDIR") or env_str("JARVIS_OS_VAULT_INBOX", engine.INBOX_FOLDER),
        "vaultInboxConfigured": bool(env_str("JARVIS_OS_INBOX_SUBDIR") or env_str("JARVIS_OS_VAULT_INBOX")),
        "indexDb": env_str("JARVIS_OS_INDEX_DB") or str(data_root() / "vault_os_index.sqlite"),
        "vaultMapPath": env_str("JARVIS_OS_VAULT_MAP_PATH"),
        "vaultMapSchema": env_str("JARVIS_OS_VAULT_MAP_SCHEMA"),
        "maskVaultPath": env_flag("JARVIS_OS_MASK_VAULT_PATH"),
        "buildSourceDirs": tuple(s.strip() for s in env_str("NERVA_VAULT_BUILD_SOURCE_DIRS").split(";") if s.strip()),
        "projectIndex": env_flag("JARVIS_OS_PROJECT_INDEX"),
        "projectIndexPath": env_str("JARVIS_OS_PROJECT_INDEX_PATH") or engine.vault_projects.INDEX_PATH,
        "projectRegisterDir": env_str("JARVIS_OS_PROJECT_REGISTER_DIR") or engine.vault_projects.REGISTER_DIR,
        "projectIndexSchema": env_str("JARVIS_OS_PROJECT_INDEX_SCHEMA") or engine.vault_projects.SCHEMA,
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
    links: list[str] = Field(default_factory=list, max_length=16)


class ChatNoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targetId: str = Field(strict=True, pattern=r"^v1-[0-9a-f]{64}$", min_length=67, max_length=67)
    requestId: str = Field(strict=True, max_length=64)
    title: str = Field(strict=True, min_length=1, max_length=120)
    content: str = Field(strict=True, min_length=1, max_length=100_000)

    @field_validator("requestId")
    @classmethod
    def valid_request_id(cls, value: str) -> str:
        try:
            parsed = uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("requestId must be a UUID") from exc
        return str(parsed)

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("title must be valid Unicode") from exc
        return value

    @field_validator("content")
    @classmethod
    def nonblank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("content must be valid Unicode") from exc
        return value


class ChatNoteSource(BaseModel):
    vault: str
    file: str
    readable: bool


class ChatNoteReceipt(BaseModel):
    ok: Literal[True]
    relPath: str
    source: ChatNoteSource | None


def _unavailable():
    return nocache_json({"ok": False, "error": _NOT_INSTALLED}, status_code=503)


@router.get("/api/os/status", dependencies=[Depends(user_guard)])
async def os_status():
    from agents.core.memory import second_brain
    engine = _engine()
    if engine is None:
        return _unavailable()
    cfg = _config(engine)
    capture_target = await asyncio.to_thread(engine.chat_note_target, cfg)
    available = _vault_available(cfg)
    indexed, copilot = await asyncio.gather(
        asyncio.to_thread(engine.sync_vault_index, cfg) if available else asyncio.sleep(0, result={}),
        asyncio.to_thread(second_brain.health),
    )
    mask = env_flag("JARVIS_OS_MASK_VAULT_PATH")
    return nocache_json({
        "ok": True,
        "backend": "hub",
        "activeEngine": "nerva hub",
        "preferredProvider": "auto",
        "vaultMode": cfg["vaultMode"] if _vault_available(cfg) else "demo_550",
        "vaultPath": Path(cfg["vaultPath"]).name if mask else cfg["vaultPath"],
        "indexedNotes": indexed.get("indexedNotes", 0),
        "excludedZones": indexed.get("excludedZones", 0),
        "skippedHardlinks": indexed.get("skippedHardlinks", 0),
        "lastIndexedAt": indexed.get("lastIndexedAt"),
        "copilotConnected": copilot["connected"],
        "indexReady": available and indexed.get("ok") is True,
        "inboxFolder": engine.configured_inbox(cfg),
        "captureTarget": capture_target,
        "captureUnavailableReason": None if capture_target else "Configure an existing allowed vault inbox, then refresh.",
        "nervaPath": Path(cfg["nervaPath"]).name if mask else cfg["nervaPath"],
        "vaultAvailable": available,
        "vaultEnv": VAULT_ENV,
    })


@router.post("/api/os/brain/reindex", dependencies=[Depends(user_guard)])
async def os_reindex():
    """Reconcile on-disk changes using the same safe index as chat and the graph."""
    engine = _engine()
    if engine is None:
        return _unavailable()
    cfg = _config(engine)
    if not _vault_available(cfg):
        return nocache_json({"ok": False, "error": "vault unavailable"}, status_code=409)
    stats = await asyncio.to_thread(engine.sync_vault_index, cfg)
    if stats.get("ok") is not True:
        return nocache_json({"ok": False, "error": "index unavailable"}, status_code=503)
    return nocache_json({"ok": True, "indexedNotes": stats["indexedNotes"], "lastIndexedAt": stats["lastIndexedAt"]})


@router.get("/api/os/brain", dependencies=[Depends(user_guard)])
async def os_brain(request: Request, reindex: int = 0):
    engine = _engine()
    if engine is None:
        return _unavailable()
    cfg = _config(engine)
    if not _vault_available(cfg):
        # Same answer the standalone app gives: the page falls back to its demo galaxy.
        return nocache_json({"ok": True, "mode": "demo_550", "brandTitle": "ANDREI OS",
                             "reason": "no vault found", "vaultEnv": VAULT_ENV})
    cfg["localProjectMetadata"] = direct_local_owner(request)
    if reindex:
        engine.invalidate_brain_cache()
    return nocache_json(await asyncio.to_thread(engine.build_real_brain_graph, cfg))


@router.get("/api/os/brain/note", dependencies=[Depends(user_guard)])
async def os_brain_note(request: Request, relPath: str = "",  # noqa: N803 — the page's query names
                        targetId: Annotated[str | None, Query(pattern=r"^v1-[0-9a-f]{64}$", max_length=67)] = None,
                        q: str = "", local_only: bool = False):
    engine = _engine()
    if engine is None:
        return _unavailable()
    # An allowlist, not a path check: only Markdown the graph itself indexed is served
    # (never config.json, .env or a *.local.md), read without following any link.
    if local_only and (not direct_local_owner(request) or targetId is not None):
        return nocache_json({"ok": False, "error": "direct local reader required"}, status_code=403)
    try:
        title, tags, body, wikilinks = await asyncio.to_thread(
            engine.read_indexed_note, _config(engine), relPath, target_id=targetId,
            **({"local_only": True} if local_only else {}))
    except (OSError, ValueError) as exc:
        return error_json(exc, 404, "note not found", extra={"ok": False})
    if targetId is not None:
        if len(body) > 100_000:
            return nocache_json({"ok": False, "error": "Note exceeds the chat reader limit."}, status_code=413)
        return nocache_json({"ok": True, "targetId": targetId, "relPath": relPath, "body": body})
    start = 0
    query = q.strip()[:4096]
    if query and len(body) > 6000:
        excerpt = await asyncio.to_thread(engine.vault_search.passage, body, query, engine.SYNONYM_EXPANSIONS)
        start = body.index(excerpt)
    return nocache_json({"ok": True, "title": title, "tags": tags, "body": body[start:start + 6000],
                         "wikilinks": wikilinks, **({"start": start} if start else {})})


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
    attachments = []
    sources = {}
    source_names = set()
    ambiguous_names = set()
    for node in nodes:
        excerpt = str(node.get("excerpt", node.get("body")) or "")[:_ATTACHMENT_CHARS]
        if not excerpt.strip():
            continue
        name = str(node.get("relPath") or node.get("title") or "note")[:200]
        attachments.append({"name": name, "text": excerpt})
        if name in source_names:
            ambiguous_names.add(name)
            sources.pop(name, None)
        else:
            source_names.add(name)
        if node.get("obsidianSource") and name not in ambiguous_names:
            sources[name] = node["obsidianSource"]
    focus = None
    if nodes:
        title = str(nodes[0].get("title") or "")
        words = re.findall(r"[\wăâîșț]{3,}", engine.nfc(query).lower())
        if title and set(words).intersection(re.findall(r"[\wăâîșț]{3,}", engine.nfc(title).lower())):
            focus = title
    return nocache_json({"ok": True, "attachments": attachments, "sources": sources, "focus": focus})


@router.post("/api/os/brain/capture", dependencies=[Depends(user_guard)])
async def os_brain_capture(body: CaptureBody):
    """Write a new note into the configured vault inbox."""
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
        return error_json(exc, 409, "the vault inbox must be an allowed, plain folder inside the vault",
                          extra={"ok": False})
    except OSError as exc:
        return error_json(exc, 500, "could not write the note", extra={"ok": False})
    return nocache_json(result)


@router.post("/api/os/brain/chat-note", dependencies=[Depends(user_guard)], response_model=ChatNoteReceipt)
async def os_brain_chat_note(body: ChatNoteBody):
    engine = _engine()
    if engine is None:
        return _unavailable()
    try:
        result = await asyncio.to_thread(engine.save_chat_note, _config(engine), body.targetId,
                                         body.requestId, body.title, body.content)
    except engine.ChatNoteConflict as exc:
        message = ("A note with this title already exists; choose a different title and try again."
                   if exc.code == "title_conflict" else "saved note changed or request ID conflicts")
        return nocache_json({"ok": False, "code": exc.code, "error": message}, status_code=409)
    except (engine.vault_fs.UnsafePath, FileNotFoundError):
        return nocache_json({"ok": False, "error": "capture target changed or note conflicts"}, status_code=409)
    except OSError as exc:
        return error_json(exc, 500, "could not write the note", extra={"ok": False})
    return nocache_json(result)


class WorkshopEditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view: Literal["robot", "house"]
    instruction: str = Field(min_length=1, max_length=1000)

    @field_validator("instruction")
    @classmethod
    def nonblank_instruction(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("instruction must not be blank")
        return value


@router.post("/api/os/workshop/edit", dependencies=[Depends(user_guard)])
async def os_workshop_edit(body: WorkshopEditBody):
    """Turn one instruction into bounded parameters; the browser applies them."""
    if estop.is_engaged():
        return nocache_json({"ok": False, "error": "workshop edit unavailable"}, status_code=503)
    if _workshop_edit_lock.locked():
        return nocache_json({"ok": False, "error": "workshop edit busy"}, status_code=429)
    orchestrator = get_orch()
    llm_router = getattr(orchestrator, "llm_router", None)
    if llm_router is None:
        return nocache_json({"ok": False, "error": "local model unavailable"}, status_code=503)
    async with _workshop_edit_lock:
        if estop.is_engaged():
            return nocache_json({"ok": False, "error": "workshop edit unavailable"}, status_code=503)
        try:
            params = await asyncio.wait_for(
                workshop_edit.propose(llm_router, body.view, body.instruction), timeout=20.0)
        except workshop_edit.InvalidEdit:
            return nocache_json({"ok": False, "error": "unsupported workshop edit"}, status_code=422)
        except Exception:
            logger.warning("Local workshop edit unavailable")
            return nocache_json({"ok": False, "error": "local model unavailable"}, status_code=503)
        if estop.is_engaged():
            return nocache_json({"ok": False, "error": "workshop edit unavailable"}, status_code=503)
    return nocache_json({"ok": True, "params": params})


class WorkshopProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    project: dict


@router.get("/api/os/workshop/projects", dependencies=[Depends(user_guard)])
async def os_workshop_projects():
    engine = _engine()
    if engine is None:
        return _unavailable()
    try:
        projects = await asyncio.to_thread(engine.workshop_projects.list_projects, engine, _config(engine))
    except (OSError, ValueError):
        return nocache_json({"ok": False, "error": "workshop projects unavailable"}, status_code=422)
    return nocache_json({"ok": True, "projects": projects})


@router.get("/api/os/workshop/project", dependencies=[Depends(user_guard)])
async def os_workshop_project(path: str = ""):
    engine = _engine()
    if engine is None:
        return _unavailable()
    try:
        result = await asyncio.to_thread(engine.workshop_projects.get_project, engine, _config(engine), path)
    except FileNotFoundError:
        return nocache_json({"ok": False, "error": "workshop project not found"}, status_code=404)
    except (OSError, ValueError):
        return nocache_json({"ok": False, "error": "workshop project unavailable or corrupt"}, status_code=422)
    return nocache_json({"ok": True, **result})


@router.post("/api/os/workshop/projects", dependencies=[Depends(user_guard)])
async def os_workshop_project_save(body: WorkshopProjectBody):
    engine = _engine()
    if engine is None:
        return _unavailable()
    cfg = _config(engine)
    if not _vault_available(cfg):
        return nocache_json({"ok": False, "error": "no vault found to save into"}, status_code=409)
    try:
        result = await asyncio.to_thread(engine.workshop_projects.save_project, engine, cfg,
                                         body.title, body.project)
    except engine.workshop_projects.SavedProjectUnavailable as exc:
        return nocache_json({"ok": False, "error": "project saved but could not be reopened", "path": exc.path},
                            status_code=500)
    except engine.vault_fs.UnsafePath:
        return nocache_json({"ok": False, "error": "vault inbox unavailable"}, status_code=409)
    except (OSError, ValueError):
        return nocache_json({"ok": False, "error": "invalid or unavailable workshop project"}, status_code=422)
    return nocache_json({"ok": True, **result})
