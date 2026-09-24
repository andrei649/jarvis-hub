"""Inbound webhook trigger endpoints (H10.8) — extracted from web.py (CLN-3).

H153/H200: a hook can be switched off without losing its token (PATCH), and
creating, switching and deleting one each write an audit row that names the hook,
its target and whether it is signed, never its token or signing secret.

H153 (the rest of a Hermes subscription): a hook's event list and prompt template,
set on create or by PATCH, and the receiver switch (setting
``webhooks.receiver_enabled``) that refuses every delivery at once.
"""

import asyncio
import json
import logging
import time

from typing import Annotated

from fastapi import APIRouter, Request, Depends
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator

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


def _event_name(value: str) -> str:
    from agents.core.webhooks import MAX_EVENT_NAME

    name = value.strip()
    if not name or len(name) > MAX_EVENT_NAME or not name.isprintable():
        raise ValueError(f"an event name is 1 to {MAX_EVENT_NAME} printable characters")
    return name


EventName = Annotated[StrictStr, AfterValidator(_event_name)]
EventList = Annotated[list[EventName], Field(max_length=32)]
PromptTemplate = Annotated[StrictStr, Field(max_length=2_000)]


class WebhookCreateBody(BaseModel):
    target: str = Field(..., max_length=128)
    target_type: str = Field("agent", pattern="^(agent|workflow)$")
    name: str = Field("", max_length=128)
    signed: bool = False   # H16.4 — require an HMAC X-Signature-256 on triggers
    events: EventList = Field(default_factory=list)   # H153 — empty: every event
    prompt: PromptTemplate = ""                        # H153 — empty: the payload's text


class WebhookUpdateBody(BaseModel):
    """H153 — what PATCH may change; at least one field, and none of them null."""
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool | None = None
    events: EventList | None = None
    prompt: PromptTemplate | None = None

    @model_validator(mode="after")
    def _a_real_change(self):
        if not self.model_fields_set:
            raise ValueError("nothing to change")
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


def _printable(value, limit: int = 128) -> str:
    """One line of printable text: a target cannot forge a second audit line."""
    return "".join(ch if ch.isprintable() else " " for ch in str(value))[:limit]


def _quoted(value, limit: int = 160) -> str:
    """A JSON string (quotes and control characters escaped): an owner-chosen target
    cannot pass off its own text as the row's id or flags."""
    return json.dumps(str(value)[:limit])


async def _audit_webhook(action: str, record: dict) -> None:
    """H153 — a hook created, switched or deleted: its id, target and signed flag,
    never its token or signing secret (the precedent is admin._audit_settings_change)."""
    orch = get_orch()
    audit = getattr(orch, "audit", None) if orch else None
    if audit is None:
        return
    from agents.core.security.types import SecurityEvent, SecurityEventType

    target = f"{record.get('target_type')}:{record.get('target')}"
    events = json.dumps(record.get("events") or [], ensure_ascii=False)
    prompt = record.get("prompt") if isinstance(record.get("prompt"), str) else ""
    preview = (f"webhook {action}: id={_printable(record.get('id'))} target={_quoted(target)} "
               f"events={events} prompt={len(prompt)} chars "
               f"signed={bool(record.get('signed'))} enabled={_get_webhook_store().is_enabled(record)}")
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
        rec = _get_webhook_store().create(body.target, body.target_type, body.name, signed=body.signed,
                                          events=body.events, prompt=body.prompt)
    except ValueError as exc:
        return error_json(exc, 400, "invalid webhook target")
    await _audit_webhook("create", rec)
    return nocache_json(rec)


@router.patch("/api/webhooks/{hook_id}", dependencies=[Depends(admin_guard)])
async def update_webhook(hook_id: str, body: WebhookUpdateBody):
    """Switch a hook on or off, or change its event list or prompt template (H153).
    It keeps its token; a disabled hook refuses every delivery after authentication."""
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    rec = _get_webhook_store().update(hook_id, **changes)
    if rec is None:
        return nocache_json({"error": "webhook not found"}, status_code=404)
    if set(changes) == {"enabled"}:
        await _audit_webhook("enable" if body.enabled else "disable", rec)
    else:
        await _audit_webhook("update", rec)
    return nocache_json({"ok": True, "webhook": rec})


@router.delete("/api/webhooks/{hook_id}", dependencies=[Depends(admin_guard)])
async def delete_webhook(hook_id: str):
    store = _get_webhook_store()
    rec = store.get(hook_id)
    ok = store.delete(hook_id)
    if ok and rec is not None:
        await _audit_webhook("delete", rec)
    if not ok:
        return nocache_json({"ok": False, "error": "webhook not found"}, status_code=404)
    return nocache_json({"ok": True})


def _receiver_enabled() -> bool:
    """H153 — the platform-level switch (setting ``webhooks.receiver_enabled``, on by
    default). Only a stored false turns it off: a settings store that cannot be read
    leaves every hook to its own switch."""
    from agents.core import settings_db

    return settings_db.get_value("webhooks", "receiver_enabled", True) is not False


def _receiver_off():
    return nocache_json({"error": "the webhook receiver is off"}, status_code=503)


def _skipped(store, hook_id: str, event: str, reason: str):
    store.mark_skipped(hook_id, event)
    return nocache_json({"ok": True, "skipped": reason}, status_code=202)


@router.post("/api/webhooks/{hook_id}")
async def trigger_webhook(hook_id: str, request: Request):
    """Token-authenticated trigger → runs the configured agent/workflow."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    # H153 — the receiver switch is read before the body (a flood costs nothing to
    # refuse) and again after authentication (a switch that lands mid-body).
    if not _receiver_enabled():
        return _receiver_off()
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
    # H153 — the switch is read from the live record, after authentication: the body
    # read above can take any time, and a switch-off that lands during it must stop
    # this delivery too. A caller without the token or secret learns nothing about
    # it, and a refused delivery is not counted as a call.
    live = store.get(hook_id)
    if live is None:
        return nocache_json({"error": "webhook not found"}, status_code=404)
    if not _receiver_enabled():
        return _receiver_off()
    if not store.is_enabled(live):
        return nocache_json({"error": "webhook disabled"}, status_code=403)

    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = raw.decode("utf-8", "replace")

    # H153 — the event list and the prompt template, both from the live record. A
    # delivery the list turns away is answered 202 (the sender does not retry), is
    # never run and is counted as skipped, not as a call.
    from agents.core.webhooks import delivery_event, event_subscribed, extract_input, render_prompt
    event = delivery_event(request.headers, payload)
    events = store.stored_events(live)
    if events is None:
        return _skipped(store, hook_id, event, "the hook's event list is unreadable")
    if events and not event:
        return _skipped(store, hook_id, event, "the delivery names no event")
    if events and not event_subscribed(events, event):
        return _skipped(store, hook_id, event, f"event '{event}' is not subscribed")
    template = live.get("prompt") if isinstance(live.get("prompt"), str) else ""
    text = render_prompt(template, payload, event) if template else extract_input(payload)
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
