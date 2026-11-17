"""Agent-to-Agent (A2A) endpoints (H16.2) — extracted from web.py (CLN-3).

Opt-in, allowlisted, approval-gated. The public routes (agent-card, inbound task)
authenticate by peer HMAC, not a user token; management routes are admin-gated.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from agents.core.routers._deps import admin_guard

from agents.core.web_helpers import nocache_json


router = APIRouter(tags=["a2a"])

_a2a_registry = None


def _get_a2a_registry():
    global _a2a_registry
    if _a2a_registry is None:
        from agents.core.a2a import get_registry
        _a2a_registry = get_registry()
    return _a2a_registry


def _secret_broker():
    from agents.core.app_state import get_orch

    orch = get_orch()
    return getattr(orch, "secret_broker", None) if orch is not None else None


class A2APeerBody(BaseModel):
    peer_id: str = Field(..., max_length=128)
    name: str = Field("", max_length=128)


class A2ACardBody(BaseModel):
    name: str = Field("jarvis", max_length=128)
    capabilities: list[str] = Field(default_factory=list)


class A2ADecisionBody(BaseModel):
    approve: bool


class A2APeerPolicyBody(BaseModel):
    """The owner's switches for a peer (H563): suspend it without revoking its credential,
    and how many tasks it may send in one conversation (1-20)."""
    model_config = ConfigDict(extra="forbid", strict=True)
    allowed: Optional[bool] = None
    turn_cap: Optional[int] = Field(None, ge=1, le=20)


async def _audit(action: str, preview: str) -> None:
    """One line in the signed, hash-chained audit log per A2A exchange (H563). Never the
    task's text: the peer, the task id, the outcome and the size only."""
    import logging
    import time

    from agents.core.app_state import get_orch

    orch = get_orch()
    audit_log = getattr(orch, "audit", None) if orch is not None else None
    if audit_log is None:
        return
    from agents.core.security.types import SecurityEvent, SecurityEventType

    try:
        await asyncio.to_thread(audit_log.log, SecurityEvent(
            event_type=SecurityEventType.AUDIT_LOG, timestamp=time.time(),
            content_preview=preview[:500], action_taken=action))
    except Exception:  # noqa: BLE001 - the exchange already happened; say so in the log
        logging.getLogger("jarvis.a2a").warning("an A2A audit line could not be written (%s)", action)


class A2AOutboundBody(BaseModel):
    """Where and how this hub calls a peer (G14). The token is stored in the secret store."""
    url: str = Field(..., max_length=2048)
    token: Optional[str] = Field(None, max_length=4096)
    keep_token: bool = False
    allow_lan: bool = False
    timeout: int = Field(60, ge=5, le=90)
    capabilities: list[str] = Field(default_factory=list, max_length=20)
    tenant: str = Field("", max_length=128)


@router.get("/.well-known/agent-card")
async def a2a_agent_card():
    """Public: our advertised, signed Agent Card — only when A2A is enabled."""
    from agents.core.a2a import a2a_enabled
    if not a2a_enabled():
        return nocache_json({"error": "a2a disabled"}, status_code=404)
    return nocache_json(_get_a2a_registry().agent_card())


@router.post("/api/a2a/task")
async def a2a_receive_task(request: Request):
    """Inbound peer task. Authenticated by the peer's HMAC signature (not a user
    token); off unless enabled; verified tasks land in the inbox for approval."""
    from agents.core.a2a import a2a_enabled
    if not a2a_enabled():
        return nocache_json({"error": "a2a disabled"}, status_code=404)
    from agents.core import idempotency

    refusal = idempotency.check_header(request)
    if refusal is not None:
        return refusal
    peer_id = request.headers.get("x-a2a-peer", "")
    signature = request.headers.get("x-signature-256", "")
    raw = await request.body()
    registry = _get_a2a_registry()
    # H659: a peer's retry of a task it already sent returns the first receipt, and no
    # second inbox row. The key is reserved only for an authenticated peer, in its scope.
    started = idempotency.Begin()
    if registry.verify_peer(peer_id, raw, signature):
        started = await asyncio.to_thread(idempotency.begin, request, f"a2a:{peer_id}", raw)
        if started.refusal is not None:
            return started.refusal
        if started.replay is not None:
            return idempotency.replayed(started.replay.ref or {})
    try:
        receipt = registry.receive_task(peer_id, raw, signature)
    except PermissionError as exc:
        if started.claim is not None:
            started.claim.release()
        status = getattr(exc, "status", None)
        if status in (403, 429):
            # An authenticated peer refused by the owner's policy (H563 A2ARefused): it
            # may know why, and the refusal is audited.
            reason = str(getattr(exc, "reason", "refused"))
            await _audit("a2a_inbound_refused", f"peer={peer_id} reason={reason} bytes={len(raw)}")
            response = nocache_json({"error": reason}, status_code=status)
            if status == 429:
                response.headers["Retry-After"] = "60"
            return response
        # Unknown peer or bad signature — fail closed without leaking which.
        return nocache_json({"error": "rejected"}, status_code=401)
    except ValueError:
        if started.claim is not None:
            started.claim.release()
        return nocache_json({"error": "invalid task body"}, status_code=400)
    except BaseException:
        if started.claim is not None:
            started.claim.release()
        raise
    if started.claim is not None:
        await asyncio.to_thread(started.claim.done, {k: receipt.get(k) for k in ("id", "status", "accepted")})
    await _audit("a2a_inbound", f"peer={peer_id} task={receipt.get('id')} status=pending bytes={len(raw)}")
    return nocache_json(receipt)


