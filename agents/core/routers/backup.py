"""Backup / restore-drill endpoints (roadmap 0.14 · H23.8) — `/api/admin/backup`.

Operator-facing, **admin-guarded**: snapshot the data root, list snapshots, and
run a restore-drill (integrity-check a snapshot's DBs without touching live
data). Hot in-place *restore* is intentionally NOT exposed over HTTP — it
overwrites live state and is an operator CLI action (`python -m agents.core.backup
restore <name> <target> --force` with the server stopped). A verify target is
resolved by matching the trusted backups listing, so no request value reaches a
path expression.

Also hosts the destructive sibling `POST /api/admin/forget` (H23.9): a confirm-gated,
backup-first "forget me" purge of the user's structured content at rest.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from agents.core import backup as _backup
from agents.core import data_export as _export
from agents.core import data_purge as _purge
from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import nocache_json

logger = logging.getLogger("jarvis.web")

router = APIRouter(tags=["backup"])


@router.get("/api/admin/backup", dependencies=[Depends(admin_guard)])
async def backup_list():
    """List local backup snapshots (newest first)."""
    return nocache_json({"backups": _backup.list_backups()})


@router.post("/api/admin/backup", dependencies=[Depends(admin_guard)])
async def backup_create(req: Request):
    """Create a consistent snapshot of the data root. Body: {label?}."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    try:
        # tar+gzip (and optional encrypt) of the whole data root — blocking, so
        # offload it like the export sibling below or it freezes the event loop.
        result = await asyncio.to_thread(_backup.create_backup, label=(body or {}).get("label", ""))
    except (OSError, ValueError) as e:
        logger.warning("backup create failed: %s", e)
        return JSONResponse({"error": "backup failed"}, status_code=500)
    return nocache_json({"ok": True, **result})


@router.post("/api/admin/backup/verify", dependencies=[Depends(admin_guard)])
async def backup_verify(req: Request):
    """Restore-drill a snapshot (integrity-check its DBs). Body: {name?} — newest if omitted."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = (body or {}).get("name")
    if not name:
        listing = _backup.list_backups()
        if not listing:
            return JSONResponse({"error": "no backups to verify"}, status_code=404)
        name = listing[0]["name"]
    # Resolve via the trusted listing — the request string never reaches a path.
    path = _backup.resolve_backup(name)
    if path is None:
        return JSONResponse({"error": "backup not found"}, status_code=404)
    try:
        # Extracts the full archive + integrity-checks every DB — blocking.
        report = await asyncio.to_thread(_backup.verify_backup, str(path))
    except (OSError, ValueError) as e:
        logger.warning("backup verify failed: %s", e)
        return JSONResponse({"error": "verify failed"}, status_code=500)
    return nocache_json(report)


@router.post("/api/admin/export", dependencies=[Depends(admin_guard)])
async def export_data(req: Request):
    """Write a portable JSON export of the user's content DBs (H23.9).

    Admin-guarded sibling of backup/forget. The export covers only user-content
    DBs (``data_export.EXPORT_DBS``) — never settings.db/secrets — so it is the
    data-portability counterpart to the destructive forget. The dump does blocking
    SQLite I/O, so it is offloaded off the event loop.
    """
    try:
        result = await asyncio.to_thread(_export.export_data)
    except (OSError, ValueError) as e:
        logger.warning("export failed: %s", e)
        return JSONResponse({"error": "export failed"}, status_code=500)
    return nocache_json({"ok": True, **result})


@router.post("/api/admin/forget", dependencies=[Depends(admin_guard)])
async def forget_data(req: Request):
    """Irreversibly erase the user's content (backup-first). Body: {confirm}.

    Requires an explicit ``{"confirm": "FORGET"}`` body in addition to the admin guard —
    a deliberate, hard-to-fat-finger acknowledgement. A snapshot is taken and verified
    before anything is deleted, so the purge is recoverable from the archive it just made.

    AUD-2: the purge now also clears the memory subsystem at rest (knowledge graph,
    entities, decay, embedding cache, conversation transcripts). Live in-memory stores
    are cleared first so a running orchestrator doesn't re-persist what is deleted.
    """
    try:
        body = await req.json()
    except Exception:
        body = {}
    if (body or {}).get("confirm") != "FORGET":
        return JSONResponse(
            {"error": 'forget requires confirmation — send {"confirm": "FORGET"}'},
            status_code=400,
        )
    # Capture known session ids and clear live memory before the file purge.
    orch = get_orch()
    session_ids: list[str] = []
    if orch is not None:
        conv = getattr(getattr(orch, "memory", None), "conversation", None)
        if conv is not None:
            try:
                session_ids = list(getattr(conv, "sessions", {}).keys())
            except Exception:
                session_ids = []
    denied = _purge.purge_contract_denial(
        source="api.admin.forget",
        backup_first=True,
        memory=True,
        session_count=len(session_ids),
    )
    if denied is not None:
        return JSONResponse({"error": f"contract denied: {denied}"}, status_code=403)
    if orch is not None:
        await _purge.clear_live_memory(orch)
    try:
        # Backs up then deletes across the data root — blocking file/DB I/O.
        result = await asyncio.to_thread(
            _purge.purge_data, backup_first=True, memory=True, session_ids=session_ids
        )
    except (OSError, ValueError, _purge.PurgeError) as e:
        logger.warning("forget purge failed: %s", e)
        return JSONResponse({"error": "forget failed"}, status_code=500)
    return nocache_json(result)
