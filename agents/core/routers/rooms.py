"""Chat Channels / Rooms endpoints (H10.20 + H657 failover/fencing) — extracted from web.py."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.core.app_state import get_orch
from agents.core.rooms import RoomAuthorityError
from agents.core.routers._component import require_component
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import logsafe, nocache_json

logger = logging.getLogger("jarvis.web")


router = APIRouter(tags=["rooms"])


class RoomReplicateBody(BaseModel):
    page: dict[str, Any] | None = None
    room_id: str | None = None
    room_meta: dict[str, Any] | None = None
    authority_epoch: int | None = None
    authority_host: str | None = None
    after_seq: int = 0
    entries: list[dict[str, Any]] | None = None


class RoomPromoteBody(BaseModel):
    confirm: bool = False
    new_host: str = Field("", max_length=80)
    reason: str = Field("", max_length=300)


class RoomDemoteBody(BaseModel):
    proof: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/rooms", dependencies=[Depends(user_guard)])
async def rooms_list():
    orch = get_orch()
    store = getattr(orch, "rooms", None) if orch else None
    return nocache_json({"rooms": store.list() if store else []})


@router.post("/api/rooms", dependencies=[Depends(user_guard)])
async def rooms_create(req: Request):
    _, store, err = require_component("rooms", "rooms not available")
    if err is not None:
        return err
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not (body or {}).get("name"):
        return JSONResponse({"error": "name required"}, status_code=400)
    room = store.create(
        body["name"],
        (body or {}).get("description", ""),
        (body or {}).get("agents"),
        (body or {}).get("default_agent", "jarvis"),
    )
    return nocache_json({"ok": True, "room": room})


@router.get("/api/rooms/{room_id}", dependencies=[Depends(user_guard)])
async def rooms_get(room_id: str):
    orch = get_orch()
    store = getattr(orch, "rooms", None) if orch else None
    room = store.get(room_id) if store else None
    if room is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json(room)


@router.delete("/api/rooms/{room_id}", dependencies=[Depends(user_guard)])
async def rooms_delete(room_id: str):
    orch = get_orch()
    store = getattr(orch, "rooms", None) if orch else None
    if store is None or not store.delete(room_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"ok": True, "deleted": room_id})


@router.get("/api/rooms/{room_id}/history", dependencies=[Depends(user_guard)])
async def rooms_history(room_id: str, limit: int = Query(50, ge=1, le=200)):
    orch = get_orch()
    store = getattr(orch, "rooms", None) if orch else None
    if store is None or store.get(room_id) is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json({"history": store.history(room_id, limit)})


@router.get("/api/rooms/{room_id}/replica-state", dependencies=[Depends(user_guard)])
async def rooms_replica_state(room_id: str):
    """H657 — inspect authority epoch, role, log cursor, fencing state, and lineage."""
    _, store, err = require_component("rooms", "rooms not available")
    if err is not None:
        return err
    state = store.replica_state(room_id)
    if state is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json(state)


@router.get("/api/rooms/{room_id}/log-page", dependencies=[Depends(user_guard)])
async def rooms_log_page(
    room_id: str,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """H657 — export a verbatim hash-chained page of room log events for standby replicas."""
    _, store, err = require_component("rooms", "rooms not available")
    if err is not None:
        return err
    page = store.export_log_page(room_id, after_seq=after_seq, limit=limit)
    if page is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json(page)


@router.post("/api/rooms/{room_id}/replicate", dependencies=[Depends(admin_guard)])
async def rooms_replicate(room_id: str, body: RoomReplicateBody):
    """H657 — ingest a verbatim room log page onto a standby replica (idempotent, gap/epoch-safe)."""
    _, store, err = require_component("rooms", "rooms not available")
    if err is not None:
        return err
    page = body.page if isinstance(body.page, dict) else body.model_dump(exclude={"page"}, exclude_none=True)
    try:
        result = store.replicate(room_id, page)
    except RoomAuthorityError as exc:
        return nocache_json(
            {"ok": False, "error": exc.reason, "detail": exc.detail},
            status_code=exc.status,
        )
    return nocache_json(result)


@router.post("/api/rooms/{room_id}/promote", dependencies=[Depends(admin_guard)])
async def rooms_promote(room_id: str, body: RoomPromoteBody):
    """H657 — promote a surviving replica host to owner at ``epoch + 1`` (explicit confirm)."""
    _, store, err = require_component("rooms", "rooms not available")
    if err is not None:
        return err
    try:
        result = store.promote(
            room_id,
            confirm=body.confirm,
            new_host=body.new_host or None,
            reason=body.reason,
        )
    except RoomAuthorityError as exc:
        return nocache_json(
            {"ok": False, "error": exc.reason, "detail": exc.detail},
            status_code=exc.status,
        )
    if result is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json(result)


@router.post("/api/rooms/{room_id}/demote", dependencies=[Depends(admin_guard)])
async def rooms_demote(room_id: str, body: RoomDemoteBody):
    """H657 — fence and demote an old host upon proof of a newer authority epoch."""
    _, store, err = require_component("rooms", "rooms not available")
    if err is not None:
        return err
    try:
        result = store.demote(room_id, proof=body.proof)
    except RoomAuthorityError as exc:
        return nocache_json(
            {"ok": False, "error": exc.reason, "detail": exc.detail},
            status_code=exc.status,
        )
    if result is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json(result)


@router.post("/api/rooms/{room_id}/message", dependencies=[Depends(user_guard)])
async def rooms_message(room_id: str, req: Request):
    """Post a message to a room; @mention routes to a specific agent."""
    orch, store, err = require_component("rooms", "rooms not available")
    if err is not None:
        return err
    room = store.get(room_id)
    if room is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = (body or {}).get("message", "")
    if not text:
        return JSONResponse({"error": "message required"}, status_code=400)
    target = store.route(room_id, text)
    if target != "jarvis" and target not in (getattr(orch, "agents", None) or {}):
        # H202: a retired (or unknown) agent does not answer: the hub routes the message as
        # it routes one for Jarvis, so the reply is never stored or shown as that agent's.
        target = "jarvis"
    try:
        store.add_message(room_id, "user", text)
    except RoomAuthorityError as exc:
        return nocache_json(
            {"ok": False, "error": exc.reason, "detail": exc.detail},
            status_code=exc.status,
        )
    prompt = store.context_for(room_id) + text
    try:
        reply = await orch.handle_input(
            prompt,
            channel="room",
            agent_override=target if target != "jarvis" else None,
        )
    except Exception as e:
        # CWE-209: log the full detail server-side, never echo the raw exception
        # text (it can carry internal paths / stack info) back to the client.
        logger.warning(
            "room handle_input failed (room=%s, agent=%s): %s",
            logsafe(room_id),
            logsafe(target),
            logsafe(e),
        )
        reply = "[error: the agent could not process this message]"
    try:
        store.add_message(room_id, "assistant", reply, agent=target)
    except RoomAuthorityError as exc:
        return nocache_json(
            {"ok": False, "error": exc.reason, "detail": exc.detail},
            status_code=exc.status,
        )
    return nocache_json(
        {"reply": reply, "agent": target, "mentioned": store.parse_mentions(text)}
    )
