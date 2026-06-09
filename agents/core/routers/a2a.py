"""Agent-to-Agent (A2A) endpoints (H16.2) — extracted from web.py (CLN-3).

Opt-in, allowlisted, approval-gated. The public routes (agent-card, inbound task)
authenticate by peer HMAC, not a user token; management routes are admin-gated.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from agents.core.routers._deps import admin_guard

router = APIRouter(tags=["a2a"])

_a2a_registry = None


def _get_a2a_registry():
    global _a2a_registry
    if _a2a_registry is None:
        from agents.core.a2a import A2ARegistry
        _a2a_registry = A2ARegistry()
    return _a2a_registry


class A2APeerBody(BaseModel):
    peer_id: str = Field(..., max_length=128)
    name: str = Field("", max_length=128)


class A2ACardBody(BaseModel):
    name: str = Field("jarvis", max_length=128)
    capabilities: list[str] = Field(default_factory=list)


class A2ADecisionBody(BaseModel):
    approve: bool


@router.get("/.well-known/agent-card")
async def a2a_agent_card():
    """Public: our advertised, signed Agent Card — only when A2A is enabled."""
    from agents import web
    from agents.core.a2a import a2a_enabled
    if not a2a_enabled():
        return web._nocache_json({"error": "a2a disabled"}, status_code=404)
    return web._nocache_json(_get_a2a_registry().agent_card())


@router.post("/api/a2a/task")
async def a2a_receive_task(request: Request):
    """Inbound peer task. Authenticated by the peer's HMAC signature (not a user
    token); off unless enabled; verified tasks land in the inbox for approval."""
    from agents import web
    from agents.core.a2a import a2a_enabled
    if not a2a_enabled():
        return web._nocache_json({"error": "a2a disabled"}, status_code=404)
    peer_id = request.headers.get("x-a2a-peer", "")
    signature = request.headers.get("x-signature-256", "")
    raw = await request.body()
    try:
        receipt = _get_a2a_registry().receive_task(peer_id, raw, signature)
        return web._nocache_json(receipt)
    except PermissionError:
        # Unknown peer or bad signature — fail closed without leaking which.
        return web._nocache_json({"error": "rejected"}, status_code=401)
    except ValueError:
        return web._nocache_json({"error": "invalid task body"}, status_code=400)


@router.get("/api/a2a/peers", dependencies=[Depends(admin_guard)])
async def a2a_list_peers():
    from agents import web
    return web._nocache_json({"peers": _get_a2a_registry().list_peers()})


@router.post("/api/a2a/peers", dependencies=[Depends(admin_guard)])
async def a2a_add_peer(body: A2APeerBody):
    """Allowlist a peer; the shared secret is returned ONCE."""
    from agents import web
    try:
        return web._nocache_json(_get_a2a_registry().add_peer(body.peer_id, name=body.name))
    except ValueError:
        return web._nocache_json({"error": "peer_id is required"}, status_code=400)


@router.delete("/api/a2a/peers/{peer_id}", dependencies=[Depends(admin_guard)])
async def a2a_remove_peer(peer_id: str):
    from agents import web
    ok = _get_a2a_registry().remove_peer(peer_id)
    return web._nocache_json({"ok": ok}, status_code=200 if ok else 404)


@router.post("/api/a2a/card", dependencies=[Depends(admin_guard)])
async def a2a_set_card(body: A2ACardBody):
    from agents import web
    return web._nocache_json(_get_a2a_registry().set_card(body.name, body.capabilities))


@router.get("/api/a2a/inbox", dependencies=[Depends(admin_guard)])
async def a2a_inbox(status: Optional[str] = None):
    from agents import web
    return web._nocache_json({"inbox": _get_a2a_registry().list_inbox(status)})


@router.post("/api/a2a/inbox/{task_id}/decide", dependencies=[Depends(admin_guard)])
async def a2a_decide(task_id: str, body: A2ADecisionBody):
    """Approve or reject a pending inbound task. Approval does NOT execute it."""
    from agents import web
    try:
        return web._nocache_json(_get_a2a_registry().decide(task_id, body.approve))
    except ValueError:
        return web._nocache_json({"error": "task not found or already decided"}, status_code=404)
