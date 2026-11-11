"""G17 owner event hooks (H163, H021, H514, H408): list, define, switch off/on, remove, test.

Every route is admin-only; every write must also come from this origin as JSON. Defining a
hook (or turning one back on) only queues a ``hooks.define`` approval card at the
irreversible tier; nothing runs until a person accepts it. Switching off and removing only
narrow what runs, so they apply at once. The logic is ``agents/core/hooks/``.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from agents.core.app_state import get_orch
from agents.core.web_helpers import nocache_json

from ._deps import admin_guard

logger = logging.getLogger("jarvis.routers.hooks")

HOOK_ID = r"^hk-[0-9a-f]{10}$"

router = APIRouter(tags=["hooks"])


async def same_origin_write(request: Request) -> None:
    """A hook change must come from this origin and, for a POST, be JSON (which forces the
    browser's CORS pre-check): a page the owner visits cannot define a hook."""
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail="a hook change must come from this origin")
    if request.method == "POST":
        kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if kind != "application/json":
            raise HTTPException(status_code=415, detail="expected application/json")


WRITE_GUARDS = [Depends(admin_guard), Depends(same_origin_write)]

_STATUS = {"not_found": 404, "unknown_event": 422, "invalid_command": 422, "invalid_matcher": 422,
           "matcher_not_supported": 422, "guard_not_blocking": 422, "invalid_timeout": 422,
           "invalid_guard": 422, "invalid_name": 422, "unreadable_file": 422, "too_many_hooks": 409,
           "replacement_pending": 409, "not_disabled": 409, "not_active": 409,
           "admin_credential_required": 409, "store_unavailable": 503, "approval_queue_unavailable": 503,
           "approval_queue_refused": 503, "unknown_kind": 503}


def _refusal(exc) -> object:
    body = {"error": exc.code}
    if exc.detail:
        body["detail"] = exc.detail
    return nocache_json(body, status_code=_STATUS.get(exc.code, 422))


def _unavailable():
    return nocache_json({"error": "not initialized"}, status_code=503)


def _listing() -> dict:
    from agents.core.hooks import runner, store

    rows = store.all_hooks()
    hooks = []
    for row in rows:
        view = store.public(row)
        view["binding_current"] = runner.binding_current(row) if row["status"] != "pending" else None
        view["last_run"] = next(iter(runner.recent_runs(1, hook=row["id"])), None)
        hooks.append(view)
    return {"hooks": hooks, "events": store.catalogue(), "status": runner.status(),
            "runs": runner.recent_runs(50)}


@router.get("/api/hooks", dependencies=[Depends(admin_guard)])
async def hooks_list():
    """The hooks, the event catalogue, whether hooks can run here, and the latest runs."""
    from agents.core.hooks import store

    try:
        return nocache_json(await asyncio.to_thread(_listing))
    except store.HookRefused as exc:
        return _refusal(exc)


class HookBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event: StrictStr = Field(min_length=1, max_length=40)
    argv: list[StrictStr] = Field(min_length=1, max_length=32)
    matcher: StrictStr | None = Field(default=None, max_length=100)
    guard: StrictBool = False
    timeout_s: StrictInt | None = None
    name: StrictStr = Field(default="", max_length=80)
    replaces: StrictStr | None = Field(default=None, pattern=HOOK_ID)


@router.post("/api/hooks", dependencies=WRITE_GUARDS)
async def hooks_define(body: HookBody):
    """Validate a hook and queue its approval card; nothing runs until a person accepts."""
    from agents.core.hooks import runner, store

    orch = get_orch()
    if not orch:
        return _unavailable()
    if not runner.admin_credential_configured():
        return _refusal(store.HookRefused(
            "admin_credential_required",
            "set an admin token first: without one, any local program is trusted as the owner, "
            "so a hook could decide approval cards"))
    try:
        result = await asyncio.to_thread(
            store.request_define, orch, event=body.event, argv=list(body.argv), matcher=body.matcher,
            guard=body.guard, timeout_s=body.timeout_s, name=body.name, replaces=body.replaces)
    except store.HookRefused as exc:
        return _refusal(exc)
    return nocache_json({"ok": True, "status": "pending_approval", "task_id": result["pending"],
                         "hook": result["hook"]}, status_code=202)


