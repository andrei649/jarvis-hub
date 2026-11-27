"""Owner-initiated ChatGPT plan connection for the desktop hub."""

import asyncio
import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from agents.core import chatgpt_connection as account
from agents.core.routers._deps import owner_web_principal
from agents.core.routers.browser_auth import _loopback
from agents.core.routers.integrations_setup import _audit, _redetect_router, same_origin_write
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


class ChatChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: StrictStr = Field(min_length=1, max_length=120)
    confirm_expensive: StrictBool = False
    acknowledge_training: StrictBool = False


@router.post(BASE + "/select", dependencies=_WRITE)
async def select_for_chat(body: ChatChoice):
    """Choose a visible plan model for ordinary chat, after the usual settings consent."""
    from agents.core import managed_scope, settings_db

    from . import admin

    model = body.model.strip()
    if not model:
        return nocache_json({"error": "model_required"}, status_code=422)
    values = {"compatible_provider": "chatgpt-plan", "compatible_model": model}
    problems = settings_db.validate_category("llm", values) + settings_db.route_only_problems("llm", values)
    if problems:
        return nocache_json({"error": "invalid_settings", "details": problems}, status_code=422)
    try:
        for key, value in values.items():
            managed_scope.check_setting_write("llm", key, value)
    except managed_scope.ManagedRefused as exc:
        return await admin._managed_refusal(exc, "llm")
    changes = {"llm": values}
    try:
        pair_state = await admin._pair_snapshot(changes)
    except Exception as exc:
        return admin._selection_write_refusal(exc)
    guarded = await admin._guard_selection(
        changes, confirm_expensive=body.confirm_expensive,
        acknowledge_training=body.acknowledge_training,
        surface="chatgpt-plan", pair_state=pair_state,
    )
    if isinstance(guarded, JSONResponse):
        return guarded
    # Catalog validation may contact only this owner's provider. It runs after
    # policy/consent guards and does not bind a chat route yet.
    try:
        prepared = await account.prepare_chat_selection(model)
    except account.ConnectionError as exc:
        return nocache_json({"error": exc.reason}, status_code=exc.status)
    try:
        _, skipped = await admin._drain_settings_write(
            settings_db.put_category, "llm", values,
            expected_pair_revision=pair_state[0] if pair_state else None,
        )
    except Exception as exc:
        if admin._is_managed_refusal(exc):
            return await admin._managed_refusal(exc, "llm")
        return admin._selection_write_refusal(exc)
    pinned = set(settings_db.managed_setting_names("llm"))
    skipped = [key for key in skipped if f"llm.{key}" not in pinned]
    if skipped:
        return nocache_json({"error": "not_stored", "skipped": skipped}, status_code=409)
    await admin._audit_settings_change("llm", list(values), values)
    try:
        await _audit(f"ChatGPT plan model chosen for chat: {model}", "chatgpt_plan_chat_selected", required=True)
    except Exception:
        return nocache_json({"error": "selection_audit_unavailable"}, status_code=503)
    try:
        await asyncio.to_thread(account.select_for_chat, model, prepared)
    except account.ConnectionError as exc:
        return nocache_json({"error": exc.reason}, status_code=exc.status)
    try:
        if not await _redetect_router():
            raise RuntimeError("router unavailable")
    except Exception:
        return nocache_json({"error": "router_unavailable"}, status_code=503)
    return nocache_json({"model": model})


@router.post(BASE + "/disconnect", dependencies=_WRITE)
async def disconnect():
    try:
        await asyncio.to_thread(account.disconnect)
    except account.ConnectionError as exc:
        return nocache_json({"error": exc.reason}, exc.status)
    await _audit("ChatGPT plan disconnected locally", "chatgpt_plan_disconnected")
    return nocache_json({"connected": False})
