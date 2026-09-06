"""Permission ledger routes — read the consent ledger, narrow a grant.

``GET /api/permissions`` (user-guarded) is the ledger snapshot: flag state,
grants (active, consumed, revoked, expired, never), the built-in default-deny
list and the recent audit rows. ``POST /api/permissions/{id}/revoke``
(user-guarded) narrows one grant — narrowing needs no approval. There is no
widening route on purpose: a grant is widened only by the owner deciding the
``permission.grant`` task in the decision inbox (``PermissionLedger.request`` →
governed intake → ``apply_grant`` from the approved task's execution).
"""

from __future__ import annotations

import asyncio
import threading

from fastapi import APIRouter, Depends

from agents.core.app_state import get_orch
from agents.core.permission_ledger import PermissionLedger, PermissionRequestError
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["permissions"])

_default: PermissionLedger | None = None
_build_lock = threading.Lock()


def _build_default() -> PermissionLedger:
    global _default
    with _build_lock:
        if _default is None:
            _default = PermissionLedger()
        return _default


async def _get_ledger() -> PermissionLedger:
    """The orchestrator-bound ledger when web.py attached one, else a process-wide
    default at ``data_path('permissions.db')`` (built off the loop, once)."""
    orch = get_orch()
    bound = getattr(orch, "permission_ledger", None) if orch is not None else None
    if isinstance(bound, PermissionLedger):
        return bound
    if _default is not None:
        return _default
    return await asyncio.to_thread(_build_default)


@router.get("/api/permissions", dependencies=[Depends(user_guard)])
async def permissions_snapshot():
    """The consent ledger: grants, default-deny list, audit tail."""
    ledger = await _get_ledger()
    return nocache_json(await asyncio.to_thread(ledger.snapshot))


@router.post("/api/permissions/{grant_id}/revoke", dependencies=[Depends(user_guard)])
async def permissions_revoke(grant_id: str):
    """Narrow one grant. ``never`` rows are immutable (409); unknown ids are 404."""
    ledger = await _get_ledger()
    if len(grant_id) > 64:
        return nocache_json({"ok": False, "reason": "invalid_grant_id"}, status_code=400)
    try:
        grant = await asyncio.to_thread(ledger.revoke, grant_id, by="hud")
    except KeyError:
        return nocache_json({"ok": False, "reason": "unknown_grant"}, status_code=404)
    except PermissionRequestError as exc:
        return nocache_json({"ok": False, "reason": exc.reason}, status_code=409)
    return nocache_json({"ok": True, "grant": grant.as_dict()})
