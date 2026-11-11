"""Remote room members (H658) — owner routes and the peer transport.

Owner routes (admin-only) run both roles: on the **target** hub they invite a member
into a room (an approval card on this hub's queue), reveal the one-time bundle after
approval, change a member's execution policy and revoke a member; on the **member
host** they redeem a bundle, call through a link, renew and leave.

Peer routes (``/api/room-peers/peer/*``) are the cross-machine transport. They take no
hub token: each request is authenticated by an Ed25519 signature against a key pinned
at accept time and, after accept, by the ``Authorization: NervaRoom <grant>`` scheme
(HMAC-signed by this hub). Unauthenticated failures answer a bare ``401 rejected``.
Every response to an authenticated peer request is signed by this hub over the request
nonce, status and body; an unauthenticated refusal is not signed (this hub never signs a
nonce a stranger chose). A body over the limit is refused on its Content-Length before
it is read, and on its streamed size otherwise.
All of it answers 404 while ``JARVIS_ROOM_PEERS`` is off.
"""

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["room-peers"])


def _service(request: Request):
    svc = getattr(request.app.state, "room_peers", None)
    if svc is not None:
        return svc
    orch = get_orch()
    return getattr(orch, "room_peers", None) if orch else None


def _unavailable():
    return nocache_json({"error": "room peers unavailable"}, status_code=503)


def _refusal(exc):
    return nocache_json({"ok": False, "reason": exc.reason}, status_code=exc.status)


def _disabled():
    return nocache_json({"error": "room peers disabled"}, status_code=404)


class InviteBody(BaseModel):
    room_id: str = Field(..., max_length=64)
    member_id: str = Field(..., max_length=40)
    tools: list[str] = Field(..., max_length=32)
    permissions: list[str] = Field(default_factory=lambda: ["dispatch", "status"], max_length=4)
    max_calls_per_hour: int = Field(60, ge=1, le=10_000)
    target_url: str = Field(..., max_length=2048)


class PolicyBody(BaseModel):
    tools: list[str] = Field(..., max_length=32)
    permissions: list[str] = Field(default_factory=lambda: ["dispatch", "status"], max_length=4)
    max_calls_per_hour: int = Field(60, ge=1, le=10_000)


class JoinBody(BaseModel):
    bundle: str = Field(..., max_length=8192)
    label: str = Field("", max_length=80)


class LinkCallBody(BaseModel):
    op: str = Field("dispatch", pattern="^(dispatch|status)$")
    tool: str = Field("", max_length=80)
    args: dict = Field(default_factory=dict)
    task_id: int | None = None


@router.get("/api/room-peers", dependencies=[Depends(admin_guard)])
async def room_peers_status(request: Request):
    """H658 — this hub's identity fingerprint, invitations, remote members and links (no credentials)."""
    svc = _service(request)
    if svc is None:
        return nocache_json({"enabled": False, "available": False})
    return nocache_json({"available": True, **svc.status()})


@router.post("/api/room-peers/invitations", dependencies=[Depends(admin_guard)])
async def room_peers_invite(request: Request, body: InviteBody):
    """H658 — invite a remote member into a room; raises an approval card on this hub."""
    from agents.core.room_peers import RoomPeerError

    svc = _service(request)
    if svc is None:
        return _unavailable()
    try:
        out = svc.invite(body.room_id, body.member_id, body.tools, target_url=body.target_url,
                         permissions=body.permissions, max_calls_per_hour=body.max_calls_per_hour)
    except RoomPeerError as exc:
        return _refusal(exc)
    return nocache_json({"ok": True, **out})


@router.post("/api/room-peers/invitations/{invite_id}/bundle", dependencies=[Depends(admin_guard)])
async def room_peers_bundle(request: Request, invite_id: str):
    """H658 — the one-time bundle of an approved invitation (a new call replaces the code)."""
    from agents.core.room_peers import RoomPeerError

    svc = _service(request)
    if svc is None:
        return _unavailable()
    if not svc.enabled():
        return _disabled()
    try:
        return nocache_json({"ok": True, **svc.issue_bundle(invite_id)})
    except RoomPeerError as exc:
        return _refusal(exc)


@router.post("/api/room-peers/members/{membership_id}/policy", dependencies=[Depends(admin_guard)])
async def room_peers_policy(request: Request, membership_id: str, body: PolicyBody):
    """H658 — change a member's execution policy; its digest moves and every grant must be re-issued."""
    from agents.core.room_peers import RoomPeerError

    svc = _service(request)
    if svc is None:
        return _unavailable()
    if not svc.enabled():
        return _disabled()
    try:
        return nocache_json({"ok": True, **svc.set_policy(
            membership_id, body.tools, body.permissions, body.max_calls_per_hour)})
    except RoomPeerError as exc:
        return _refusal(exc)


