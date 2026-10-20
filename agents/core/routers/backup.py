"""Backup / restore-drill endpoints (roadmap 0.14 · H23.8) — `/api/admin/backup`.

Operator-facing, **admin-guarded**: snapshot the data root, list snapshots, and
run a restore-drill (integrity-check a snapshot's DBs without touching live
data). An in-place *restore* (H010) is never applied by a request: `POST
/api/admin/backup/restore` only queues a `backup.restore` card at the approval
queue's irreversible tier (tier 3, `agents/core/autonomy/irreversible.py`). A human's
accept stages it and asks the hub to restart; serve.py applies it at the next boot
before any store opens. A backup name is resolved by matching the trusted backups
listing, so no request value reaches a path expression.

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
    """List local backup snapshots (newest first), a staged restore and the last one applied."""
    return nocache_json({"backups": _backup.list_backups(),
                         "pending_restore": _backup.pending_restore(),
                         "last_restore": _backup.last_restore()})


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


@router.post("/api/admin/backup/restore", dependencies=[Depends(admin_guard)])
async def backup_restore(req: Request):
    """Ask to restore a snapshot over the live data root. Body: {name}.

    Answers 202 ``{"pending": task id}``: the restore waits for a human in the decision
    inbox at the irreversible tier (``nerva approvals accept <id>``); a card for the same
    archive already waiting is answered instead. 503 when no approval queue can take it
    — nothing is ever restored on this request alone.
    """
    from agents.core.autonomy import irreversible

    try:
        body = await req.json()
    except Exception:
        body = {}
    name = (body or {}).get("name") if isinstance(body, dict) else None
    if not isinstance(name, str) or not name:
        return JSONResponse({"error": "name is required (see GET /api/admin/backup)"}, status_code=400)
    try:
        request = await asyncio.to_thread(_backup.restore_request, name)
    except FileNotFoundError:
        return JSONResponse({"error": "backup not found"}, status_code=404)
    except (OSError, ValueError) as e:
        logger.warning("backup restore request failed: %s", e)
        return JSONResponse({"error": "the backup could not be drilled"}, status_code=422)
    if not request["preview"]["verify"]["ok"]:
        return JSONResponse({"error": "the backup failed its restore drill",
                             "verify": request["preview"]["verify"]}, status_code=422)
    orch = get_orch()
    for task in await asyncio.to_thread(irreversible.pending, orch, _backup.APPROVAL_KIND):
        if (getattr(task, "payload", None) or {}).get("name") == request["payload"]["name"]:
            return nocache_json({"pending": int(task.id), "existing": True}, status_code=202)
    queued = irreversible.enqueue(orch, _backup.APPROVAL_KIND, **request)
    if "pending" not in queued:
        return JSONResponse({"error": "restore needs the approval queue",
                             "reason": queued.get("refused")}, status_code=503)
    return nocache_json(queued, status_code=202)


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
    # AUDIT-2c: the API's equivalent of the CLI's --no-backup. The route used to hardcode
    # backup_first=True, so a user who wanted deletion could not get deletion through the
    # product — the one path that matters for someone handing the box back. Still defaults
    # to True: an accidental forget with no way back is the worse failure.
    backup_first = (body or {}).get("backup_first", True)
    if not isinstance(backup_first, bool):
        return JSONResponse(
            {"error": "backup_first must be true or false"}, status_code=400,
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
        backup_first=backup_first,
        memory=True,
        session_count=len(session_ids),
    )
    if denied is not None:
        return JSONResponse({"error": f"contract denied: {denied}"}, status_code=403)
    live_cleared: list[str] = []
    live_failed: list[str] = []
    if orch is not None:
        live_cleared, live_failed = await _purge.clear_live_memory(orch)
    try:
        # Backs up then deletes across the data root — blocking file/DB I/O.
        result = await asyncio.to_thread(
            _purge.purge_data, backup_first=backup_first, memory=True,
            session_ids=session_ids
        )
    except (OSError, ValueError, _purge.PurgeError) as e:
        logger.warning("forget purge failed: %s", e)
        return JSONResponse({"error": "forget failed"}, status_code=500)
    # AUDIT-2: never report an unqualified success over data that survived. A wipe that
    # could not reach Qdrant or Neo4j used to be logged and dropped, so the response said
    # ok:true while every embedding was still on disk — an F5 (a claimed completed action
    # that did not complete) on the one operation where the user cannot check for
    # themselves. `ok` now reflects the whole forget, not just the file half.
    result["live_stores_cleared"] = live_cleared
    # MERGE, don't overwrite. `purge_data` already puts the files its sweep could not
    # erase into `not_erased` (and sets ok:false). This line used to assign
    # `live_failed` straight over that, so a run where the FILE sweep failed but the
    # live stores cleared cleanly reported `ok: false` with an empty `not_erased`
    # and no warning — the user was told something survived but not what, on the one
    # operation where they cannot go and check for themselves. That is the same
    # defect the comment above this block was written about, one line further down.
    file_failed = list(result.get("not_erased") or [])
    not_erased = file_failed + [s for s in live_failed if s not in file_failed]
    result["not_erased"] = not_erased
    if not_erased:
        result["ok"] = False
        parts = []
        if file_failed:
            parts.append("files the sweep could not erase")
        if live_failed:
            parts.append("live stores that could not be cleared")
        result["warning"] = (
            "SOME DATA WAS NOT ERASED — see not_erased (" + " and ".join(parts) + "). "
            "The listed items still hold your content."
        )
        logger.error("forget completed with surviving data: %s", not_erased)
    return nocache_json(result)
