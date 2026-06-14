"""Data Spaces / per-agent data scope endpoints (H10.26) — extracted from web.py (CLN-3).

Covers the data-space surface only: `/api/memory/profile` (whose scoping uses
data spaces) and the `/api/memory/spaces...` management routes. The rest of
`/api/memory/*` stays in web.py.

The `_data_spaces` singleton + its `_get_data_spaces()` accessor stay in web.py
(CLN-3 unblock B): `tests/test_data_spaces_h10_26.py` does
`monkeypatch.setattr(web, "_data_spaces", ...)`. The handlers read it at REQUEST
time via `_data_spaces_store()`, which resolves `web._get_data_spaces()` through
`sys.modules` — so the monkeypatch is still observed and there is no static
import edge back into `agents.web`.
"""

import sys

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import user_guard, admin_guard

from agents.core.web_helpers import nocache_json


router = APIRouter(tags=["data_spaces"])


def _data_spaces_store():
    web = sys.modules.get("agents.web")
    return web._get_data_spaces()   # web owns the singleton; test patches web._data_spaces


@router.get("/api/memory/profile", dependencies=[Depends(user_guard)])
async def get_memory_profile(agent: Optional[str] = None):
    """Return all stored user facts/preferences grouped by category.

    H10.26: pass ?agent=<id> to apply that agent's data-space scope — only the
    categories the agent is granted are returned (unscoped agent → everything)."""
    from agents.core.memory.store import MemoryStore
    store = MemoryStore()
    profile = await store.get_all()
    if agent:
        profile = _data_spaces_store().filter_categories(profile, agent)
    return profile


# ── H10.26 Data Spaces (per-agent data scope) ─────────────────────


class DefineSpaceBody(BaseModel):
    name: str = Field(..., max_length=128)
    sources: list[str] = Field(default_factory=list)


class AssignSpaceBody(BaseModel):
    agent: str = Field(..., max_length=128)
    space: str = Field(..., max_length=128)


@router.get("/api/memory/spaces", dependencies=[Depends(admin_guard)])
async def list_data_spaces():
    ds = _data_spaces_store()
    return nocache_json({"spaces": ds.list_spaces(), "assignments": ds.list_assignments()})


@router.post("/api/memory/spaces", dependencies=[Depends(admin_guard)])
async def define_data_space(body: DefineSpaceBody):
    try:
        return nocache_json(_data_spaces_store().define_space(body.name, body.sources))
    except ValueError:
        return nocache_json({"error": "space name is required"}, status_code=400)


@router.delete("/api/memory/spaces/{name}", dependencies=[Depends(admin_guard)])
async def delete_data_space(name: str):
    ok = _data_spaces_store().delete_space(name)
    return nocache_json({"ok": ok}, status_code=200 if ok else 404)


@router.post("/api/memory/spaces/assign", dependencies=[Depends(admin_guard)])
async def assign_data_space(body: AssignSpaceBody):
    try:
        return nocache_json(_data_spaces_store().assign(body.agent, body.space))
    except ValueError:
        return nocache_json({"error": "unknown space or missing agent"}, status_code=400)


@router.post("/api/memory/spaces/unassign", dependencies=[Depends(admin_guard)])
async def unassign_data_space(body: AssignSpaceBody):
    return nocache_json(_data_spaces_store().unassign(body.agent, body.space))
