"""Chat Channels / Rooms endpoints (H10.20) — extracted from web.py (CLN-3)."""

import logging

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse

from agents.core.routers._deps import user_guard
from agents.core.routers._component import require_component

from agents.core.web_helpers import nocache_json, logsafe
from agents.core.app_state import get_orch

logger = logging.getLogger("jarvis.web")


router = APIRouter(tags=["rooms"])


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
    room = store.create(body["name"], (body or {}).get("description", ""),
                        (body or {}).get("agents"), (body or {}).get("default_agent", "jarvis"))
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
    store.add_message(room_id, "user", text)
    prompt = store.context_for(room_id) + text
    try:
        reply = await orch.handle_input(prompt, channel="room",
                                        agent_override=target if target != "jarvis" else None)
    except Exception as e:
        # CWE-209: log the full detail server-side, never echo the raw exception
        # text (it can carry internal paths / stack info) back to the client.
        logger.warning("room handle_input failed (room=%s, agent=%s): %s",
                       logsafe(room_id), logsafe(target), logsafe(e))
        reply = "[error: the agent could not process this message]"
    store.add_message(room_id, "assistant", reply, agent=target)
    return nocache_json({"reply": reply, "agent": target,
                         "mentioned": store.parse_mentions(text)})
