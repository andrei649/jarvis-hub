"""Code Intelligence (0.31) — read-only symbol search over the project source.

  * `GET  /api/codeintel/stats`             — index roll-ups (files, symbols, by-kind)
  * `GET  /api/codeintel/search?q=&kind=`   — substring search over symbol names
  * `POST /api/codeintel/reindex`           — rebuild the cached index (admin)
  * `/api/codeintel/lsp/*`                   — language servers (H055/H564/H597), below

Returns structure only — symbol names, kinds, relative paths, line numbers, and a
one-line doc — never file contents. The index covers the project's own Python
source, built once and cached.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["codeintel"])


async def search_payload(q: str = "", kind: str = "", limit: int = 50) -> dict:
    """Plain-signature symbol search shared by the HTTP route and the MCP route tool.

    Kept module-level (and free of fastapi `Query` defaults) so the in-process
    route-tool dispatch can reflect its signature and call it with ordinary kwargs.
    """
    from agents.core import codeintel
    # A cold cache walks + parses the whole repo synchronously — keep that off
    # the event loop so other requests keep flowing while it runs.
    idx = await asyncio.to_thread(codeintel.project_index)
    hits = codeintel.search_symbols(idx, q, kind=(kind or None), limit=limit)
    return {"query": q, "kind": kind or None, "count": len(hits), "results": hits}


@router.get("/api/codeintel/stats", dependencies=[Depends(user_guard)])
async def codeintel_stats():
    """Index roll-ups: files indexed, symbol count, counts by kind."""
    from agents.core import codeintel
    # Same cold-build stall as above — offload the blocking walk.
    idx = await asyncio.to_thread(codeintel.project_index)
    return nocache_json({k: idx[k] for k in ("files_indexed", "symbol_count", "by_kind", "errors")})


@router.get("/api/codeintel/search", dependencies=[Depends(user_guard)])
async def codeintel_search(q: str = "", kind: str = "", limit: int = Query(50, ge=1, le=500)):
    """Substring search over symbol names/qualnames; optional `kind` filter."""
    return nocache_json(await search_payload(q, kind, limit))


@router.post("/api/codeintel/reindex", dependencies=[Depends(admin_guard)])
async def codeintel_reindex():
    """Rebuild the cached project index (admin)."""
    from agents.core import codeintel
    # Every reindex re-walks the repo synchronously — offload it (house pattern:
    # routers/admin.py offloads its blocking sqlite audit the same way).
    idx = await asyncio.to_thread(codeintel.reindex)
    return nocache_json({"ok": True, "files_indexed": idx["files_indexed"],
                         "symbol_count": idx["symbol_count"]})


# ── H055/H564/H597: language servers ─────────────────────────────────────────
#
#   * `GET  /api/codeintel/lsp/status`  — known servers, where each was found, running ones,
#                                          the broken set and the isolation in force (user)
#   * `POST /api/codeintel/lsp/install` — queue an `lsp.install` approval card (admin);
#                                          nothing is fetched until a person accepts it
#   * `POST /api/codeintel/lsp/start`   — start a server for a workspace inside the file roots
#   * `POST /api/codeintel/lsp/stop`    — stop running servers (all, one server, one root)

_LSP_STATUS = {"unknown_server": 404, "manual_only": 409, "toolchain_missing": 409,
               "already_pending": 409, "not_installed": 409, "outside_scope": 403,
               "symlink_escape": 403, "secret_path": 403, "bad_path": 422, "not_a_directory": 422,
               "approval_queue_unavailable": 503, "approval_queue_refused": 503, "unknown_kind": 503,
               "sandbox_unavailable": 409, "start_failed": 502, "broken": 409, "lsp_disabled": 409,
               "disabled": 409}


def _lsp_refusal(code: str, detail: str = ""):
    body = {"error": code}
    if detail:
        body["detail"] = detail
    return nocache_json(body, status_code=_LSP_STATUS.get(code, 422))


def _lsp_root(raw: str | None):
    """A workspace root the owner's file scope reaches (the first root by default)."""
    from agents.core.file_tools import FileScope, FileScopeError

    scope = FileScope.from_env()
    if not raw:
        return scope.roots[0], None
    try:
        root = scope.resolve(raw)
    except FileScopeError as exc:
        return None, exc.reason
    if not root.is_dir():
        return None, "not_a_directory"
    return root, None


class LspServerBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    server: StrictStr = Field(min_length=1, max_length=40)


class LspStartBody(LspServerBody):
    root: StrictStr | None = Field(default=None, max_length=4096)


class LspStopBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    server: StrictStr | None = Field(default=None, max_length=40)
    root: StrictStr | None = Field(default=None, max_length=4096)


@router.get("/api/codeintel/lsp/status", dependencies=[Depends(user_guard)])
async def lsp_status():
    """Language servers: known, found (Nerva's tools dir or PATH), running, broken."""
    from agents.core.codeintel.lsp import get_manager

    return nocache_json(await asyncio.to_thread(get_manager().status))


@router.post("/api/codeintel/lsp/install", dependencies=[Depends(admin_guard)])
async def lsp_install(body: LspServerBody):
    """Queue an approval card for a pinned install; nothing is downloaded yet."""
    from agents.core.app_state import get_orch
    from agents.core.codeintel.lsp.install import InstallRefused, request_install

    orch = get_orch()
    if not orch:
        return nocache_json({"error": "hub_not_ready"}, status_code=503)
    try:
        result = await asyncio.to_thread(request_install, orch, body.server)
    except InstallRefused as exc:
        return _lsp_refusal(exc.code, exc.detail)
    return nocache_json({"ok": True, "status": "pending_approval", "task_id": result["pending"],
                         "server": result["server"], "packages": result["packages"]}, status_code=202)


@router.post("/api/codeintel/lsp/start", dependencies=[Depends(admin_guard)])
async def lsp_start(body: LspStartBody):
    """Start (or reuse) a server for a workspace root inside the file scope."""
    from agents.core.codeintel.lsp import enabled, get_manager
    from agents.core.codeintel.lsp.client import LspError

    if not enabled():
        return _lsp_refusal("lsp_disabled")
    root, refused = _lsp_root(body.root)
    if refused:
        return _lsp_refusal(refused)
    try:
        row = await get_manager().start(body.server, root)
    except LspError as exc:
        return _lsp_refusal(exc.reason, exc.detail)
    return nocache_json({"ok": True, "running": row})


@router.post("/api/codeintel/lsp/stop", dependencies=[Depends(admin_guard)])
async def lsp_stop(body: LspStopBody):
    """Stop running servers: every one, one server's, or one root's."""
    from agents.core.codeintel.lsp import get_manager

    root = None
    if body.root:
        root, refused = _lsp_root(body.root)
        if refused:
            return _lsp_refusal(refused)
    stopped = await get_manager().stop(body.server, root)
    return nocache_json({"ok": True, "stopped": stopped})