@router.get("/api/a2a/peers", dependencies=[Depends(admin_guard)])
async def a2a_list_peers():
    return nocache_json({"peers": _get_a2a_registry().list_peers()})


@router.post("/api/a2a/peers", dependencies=[Depends(admin_guard)])
async def a2a_add_peer(body: A2APeerBody):
    """Allowlist a peer; the shared secret is returned ONCE."""
    try:
        return nocache_json(_get_a2a_registry().add_peer(body.peer_id, name=body.name))
    except ValueError:
        return nocache_json({"error": "peer_id is required"}, status_code=400)


@router.delete("/api/a2a/peers/{peer_id}", dependencies=[Depends(admin_guard)])
async def a2a_remove_peer(peer_id: str):
    ok = _get_a2a_registry().remove_peer(peer_id, secret_broker=_secret_broker())
    return nocache_json({"ok": ok}, status_code=200 if ok else 404)


@router.post("/api/a2a/peers/{peer_id}/policy", dependencies=[Depends(admin_guard)])
async def a2a_set_peer_policy(peer_id: str, body: A2APeerPolicyBody):
    """Suspend or allow an authenticated peer, and set its per-conversation turn cap (H563)."""
    try:
        result = _get_a2a_registry().set_peer_policy(peer_id, allowed=body.allowed, turn_cap=body.turn_cap)
    except KeyError:
        return nocache_json({"error": "unknown peer"}, status_code=404)
    except ValueError:
        return nocache_json({"error": "invalid_turn_cap"}, status_code=400)
    await _audit("a2a_peer_policy", f"peer={peer_id} allowed={result['allowed']} turn_cap={result['turn_cap']}")
    return nocache_json(result)


@router.put("/api/a2a/peers/{peer_id}/outbound", dependencies=[Depends(admin_guard)])
async def a2a_set_peer_outbound(peer_id: str, body: A2AOutboundBody):
    """Let this hub call the peer (G14): URL, optional bearer token, LAN opt-in, tags.

    A LAN address is refused unless ``allow_lan`` is set, and then only as a private IP
    literal or ``localhost``; an internet peer must use https. The token is never echoed."""
    try:
        result = _get_a2a_registry().set_outbound(
            peer_id, body.url, token=body.token or None, keep_token=body.keep_token,
            allow_lan=body.allow_lan, timeout=body.timeout, capabilities=body.capabilities,
            tenant=body.tenant, secret_broker=_secret_broker())
    except KeyError:
        return nocache_json({"error": "unknown peer"}, status_code=404)
    except ValueError as exc:
        reason = str(exc) if str(exc).replace("_", "").isalnum() else "invalid"
        status = 503 if reason == "secret_store_unavailable" else 400
        return nocache_json({"error": reason}, status_code=status)
    return nocache_json(result)


@router.delete("/api/a2a/peers/{peer_id}/outbound", dependencies=[Depends(admin_guard)])
async def a2a_clear_peer_outbound(peer_id: str):
    ok = _get_a2a_registry().clear_outbound(peer_id, secret_broker=_secret_broker())
    return nocache_json({"ok": ok}, status_code=200 if ok else 404)


@router.post("/api/a2a/card", dependencies=[Depends(admin_guard)])
async def a2a_set_card(body: A2ACardBody):
    return nocache_json(_get_a2a_registry().set_card(body.name, body.capabilities))


@router.get("/api/a2a/inbox", dependencies=[Depends(admin_guard)])
async def a2a_inbox(status: Optional[str] = None):
    return nocache_json({"inbox": _get_a2a_registry().list_inbox(status)})


@router.post("/api/a2a/inbox/{task_id}/decide", dependencies=[Depends(admin_guard)])
async def a2a_decide(task_id: str, body: A2ADecisionBody):
    """Approve or reject a pending inbound task. Approval does NOT execute it."""
    try:
        decided = _get_a2a_registry().decide(task_id, body.approve)
    except ValueError:
        return nocache_json({"error": "task not found or already decided"}, status_code=404)
    await _audit("a2a_inbound_decided", f"peer={decided.get('peer_id')} task={task_id} status={decided.get('status')}")
    return nocache_json(decided)
