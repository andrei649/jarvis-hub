"""Owner-only, review-bound HTTP surface for the 17 skill curator operations."""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator

from agents.core.action_origin import current_action_origin
from agents.core.app_state import get_orch
from agents.core.security.taint import is_untrusted_source
from agents.core.web_helpers import nocache_json

from ._deps import admin_guard

router = APIRouter(prefix="/api/curator", tags=["skill-curator"])

Mutation = Literal[
    "run", "pause", "resume", "pin", "unpin", "adopt", "restore",
    "archive", "prune", "backup", "rollback", "purge",
]
SkillId = Annotated[StrictStr, Field(min_length=1, max_length=128)]
_ALLOWED_ARGS = {
    "run": {"consolidate"}, "pause": set(), "resume": set(),
    "pin": {"name"}, "unpin": {"name"}, "adopt": {"name", "all_unmanaged"},
    "restore": {"archive_id"}, "archive": {"name"}, "prune": {"days"},
    "backup": {"reason"}, "rollback": {"ledger_id", "backup_id"},
    "purge": {"days", "archive_ids"},
}
_REASONS = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")


class CuratorArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: SkillId | None = None
    archive_id: SkillId | None = None
    all_unmanaged: bool = False
    consolidate: bool = False
    days: int | None = Field(default=None, ge=1, le=36_500)
    reason: StrictStr | None = Field(default=None, max_length=280)
    ledger_id: SkillId | None = None
    backup_id: SkillId | None = None
    archive_ids: list[SkillId] = Field(default_factory=list, max_length=128)

    @field_validator("name", "archive_id", "ledger_id", "backup_id")
    @classmethod
    def safe_id(cls, value: str | None) -> str | None:
        if value is not None and (value in {".", ".."} or "/" in value or "\\" in value
                                  or not all(char.isprintable() for char in value)):
            raise ValueError("invalid curator identifier")
        return value

    @field_validator("archive_ids")
    @classmethod
    def safe_archive_ids(cls, values: list[str]) -> list[str]:
        if (len(values) != len(set(values)) or any(
            value in {".", ".."} or "/" in value or "\\" in value
            or not all(char.isprintable() for char in value) for value in values
        )):
            raise ValueError("invalid archive IDs")
        return values

    @field_validator("reason")
    @classmethod
    def safe_reason(cls, value: str | None) -> str | None:
        if value is not None and not all(char.isprintable() for char in value):
            raise ValueError("invalid curator reason")
        return value


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation: Mutation
    args: CuratorArgs = Field(default_factory=CuratorArgs)

    @model_validator(mode="after")
    def operation_args(self):
        values = self.args.model_dump(exclude_defaults=True, exclude_none=True)
        if set(values) - _ALLOWED_ARGS[self.operation]:
            raise ValueError("arguments do not belong to this operation")
        if self.operation in {"pin", "unpin", "archive", "restore"} and not (
            values.get("name") or values.get("archive_id")
        ):
            raise ValueError("one exact skill or archive ID is required")
        if self.operation == "adopt" and bool(values.get("name")) == bool(values.get("all_unmanaged")):
            raise ValueError("choose one skill or all unmanaged skills")
        if self.operation == "rollback" and values.get("ledger_id") and values.get("backup_id"):
            raise ValueError("choose one ledger or backup ID")
        return self

    def operation_args_dict(self) -> dict:
        return self.args.model_dump(exclude_defaults=True, exclude_none=True)


class RequestBody(PreviewBody):
    preview_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


def _component():
    orch = get_orch()
    operations = getattr(orch, "curator_operations", None) if orch else None
    return orch, operations


def _public_reason(value: object) -> str:
    return value if type(value) is str and _REASONS.fullmatch(value) else "curator_unavailable"


def _tainted():
    return is_untrusted_source(current_action_origin())


