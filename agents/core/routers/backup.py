"""Backup / restore-drill endpoints (roadmap 0.14 · H23.8) — `/api/admin/backup`.

Operator-facing, **admin-guarded**: snapshot the data root, list snapshots, and
run a restore-drill (integrity-check a snapshot's DBs without touching live
data). Hot in-place *restore* is intentionally NOT exposed over HTTP — it
overwrites live state and is an operator CLI action (`python -m agents.core.backup
restore <name> <target> --force` with the server stopped). A verify target is
resolved by matching the trusted backups listing, so no request value reaches a
path expression.
"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from agents.core import backup as _backup
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
        result = _backup.create_backup(label=(body or {}).get("label", ""))
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
        report = _backup.verify_backup(str(path))
    except (OSError, ValueError) as e:
        logger.warning("backup verify failed: %s", e)
        return JSONResponse({"error": "verify failed"}, status_code=500)
    return nocache_json(report)