@router.delete("/api/room-peers/members/{membership_id}", dependencies=[Depends(admin_guard)])
async def room_peers_revoke(request: Request, membership_id: str):
    """H658 — revoke a remote member: refused on its next call, the room's epoch moves."""
    from agents.core.room_peers import RoomPeerError

    svc = _service(request)
    if svc is None:
        return _unavailable()
    try:
        return nocache_json({"ok": True, **svc.revoke_member(membership_id)})
    except RoomPeerError as exc:
        return _refusal(exc)


@router.post("/api/room-peers/links", dependencies=[Depends(admin_guard)])
async def room_peers_join(request: Request, body: JoinBody):
    """H658 — redeem a target hub's bundle: pins its key and stores the grant (never shown)."""
    from agents.core.room_peers import RoomPeerError

    svc = _service(request)
    if svc is None:
        return _unavailable()
    try:
        return nocache_json({"ok": True, "link": await svc.join(body.bundle, body.label)})
    except RoomPeerError as exc:
        return _refusal(exc)


@router.post("/api/room-peers/links/{link_id}/call", dependencies=[Depends(admin_guard)])
async def room_peers_call(request: Request, link_id: str, body: LinkCallBody):
    """H658 — act as the member on the target hub (its kernel and approvals decide)."""
    from agents.core.room_peers import RoomPeerError

    svc = _service(request)
    if svc is None:
        return _unavailable()
    try:
        answer = await svc.remote_call(link_id, body.tool, body.args, op=body.op, task_id=body.task_id)
    except RoomPeerError as exc:
        return _refusal(exc)
    return nocache_json(answer)


@router.post("/api/room-peers/links/{link_id}/renew", dependencies=[Depends(admin_guard)])
async def room_peers_renew(request: Request, link_id: str):
    """H658 — ask the target hub to renew this link's grant (refused if its policy moved)."""
    from agents.core.room_peers import RoomPeerError

    svc = _service(request)
    if svc is None:
        return _unavailable()
    if not svc.enabled():
        return _disabled()
    try:
        return nocache_json(await svc.renew(link_id))
    except RoomPeerError as exc:
        return _refusal(exc)


@router.delete("/api/room-peers/links/{link_id}", dependencies=[Depends(admin_guard)])
async def room_peers_leave(request: Request, link_id: str):
    """H658 — forget a link and its grant on this (member) hub."""
    from agents.core.room_peers import RoomPeerError

    svc = _service(request)
    if svc is None:
        return _unavailable()
    try:
        return nocache_json({"ok": True, **svc.leave(link_id)})
    except RoomPeerError as exc:
        return _refusal(exc)


async def _peer(request: Request, path: str) -> Response:
    svc = _service(request)
    if svc is None or not svc.enabled():
        return nocache_json({"error": "room peers disabled"}, status_code=404)
    from agents.core.room_peers import H_NONCE, H_SIG

    raw = await _bounded_body(request)
    client = request.client.host if request.client else ""
    if raw is None:
        status, body, sign = 413, {"error": "too_large"}, False
    else:
        status, body, sign = await svc.handle_peer(path, dict(request.headers), raw, client=client)
    content = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {"Cache-Control": "no-cache, no-store, must-revalidate"}
    if sign:
        # only an authenticated request's nonce is signed over (review n4)
        headers[H_SIG] = svc.sign_response(request.headers.get(H_NONCE, ""), status, content)
    return Response(content=content, status_code=status, media_type="application/json",
                    headers=headers)


async def _bounded_body(request: Request) -> bytes | None:
    """The request body, or ``None`` past ``MAX_BODY``: refused on the declared
    Content-Length before anything is read, and on the streamed size otherwise."""
    from agents.core.room_peers import MAX_BODY

    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_BODY:
                return None
        except ValueError:
            return None
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/room-peers/peer/accept")
async def room_peers_peer_accept(request: Request):
    """H658 peer — redeem an approved invitation (invite code proof + member key signature)."""
    from agents.core.room_peers import PATH_ACCEPT

    return await _peer(request, PATH_ACCEPT)


@router.post("/api/room-peers/peer/call")
async def room_peers_peer_call(request: Request):
    """H658 peer — a member's dispatch/status call (NervaRoom grant + pinned-key signature)."""
    from agents.core.room_peers import PATH_CALL

    return await _peer(request, PATH_CALL)


@router.post("/api/room-peers/peer/renew")
async def room_peers_peer_renew(request: Request):
    """H658 peer — renew a grant (refused when revoked or the execution-policy digest moved)."""
    from agents.core.room_peers import PATH_RENEW

    return await _peer(request, PATH_RENEW)
