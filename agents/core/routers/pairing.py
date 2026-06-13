"""Inbound sender pairing / approval endpoints (H12.19) — extracted from web.py (CLN-3)."""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import admin_guard

from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch


router = APIRouter(tags=["pairing"])

_sender_pairing = None


def _get_sender_pairing():
    """Shared registry: prefer the orchestrator's, else a module-level singleton."""
    orch = get_orch()
    if orch is not None and getattr(orch, "sender_pairing", None) is not None:
        return orch.sender_pairing
    global _sender_pairing
    if _sender_pairing is None:
        from agents.core.channels.pairing import SenderPairing
        _sender_pairing = SenderPairing()
    return _sender_pairing


class PairingRequestBody(BaseModel):
    channel: str = Field(..., max_length=64)
    sender_id: str = Field(..., max_length=128)
    code: Optional[str] = Field(None, max_length=128)
    name: str = Field("", max_length=128)


class PairingDecisionBody(BaseModel):
    channel: str = Field(..., max_length=64)
    sender_id: str = Field(..., max_length=128)
    action: str = Field(..., max_length=16)   # approve | reject | block | unpair
    name: str = Field("", max_length=128)


class PairingCodeBody(BaseModel):
    code: Optional[str] = Field(None, max_length=128)


@router.post("/api/channels/pairing/request")
async def pairing_request(body: PairingRequestBody):
    """Inbound first-contact from a sender. Authenticated by the pairing flow
    itself (not a user token); off (404) unless pairing is enabled. Records a
    pending request or auto-pairs on a correct code — never executes anything."""
    from agents.core.channels.pairing import pairing_enabled
    if not pairing_enabled():
        return nocache_json({"error": "pairing disabled"}, status_code=404)
    try:
        result = _get_sender_pairing().request(
            body.channel, body.sender_id, code=body.code, name=body.name)
    except ValueError:
        return nocache_json({"error": "channel and sender_id required"}, status_code=400)
    return nocache_json(result)


@router.get("/api/channels/pairing", dependencies=[Depends(admin_guard)])
async def pairing_list(status: Optional[str] = None):
    reg = _get_sender_pairing()
    return nocache_json({"senders": reg.list_senders(status), "summary": reg.summary()})


@router.post("/api/channels/pairing/decide", dependencies=[Depends(admin_guard)])
async def pairing_decide(body: PairingDecisionBody):
    """Owner decision on a sender: approve / reject / block / unpair."""
    try:
        return nocache_json(_get_sender_pairing().decide(
            body.channel, body.sender_id, body.action, name=body.name))
    except ValueError:
        return nocache_json({"error": "unknown action"}, status_code=400)


@router.post("/api/channels/pairing/code", dependencies=[Depends(admin_guard)])
async def pairing_set_code(body: PairingCodeBody):
    """Set/rotate (or clear) the self-service pairing code."""
    reg = _get_sender_pairing()
    reg.set_code(body.code)
    return nocache_json({"has_code": reg.has_code()})