@router.post("/api/hooks/{hook_id}/disable", dependencies=WRITE_GUARDS)
async def hooks_disable(hook_id: str = Path(pattern=HOOK_ID)):
    from agents.core.hooks import store

    orch = get_orch()
    if not orch:
        return _unavailable()
    try:
        return nocache_json({"ok": True, **await asyncio.to_thread(store.disable, orch, hook_id)})
    except store.HookRefused as exc:
        return _refusal(exc)


@router.post("/api/hooks/{hook_id}/enable", dependencies=WRITE_GUARDS)
async def hooks_enable(hook_id: str = Path(pattern=HOOK_ID)):
    """Turning a hook back on is an approval card again (the files as they are now)."""
    from agents.core.hooks import store

    orch = get_orch()
    if not orch:
        return _unavailable()
    try:
        result = await asyncio.to_thread(store.request_enable, orch, hook_id)
    except store.HookRefused as exc:
        return _refusal(exc)
    return nocache_json({"ok": True, "status": "pending_approval", "task_id": result["pending"],
                         "hook": result["hook"]}, status_code=202)


@router.delete("/api/hooks/{hook_id}", dependencies=WRITE_GUARDS)
async def hooks_remove(hook_id: str = Path(pattern=HOOK_ID)):
    from agents.core.hooks import store

    orch = get_orch()
    if not orch:
        return _unavailable()
    try:
        return nocache_json({"ok": True, **await asyncio.to_thread(store.remove, orch, hook_id)})
    except store.HookRefused as exc:
        return _refusal(exc)


class HookTestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tool: StrictStr = Field(default="terminal_run", max_length=100)
    tool_input: dict = Field(default_factory=dict)


@router.post("/api/hooks/{hook_id}/test", dependencies=WRITE_GUARDS)
async def hooks_test(body: HookTestBody, hook_id: str = Path(pattern=HOOK_ID)):
    """Run one active hook once against a synthetic event, through the same gates, payload
    builder and evaluation as a live run (audited as a test). Its output is shown masked."""
    from agents.core.hooks import runner, store

    orch = get_orch()
    if not orch:
        return _unavailable()
    row = await asyncio.to_thread(store.get, hook_id)
    if row is None:
        return _refusal(store.HookRefused("not_found"))
    if row["status"] != "active":
        return _refusal(store.HookRefused("not_active", "only an approved, switched-on hook runs"))
    fields = synthetic_fields(row["event"], body.tool, body.tool_input)
    run = await runner.run_hook(row, row["event"], fields, orch=orch, test=True)
    return nocache_json({"ok": True, "run": run})


def synthetic_fields(event: str, tool: str, tool_input: dict) -> dict:
    samples = {
        "tool.before": {"tool_name": tool, "tool_input": tool_input, "agent_id": "jarvis",
                        "session_id": "hook-test"},
        "tool.after": {"tool_name": tool, "status": "ok"},
        "message.received": {"channel": "web", "session_id": "hook-test", "chars": 42},
        "turn.completed": {"channel": "web", "session_id": "hook-test", "status": "ok", "duration_ms": 1200},
        "session.started": {"session_id": "hook-test"},
        "session.ended": {"session_id": "hook-test"},
        "command.completed": {"command": "status", "status": "ok"},
        "approval.requested": {"request_id": "hook-test", "surface": "smart", "command": "ls",
                               "description": "list a folder"},
        "approval.decided": {"request_id": "hook-test", "surface": "smart", "command": "ls",
                             "description": "list a folder", "choice": "smart_approve", "decided_by": "aux_llm"},
    }
    return dict(samples.get(event, {}))
