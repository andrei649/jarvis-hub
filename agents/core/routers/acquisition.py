"""H32.6 governed capability-acquisition status, audit, and lifecycle controls."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field

from agents.core.acquisition.package_store import PackageStoreError
from agents.core.acquisition.promotion import PromotionError
from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["acquisition"])


class AcquisitionPurgeBody(BaseModel):
    model_config = {"extra": "forbid"}

    confirm: str = Field(..., min_length=1, max_length=64)


def _get_runtime():
    orch = get_orch()
    return getattr(orch, "acquisition", None) if orch is not None else None


def _unavailable():
    return nocache_json(
        {"status": "refused", "reason": "acquisition_unavailable"},
        status_code=409,
    )


@router.get("/api/acquisition/status", dependencies=[Depends(user_guard)])
async def acquisition_status():
    runtime = _get_runtime()
    if runtime is None:
        return nocache_json(
            {
                "enabled": False,
                "status": "unavailable",
                "reason": "acquisition_runtime_unavailable",
                "states": {},
                "reuse": {
                    "reused": 0,
                    "generated": 0,
                    "blocked": 0,
                    "abandoned": 0,
                    "reuse_rate": 0.0,
                },
                "packages": [],
                "audit": {
                    "status": "unavailable",
                    "events": 0,
                    "summarized_events": 0,
                    "chain_valid": False,
                },
            }
        )
    return nocache_json(runtime.status_snapshot())


@router.get("/api/acquisition/events", dependencies=[Depends(user_guard)])
async def acquisition_events(
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
):
    runtime = _get_runtime()
    if runtime is None:
        return nocache_json(
            {"enabled": False, "status": "unavailable", "events": []}
        )
    snapshot = runtime.status_snapshot()
    return nocache_json(
        {
            "enabled": bool(snapshot.get("enabled")),
            "status": str(snapshot.get("status", "unavailable")),
            "events": runtime.list_audit_events(limit=limit),
        }
    )


@router.get("/api/acquisition/ledger/export", dependencies=[Depends(admin_guard)])
async def acquisition_export():
    runtime = _get_runtime()
    if runtime is None:
        return _unavailable()
    return nocache_json(runtime.export_audit())


@router.post("/api/acquisition/ledger/purge", dependencies=[Depends(admin_guard)])
async def acquisition_purge(body: AcquisitionPurgeBody):
    if body.confirm != "PURGE ACQUISITION DETAIL":
        return nocache_json(
            {"status": "refused", "reason": "exact_owner_confirmation_required"},
            status_code=409,
        )
    runtime = _get_runtime()
    if runtime is None:
        return _unavailable()
    result = runtime.purge_audit(actor="owner")
    return nocache_json({"status": "purged", **result})


_SkillName = Annotated[
    str,
    Path(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$"),
]


@router.post("/api/acquisition/{name}/revoke", dependencies=[Depends(admin_guard)])
async def acquisition_revoke(name: _SkillName):
    runtime = _get_runtime()
    if runtime is None:
        return _unavailable()
    try:
        return nocache_json(await runtime.revoke(name))
    except (PromotionError, PackageStoreError, KeyError, ValueError):
        return nocache_json(
            {"status": "refused", "reason": "revocation_refused"},
            status_code=409,
        )


@router.post("/api/acquisition/{name}/rollback", dependencies=[Depends(admin_guard)])
async def acquisition_rollback(name: _SkillName):
    runtime = _get_runtime()
    if runtime is None:
        return _unavailable()
    try:
        return nocache_json(await runtime.rollback(name))
    except (PromotionError, PackageStoreError, KeyError, ValueError):
        return nocache_json(
            {"status": "refused", "reason": "rollback_refused"},
            status_code=409,
        )


__all__ = ["AcquisitionPurgeBody", "router"]
