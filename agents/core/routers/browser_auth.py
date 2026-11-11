"""Owner browser sign-in for a networked hub (H509, G13).

``POST /api/auth/login`` exchanges the owner secret — any valid admin credential, the
bootstrap ``JARVIS_ADMIN_TOKEN`` or a managed admin token — for an ``HttpOnly``,
``SameSite=Strict`` session cookie (``Secure`` over HTTPS). ``GET /api/auth/session``
tells the HUD whether it is signed in and hands it the session's CSRF token;
``POST /api/auth/logout`` ends this browser's session and ``POST /api/auth/logout-all``
ends every one. The session model, the cookie, CSRF and the throttle live in
``agents/core/security/browser_session.py``; the guards that accept the cookie are in
``agents/web.py`` (``_owner_session``).

A guest's user token, an OpenAI-compatible API key or a Workspace session never opens
an owner session: only an admin credential does. Loopback is unchanged — a box with no
admin credential still trusts a direct loopback caller and has nothing to sign in with.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from agents.core.security import browser_session as bs
from agents.core.security.auth_audit import submit_auth_event
from agents.core.web_helpers import nocache_json

from ._deps import _web, admin_guard

router = APIRouter(tags=["auth"])

_LOGIN_BODY_LIMIT = 8192


def _refuse(status: int, error: str, message: str, **extra: Any) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if "retry_after_seconds" in extra:
        headers["Retry-After"] = str(extra["retry_after_seconds"])
    return JSONResponse({"error": error, "message": message, **extra}, status_code=status,
                        headers=headers)


def _client(request: Request) -> str:
    return request.client.host if request.client else ""


def _loopback(request: Request) -> bool:
    """A browser on the hub's own machine (the localhost gate's origin, HF-7)."""
    web = _web()
    return web._real_client_host(request) in web._LOCALHOSTS


def _session_payload(session: dict | None) -> dict:
    if not session:
        return {"signed_in": False}
    return {"signed_in": True, "csrf": session["csrf_token"],
            "expires_at": session["expires_at"],
            "idle_expires_at": session.get("idle_expires_at")}


@router.get("/api/auth/session")
async def auth_session(request: Request):
    """Whether this browser holds a live owner session (and its CSRF token if so).

    Open by design: an anonymous caller learns only ``signed_in: false``, whether the hub
    has an owner credential to sign in with, and whether this transport allows browser
    sign-in. The CSRF token comes back solely for a valid session cookie sent with
    positive same-origin evidence. Reading it counts as use (the HUD reads it on load),
    so it refreshes the idle clock."""
    web = _web()
    transport_ok = bs.transport_ok(request, loopback=_loopback(request))
    session = None
    if transport_ok and bs.cookie_present(request):
        state, found = await asyncio.to_thread(
            bs.session_state, request, web._owner_credential_hash_valid, touch=True)
        session = found if state != bs.NONE else None
    payload = _session_payload(session)
    payload["sign_in_available"] = bool(web._admin_configured()) and transport_ok
    if not transport_ok:
        payload["reason"] = "https_required"
    return nocache_json(payload)


@router.post("/api/auth/login")
async def auth_login(request: Request):
    """Exchange the owner secret for a browser session cookie.

    Same-origin and ``application/json`` only (a cross-site form cannot send either);
    over plain HTTP from another device only with ``JARVIS_ALLOW_INSECURE_SIGNIN=1``.
    Throttled per address before the secret is checked; the hub-wide failure count
    never refuses a correct secret (anyone could otherwise lock the owner out), it only
    slows and refuses wrong ones. Loopback is exempt from both. The secret is compared
    in constant time. Each sign-in rotates the session: the one the browser presented
    is revoked."""
    web = _web()
    client = _client(request)
    if not bs.same_origin(request):
        return _refuse(403, "csrf_failed", "cross-origin sign-in refused")
    if not bs.is_json(request):
        return _refuse(415, "unsupported_media_type", "send application/json")
    raw = await request.body()
    if len(raw) > _LOGIN_BODY_LIMIT:
        return _refuse(413, "too_large", "sign-in body too large")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return _refuse(422, "invalid_request", "body must be JSON")
    secret = body.get("secret") if isinstance(body, dict) else None
    if not isinstance(secret, str) or not secret.strip() or len(secret) > bs.MAX_SECRET_LENGTH:
        return _refuse(422, "invalid_request", "secret is required")
    secret = secret.strip()
    if not web._admin_configured():
        return _refuse(409, "no_owner_credential",
                       "this hub has no owner credential yet; a direct loopback browser is "
                       "already the owner. Set JARVIS_ADMIN_TOKEN (or mint one with "
                       "scripts/token_recover.py rotate admin) to sign in from the network")
    loopback = _loopback(request)
    if not bs.transport_ok(request, loopback=loopback):
        return _refuse(403, "https_required",
                       "browser sign-in from another device needs HTTPS: over plain HTTP the "
                       "session cookie would be sent to every service on this host. Put the "
                       "hub behind HTTPS, or set JARVIS_ALLOW_INSECURE_SIGNIN=1 to accept the "
                       "risk on a trusted network")
    store = bs.get_session_store()
    ip = web._client_ip(request) or client
    attempt, global_wait = None, None
    if not loopback:
        try:
            attempt, global_wait = await asyncio.to_thread(store.reserve_attempt, ip)
        except bs.Throttled as exc:
            submit_auth_event("auth_failure", tier="admin", reason="throttled", client=client)
            return _refuse(429, "too_many_attempts", "too many failed sign-ins; try again later",
                           retry_after_seconds=exc.retry_after)
    # Only an admin credential opens an owner session: a guest's user token, an API key
    # or anything else is a wrong secret (and counted as one).
    ok = await asyncio.to_thread(web._admin_credential_ok, secret)
    if not ok:
        if global_wait:
            # Many failures hub-wide: slow every further wrong guess and say so, but
            # never refuse the right secret (that would be a lockout anyone can cause).
            await asyncio.sleep(bs.GLOBAL_BACKOFF_SECONDS)
            submit_auth_event("auth_failure", tier="admin", reason="throttled", client=client)
            return _refuse(429, "too_many_attempts", "too many failed sign-ins; try again later",
                           retry_after_seconds=global_wait)
        submit_auth_event("auth_failure", tier="admin", reason="invalid", client=client)
        return _refuse(401, "invalid_secret", "that is not this hub's owner secret")
    if attempt is not None:
        await asyncio.to_thread(store.settle_success, attempt)
    previous = bs.cookie_token(request)
    if previous:
        await asyncio.to_thread(store.revoke, bs.token_hash(previous))
    opened = await asyncio.to_thread(
        store.create, cred_hash=bs.token_hash(secret), ip=ip,
        user_agent=request.headers.get("user-agent", ""))
    submit_auth_event("auth_success", tier="admin", reason="sign_in", client=client)
    response = nocache_json({"signed_in": True, "csrf": opened["csrf"],
                             "expires_at": opened["expires_at"]})
    bs.set_session_cookie(response, request, opened["token"])
    return response


@router.post("/api/auth/logout")
async def auth_logout(request: Request):
    """Sign this browser out: revoke the session it presents and expire the cookie.

    Needs no other credential — it can only end the session it is shown — but a
    cross-origin request is refused so another site cannot sign the owner out."""
    if not bs.same_origin(request):
        return _refuse(403, "csrf_failed", "cross-origin sign-out refused")
    token = bs.cookie_token(request)
    revoked = False
    if token:
        revoked = await asyncio.to_thread(bs.get_session_store().revoke, bs.token_hash(token))
    if revoked:
        submit_auth_event("auth_success", tier="admin", reason="sign_out", client=_client(request))
    response = nocache_json({"signed_in": False, "revoked": revoked})
    bs.clear_session_cookies(response, request)
    return response


@router.post("/api/auth/logout-all", dependencies=[Depends(admin_guard)])
async def auth_logout_all(request: Request):
    """Sign out everywhere: revoke every owner browser session (owner only; a cookie
    caller must send its CSRF token, which the admin guard checks)."""
    count = await asyncio.to_thread(bs.get_session_store().revoke_all)
    submit_auth_event("token_revoked", tier="admin", reason="sign_out", count=count)
    response = nocache_json({"signed_in": False, "revoked": count})
    bs.clear_session_cookies(response, request)
    return response
