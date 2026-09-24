"""Inbound webhook trigger endpoints (H10.8) — extracted from web.py (CLN-3).

H153/H200: a hook can be switched off without losing its token (PATCH), and
creating, switching and deleting one each write an audit row that names the hook,
its target and whether it is signed, never its token or signing secret.
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field, StrictBool

from agents.core.action_origin import INBOUND_ACTION_ORIGIN, bind_action_origin, reset_action_origin
from agents.core.web_helpers import nocache_json, error_json
from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard

logger = logging.getLogger("jarvis.webhooks")

router = APIRouter(tags=["webhooks"])

_webhook_store = None


def _get_webhook_store():
    global _webhook_store
    if _webhook_store is None:
        from agents.core.webhooks import WebhookStore
        _webhook_store = WebhookStore()
    return _webhook_store


class WebhookCreateBody(BaseModel):
    target: str = Field(..., max_length=128)
    target_type: str = Field("agent", pattern="^(agent|workflow)$")
    name: str = Field("", max_length=128)
    signed: bool = False   # H16.4 — require an HMAC X-Signature-256 on triggers


class WebhookSwitchBody(BaseModel):
    enabled: StrictBool


def _printable(value, limit: int = 128) -> str:
    """One line of printable text: a target cannot forge a second audit line."""
    return "".join(ch if ch.isprintable() else " " for ch in str(value))[:limit]


async def _audit_webhook(action: str, record: dict) -> None:
    """H153 — a hook created, switched or deleted: its id, target and signed flag,
    never its token or signing secret (the precedent is admin._audit_settings_change)."""
    orch = get_orch()
    audit = getattr(orch, "audit", None) if orch else None
    if audit is None:
        return
    from agents.core.security.types import SecurityEvent, SecurityEventType

    preview = (f"webhook {action}: id={_printable(record.get('id'))} "
               f"target={_printable(record.get('target_type'))}:{_printable(record.get('target'))} "
               f"signed={bool(record.get('signed'))} enabled={record.get('enabled', True) is not False}")
    try:
        await asyncio.to_thread(audit.log, SecurityEvent(
            event_type=SecurityEventType.SETTINGS_CHANGE,
            timestamp=time.time(),
            content_preview=preview,
            action_taken=f"webhook_{action}",
        ))
    except Exception:
        logger.warning("webhook %s: the audit row could not be written", action, exc_info=True)


# SEC-1: webhook *management* is admin-only. Creating a webhook mints a trigger
# token and a webhook can run an agent/workflow, so an unguarded management
# surface defeats the trigger's own token/HMAC auth. The trigger route below
# stays open by design — it authenticates per-webhook (token or HMAC).
@router.get("/api/webhooks", dependencies=[Depends(admin_guard)])
async def list_webhooks():
    """List configured inbound webhooks (tokens masked)."""
    return nocache_json({"webhooks": _get_webhook_store().list()})


@router.post("/api/webhooks", dependencies=[Depends(admin_guard)])
async def create_webhook(body: WebhookCreateBody):
    """Create an inbound webhook; the token is returned ONCE."""
    try:
        rec = _get_webhook_store().create(body.target, body.target_type, body.name, signed=body.signed)
    except ValueError as exc:
        return error_json(exc, 400, "invalid webhook target")
    await _audit_webhook("create", rec)
    return nocache_json(rec)


@router.patch("/api/webhooks/{hook_id}", dependencies=[Depends(admin_guard)])
async def switch_webhook(hook_id: str, body: WebhookSwitchBody):
    """Switch a hook on or off (H153). It keeps its token; a disabled hook refuses
    every delivery after authentication."""
    rec = _get_webhook_store().set_enabled(hook_id, body.enabled)
    if rec is None:
        return nocache_json({"error": "webhook not found"}, status_code=404)
    await _audit_webhook("enable" if body.enabled else "disable", rec)
    return nocache_json({"ok": True, "webhook": rec})


@router.delete("/api/webhooks/{hook_id}", dependencies=[Depends(admin_guard)])
async def delete_webhook(hook_id: str):
    store = _get_webhook_store()
    rec = store.get(hook_id)
    ok = store.delete(hook_id)
    if ok and rec is not None:
        await _audit_webhook("delete", rec)
    return nocache_json({"ok": ok}, status_code=200 if ok else 404)


@router.post("/api/webhooks/{hook_id}")
async def trigger_webhook(hook_id: str, request: Request):
    """Token-authenticated trigger → runs the configured agent/workflow."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    store = _get_webhook_store()
    hook = store.get(hook_id)
    if hook is None:
        return nocache_json({"error": "webhook not found"}, status_code=404)

    raw = await request.body()
    if hook.get("signed"):
        # H16.4: signed sources authenticate via HMAC over the raw body.
        signature = request.headers.get("x-signature-256", "")
        if not store.verify_signature(hook_id, raw, signature):
            return nocache_json({"error": "invalid or missing signature"}, status_code=401)
    else:
        token = request.headers.get("x-webhook-token") or request.query_params.get("token", "")
        if not store.verify(hook_id, token):
            return nocache_json({"error": "invalid or missing token"}, status_code=401)
    # H153 — checked after authentication, so a caller without the token or secret
    # learns nothing about the switch. A refused delivery is not counted as a call.
    if not store.is_enabled(hook):
        return nocache_json({"error": "webhook disabled"}, status_code=403)

    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = raw.decode("utf-8", "replace")

    from agents.core.webhooks import extract_input
    text = extract_input(payload)
    store.mark_called(hook_id)

    if hook["target_type"] == "agent":
        reply = await orch.handle_input(text, channel="webhook", agent_override=hook["target"])
        return nocache_json({"ok": True, "target": hook["target"], "response": reply})

    # workflow target (requires the workflow engine)
    engine = getattr(orch, "workflow_engine", None)
    if engine is None or not hasattr(engine, "run"):
        return nocache_json({"error": "workflow execution not available"}, status_code=501)
    from agents.core.routers.workflows import resolve_pipeline
    try:
        pipeline = resolve_pipeline(orch, hook["target"])
    except Exception as exc:
        return error_json(exc, 200, "invalid stored pipeline", extra={"ok": False, "target": hook["target"]})
    if pipeline is None:
        return nocache_json({"ok": False, "error": "workflow not found", "target": hook["target"]}, status_code=404)
    # The text came from outside, so every step the workflow runs is an inbound turn.
    # The engine runs its steps through handle_input on the ``workflow`` channel,
    # which alone classifies as internal and trusted; bind_turn_action_origin never
    # downgrades an inbound parent, so this binding is what the kernel sees.
    origin_token = bind_action_origin(INBOUND_ACTION_ORIGIN)
    try:
        result = await engine.run(pipeline, initial_input=text)
    except Exception as exc:
        return error_json(exc, 200, "workflow run failed", extra={"ok": False, "target": hook["target"]})
    finally:
        reset_action_origin(origin_token)
    return nocache_json({"ok": result.get("_ok", True), "target": hook["target"], "result": result})