async def _read(view: str, filters: dict | None = None, *, request: Request):
    if _tainted():
        return nocache_json({"error": "untrusted_origin"}, status_code=403)
    allowed = {
        "status": set(), "usage": {"origin", "sort", "limit"},
        "list-unmanaged": {"limit"}, "list-archived": {"limit"},
        "ledger": {"name", "limit"}, "backups": {"limit"},
    }[view]
    supplied = list(request.query_params)
    if (len(request.query_params.multi_items()) != len(supplied)
            or set(supplied) - allowed):
        return nocache_json({"error": "invalid_curator_filter"}, status_code=422)
    _orch, operations = _component()
    if operations is None:
        return nocache_json({"error": "curator_unavailable"}, status_code=503)
    try:
        result = await asyncio.to_thread(operations.read, view, filters or {})
    except Exception:
        return nocache_json({"error": "curator_unavailable"}, status_code=503)
    if not isinstance(result, dict):
        return nocache_json({"error": "curator_unavailable"}, status_code=503)
    if result.get("ok") is False and result.get("status") == "refused":
        return nocache_json({"ok": False, "status": "refused",
                             "reason": _public_reason(result.get("reason"))}, status_code=503)
    if result.get("ok") is not True:
        return nocache_json({"error": "curator_unavailable"}, status_code=503)
    return nocache_json(result)


@router.get("/status", dependencies=[Depends(admin_guard)])
async def status(request: Request):
    return await _read("status", request=request)


@router.get("/usage", dependencies=[Depends(admin_guard)])
async def usage(request: Request,
                origin: Literal["agent", "import", "bundled", "unknown"] | None = None,
                sort: Literal["activity", "recent", "name"] | None = None,
                limit: int | None = Query(default=None, ge=1, le=200)):
    return await _read("usage", {key: value for key, value in
                                 {"origin": origin, "sort": sort, "limit": limit}.items()
                                 if value is not None}, request=request)


@router.get("/list-unmanaged", dependencies=[Depends(admin_guard)])
async def list_unmanaged(request: Request, limit: int | None = Query(default=None, ge=1, le=200)):
    return await _read("list-unmanaged", {"limit": limit} if limit is not None else {}, request=request)


@router.get("/list-archived", dependencies=[Depends(admin_guard)])
async def list_archived(request: Request, limit: int | None = Query(default=None, ge=1, le=200)):
    return await _read("list-archived", {"limit": limit} if limit is not None else {}, request=request)


@router.get("/ledger", dependencies=[Depends(admin_guard)])
async def ledger(request: Request, name: SkillId | None = None,
                 limit: int | None = Query(default=None, ge=1, le=200)):
    return await _read("ledger", {key: value for key, value in
                                  {"name": name, "limit": limit}.items() if value is not None}, request=request)


@router.get("/backups", dependencies=[Depends(admin_guard)])
async def backups(request: Request, limit: int | None = Query(default=None, ge=1, le=200)):
    return await _read("backups", {"limit": limit} if limit is not None else {}, request=request)


@router.post("/preview", dependencies=[Depends(admin_guard)])
async def preview(body: PreviewBody):
    if _tainted():
        return nocache_json({"error": "untrusted_origin"}, status_code=403)
    _orch, operations = _component()
    if operations is None:
        return nocache_json({"error": "curator_unavailable"}, status_code=503)
    try:
        result = await asyncio.to_thread(operations.preview, body.operation, body.operation_args_dict())
    except Exception:
        return nocache_json({"error": "curator_unavailable"}, status_code=503)
    if not isinstance(result, dict):
        return nocache_json({"error": "curator_unavailable"}, status_code=503)
    if result.get("status") == "refused":
        return nocache_json({"ok": False, "status": "refused",
                             "reason": _public_reason(result.get("reason"))}, status_code=409)
    if result.get("ok") is not True or result.get("status") != "preview":
        return nocache_json({"error": "curator_unavailable"}, status_code=503)
    return nocache_json(result)


@router.post("/request", dependencies=[Depends(admin_guard)])
async def request_operation(body: RequestBody):
    if _tainted():
        return nocache_json({"error": "untrusted_origin"}, status_code=403)
    orch, operations = _component()
    if operations is None:
        return nocache_json({"error": "curator_unavailable"}, status_code=503)
    from agents.core.skills.curator_authority import curator_authorize

    try:
        result = await asyncio.to_thread(
            operations.request, body.operation, body.operation_args_dict(),
            preview_fingerprint=body.preview_fingerprint, actor="owner",
            authorize=curator_authorize(orch),
        )
    except Exception:
        return nocache_json({"error": "curator_unavailable"}, status_code=503)
    if not isinstance(result, dict):
        return nocache_json({"error": "curator_unavailable"}, status_code=503)
    if result.get("status") == "refused":
        return nocache_json({"ok": False, "status": "refused",
                             "reason": _public_reason(result.get("reason"))}, status_code=409)
    if result.get("ok") is not True or result.get("status") != "pending":
        return nocache_json({"error": "curator_unavailable"}, status_code=503)
    return nocache_json(result, status_code=202)
