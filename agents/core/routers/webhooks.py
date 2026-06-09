"""Inbound webhook trigger endpoints (H10.8) — extracted from web.py (CLN-3)."""

import json

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

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


@router.get("/api/webhooks")
async def list_webhooks():
    """List configured inbound webhooks (tokens masked)."""
    from agents import web
    return web._nocache_json({"webhooks": _get_webhook_store().list()})


@router.post("/api/webhooks")
async def create_webhook(body: WebhookCreateBody):
    """Create an inbound webhook; the token is returned ONCE."""
    from agents import web
    try:
        rec = _get_webhook_store().create(body.target, body.target_type, body.name, signed=body.signed)
    except ValueError as exc:
        return web._nocache_json({"error": str(exc)}, status_code=400)
    return web._nocache_json(rec)


@router.delete("/api/webhooks/{hook_id}")
async def delete_webhook(hook_id: str):
    from agents import web
    ok = _get_webhook_store().delete(hook_id)
    return web._nocache_json({"ok": ok}, status_code=200 if ok else 404)


@router.post("/api/webhooks/{hook_id}")
async def trigger_webhook(hook_id: str, request: Request):
    """Token-authenticated trigger → runs the configured agent/workflow."""
    from agents import web
    orch = web.orch
    if not orch:
        return web._nocache_json({"error": "not initialized"}, status_code=503)
    store = _get_webhook_store()
    hook = store.get(hook_id)
    if hook is None:
        return web._nocache_json({"error": "webhook not found"}, status_code=404)

    raw = await request.body()
    if hook.get("signed"):
        # H16.4: signed sources authenticate via HMAC over the raw body.
        signature = request.headers.get("x-signature-256", "")
        if not store.verify_signature(hook_id, raw, signature):
            return web._nocache_json({"error": "invalid or missing signature"}, status_code=401)
    else:
        token = request.headers.get("x-webhook-token") or request.query_params.get("token", "")
        if not store.verify(hook_id, token):
            return web._nocache_json({"error": "invalid or missing token"}, status_code=401)

    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = raw.decode("utf-8", "replace")

    from agents.core.webhooks import extract_input
    text = extract_input(payload)
    store.mark_called(hook_id)

    if hook["target_type"] == "agent":
        reply = await orch.handle_input(text, channel="webhook", agent_override=hook["target"])
        return web._nocache_json({"ok": True, "target": hook["target"], "response": reply})

    # workflow target (best-effort — requires the workflow engine)
    engine = getattr(orch, "workflow_engine", None)
    if engine is None or not hasattr(engine, "run"):
        return web._nocache_json({"error": "workflow execution not available"}, status_code=501)
    result = await engine.run(hook["target"], {"input": text})
    return web._nocache_json({"ok": True, "target": hook["target"], "result": result})
