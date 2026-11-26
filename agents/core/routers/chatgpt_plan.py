"""Owner-initiated ChatGPT plan connection for the desktop hub."""

import asyncio
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from agents.core import chatgpt_connection as account
from agents.core.routers._deps import owner_web_principal
from agents.core.routers.browser_auth import _loopback
from agents.core.routers.integrations_setup import _audit, same_origin_write
from agents.core.security.browser_session import same_origin
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["integrations"])
BASE = "/api/admin/chatgpt-plan"
CALLBACK = "/api/oauth/chatgpt/callback"


def _same_page(request: Request):
    if not same_origin(request):
        raise HTTPException(403, "same_origin_required")


_OWNER = [Depends(owner_web_principal), Depends(_same_page)]
_WRITE = [*_OWNER, Depends(same_origin_write)]


def _local_callback(request: Request) -> str:
    base = request.base_url
    if (base.scheme != "http" or base.hostname != "127.0.0.1"
            or base.path != "/" or not _loopback(request)):
        raise HTTPException(403, "chatgpt_requires_local_hub")
    return str(base).rstrip("/") + CALLBACK


def _cookie(state: str) -> str:
    return "nerva_chatgpt_" + hashlib.sha256(state.encode()).hexdigest()[:16]


@router.get(BASE, dependencies=_OWNER)
def connection_status():
    try:
        return nocache_json(account.status())
    except account.ConnectionError as exc:
        return nocache_json({"error": exc.reason}, exc.status)


@router.post(BASE + "/connect", dependencies=_WRITE)
async def connect(request: Request):
    callback = _local_callback(request)
    binding = secrets.token_urlsafe(32)
    try:
        started = await asyncio.to_thread(account.start, callback, binding)
    except account.ConnectionError as exc:
        return nocache_json({"error": exc.reason}, exc.status)
    response = nocache_json({"url": started["url"]})
    response.set_cookie(_cookie(started["state"]), binding, path=CALLBACK, httponly=True,
                        samesite="lax", max_age=600)
    return response


@router.get(CALLBACK, response_class=HTMLResponse)
async def finish(request: Request):
    query = request.query_params
    # Uvicorn builds the access-log request target from this scope at response time.
    request.scope["query_string"] = b""
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
               "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"}
    status = 403
    text = "ChatGPT sign-in was not completed. Return to Nerva to start again."
    state = query.get("state", "")
    cookie = _cookie(state) if 0 < len(state) <= 200 else ""
    binding = request.cookies.get(cookie, "") if cookie else ""
    if (binding and len(binding) <= 200 and _loopback(request)
            and all(len(query.getlist(key)) <= 1 for key in ("state", "code", "client_id", "error"))):
        try:
            _local_callback(request)
            await account.complete(state, binding, code=query.get("code"), client_id=query.get("client_id"),
                                   error=query.get("error"))
        except (account.ConnectionError, HTTPException) as exc:
            status = exc.status if isinstance(exc, account.ConnectionError) else exc.status_code
        else:
            await _audit("ChatGPT plan connected", "chatgpt_plan_connected")
            status, text = 200, "ChatGPT is connected. Return to Nerva to view your available models."
    response = HTMLResponse(text, status_code=status, headers=headers)
    if binding:
        response.delete_cookie(cookie, path=CALLBACK)
    return response


@router.get(BASE + "/models", dependencies=_OWNER)
async def models():
    try:
        return nocache_json(await account.models())
    except account.ConnectionError as exc:
        return nocache_json({"error": exc.reason}, exc.status)


@router.post(BASE + "/disconnect", dependencies=_WRITE)
async def disconnect():
    try:
        await asyncio.to_thread(account.disconnect)
    except account.ConnectionError as exc:
        return nocache_json({"error": exc.reason}, exc.status)
    await _audit("ChatGPT plan disconnected locally", "chatgpt_plan_disconnected")
    return nocache_json({"connected": False})
