"""Inbound webhook trigger endpoints (H10.8) — extracted from web.py (CLN-3).

H153/H200: a hook can be switched off without losing its token (PATCH), and
creating, switching and deleting one each write an audit row that names the hook,
its target and whether it is signed, never its token or signing secret.

H153 (the rest of a Hermes subscription): a hook's event list and prompt template,
set on create or by PATCH, and the receiver switch (setting
``webhooks.receiver_enabled``) that refuses every delivery at once.

H153 review: where a delivery goes (``deliver``: the log, or one of the owner's own
direct-send channels through ``send_to_target``; ``deliver_only`` skips the agent; a
push waits out quiet hours as a note on the hook), a description, a receiver switch
that fails closed and is read off the event loop, and a body cap.
"""

import asyncio
import json
import logging
import time

from typing import Annotated

from fastapi import APIRouter, Request, Depends
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator
from pydantic.json_schema import SkipJsonSchema

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
    if not name or len(name) > MAX_EVENT_NAME or not name.isprintable() or "," in name:
        raise ValueError(f"an event name is 1 to {MAX_EVENT_NAME} printable characters, no comma")
    return name


def _destination(value: str) -> str:
    from agents.core.webhooks import destination_problem

    problem = destination_problem(value)
    if problem:
        raise ValueError(problem)
    return value


EventName = Annotated[StrictStr, AfterValidator(_event_name)]
EventList = Annotated[list[EventName], Field(max_length=32)]
PromptTemplate = Annotated[StrictStr, Field(max_length=2_000)]
Destination = Annotated[StrictStr, AfterValidator(_destination)]
Description = Annotated[StrictStr, Field(max_length=500)]


class WebhookCreateBody(BaseModel):
    """A new hook. A field this model does not know is refused (a Hermes-shaped create
    that carries ``skills`` or ``deliver_chat_id`` hears no, rather than a silent drop)."""
    model_config = ConfigDict(extra="forbid")
    target: str = Field(..., max_length=128)
    target_type: str = Field("agent", pattern="^(agent|workflow)$")
    name: str = Field("", max_length=128)
    signed: bool = False   # H16.4 — require an HMAC X-Signature-256 on triggers
    events: EventList = Field(default_factory=list)   # H153 — empty: every event
    prompt: PromptTemplate = ""                        # H153 — empty: the payload's text
    deliver: Destination = "log"                       # H153 review — where the result goes
    deliver_only: StrictBool = False                   # H153 review — skip the agent
    description: Description = ""


class WebhookUpdateBody(BaseModel):
    """H153 — what PATCH may change; at least one field, and none of them null (the
    schema says so too: a null is not advertised)."""
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool | SkipJsonSchema[None] = None
    events: EventList | SkipJsonSchema[None] = None
    prompt: PromptTemplate | SkipJsonSchema[None] = None
    deliver: Destination | SkipJsonSchema[None] = None
    deliver_only: StrictBool | SkipJsonSchema[None] = None
    description: Description | SkipJsonSchema[None] = None

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
    store = _get_webhook_store()
    preview = (f"webhook {action}: id={_printable(record.get('id'))} target={_quoted(target)} "
               f"events={events} prompt={len(prompt)} chars "
               f"deliver={store.destination(record)} deliver_only={store.delivers_only(record)} "
               f"signed={bool(record.get('signed'))} enabled={store.is_enabled(record)}")
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
                                          events=body.events, prompt=body.prompt, deliver=body.deliver,
                                          deliver_only=body.deliver_only, description=body.description)
    except ValueError as exc:
        return error_json(exc, 400, "invalid webhook target")
    await _audit_webhook("create", rec)
    return nocache_json(rec)


@router.patch("/api/webhooks/{hook_id}", dependencies=[Depends(admin_guard)])
async def update_webhook(hook_id: str, body: WebhookUpdateBody):
    """Switch a hook on or off, or change its event list or prompt template (H153).
    It keeps its token; a disabled hook refuses every delivery after authentication."""
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    try:
        rec = _get_webhook_store().update(hook_id, **changes)
    except ValueError as exc:
        return error_json(exc, 422, "invalid webhook change")
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


#: The largest body a delivery may carry (a GitHub push with hundreds of commits is a
#: few megabytes). A larger one is refused with 413 once the cap is crossed, before the
#: rest is read, because the trigger holds the raw body to check its signature.
MAX_BODY_BYTES = 5 * 1024 * 1024


async def _receiver_refusal():
    """H153 — the platform-level switch (setting ``webhooks.receiver_enabled``, on by
    default), read off the event loop through ``webhooks.RECEIVER``, which fails closed:
    off, and a store that cannot be read, both refuse. The refusal, or None to go on."""
    from agents.core.webhooks import RECEIVER

    state = await asyncio.to_thread(RECEIVER.state)
    if state is True:
        return None
    if state is None:
        return nocache_json({"error": "the webhook receiver's state cannot be read"}, status_code=503)
    return nocache_json({"error": "the webhook receiver is off"}, status_code=503)


async def _capped_body(request: Request):
    """The raw body, or None when it is larger than :data:`MAX_BODY_BYTES`."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _quiet_hours(orch) -> bool:
    """The owner's night, as the jobs read it (ambient.quiet_hours_start/end)."""
    from agents.core.autonomy.jobs import (
        DEFAULT_QUIET_END, DEFAULT_QUIET_START, QUIET_END_SETTING, QUIET_START_SETTING)
    from agents.core.autonomy.worker import is_night

    get_setting = getattr(orch, "get_setting", None)

    def hour(key, default):
        try:
            value = get_setting(key, default) if callable(get_setting) else default
            return int(value)
        except (TypeError, ValueError):
            return default

    return is_night(time.localtime().tm_hour, start=hour(QUIET_START_SETTING, DEFAULT_QUIET_START),
                    end=hour(QUIET_END_SETTING, DEFAULT_QUIET_END))


_CUT_NOTE = "… (cut: the whole reply is in the session)"


async def _deliver(orch, store, hook: dict, text: str, event: str) -> dict:
    """H153 review — send a delivery's result where the hook says, and note how it went.

    The log is the reply in the sender's response and the session: nothing to send. An
    owner channel gets the text through ``send_to_target`` (audited, rate-limited, the
    owner's own destination only), labelled as the hook, cut to what the channel
    carries. A push channel stays silent through quiet hours and says so."""
    from agents.core.channels import outbound
    from agents.core.webhooks import DELIVER_LOG, PUSH_CHANNELS, _event_name

    channel = store.destination(hook)
    if channel == DELIVER_LOG:
        store.mark_delivered(hook["id"], channel, True)
        return {"channel": channel, "ok": True}
    if channel in PUSH_CHANNELS and _quiet_hours(orch):
        reason = "quiet hours: not pushed; the reply is in the session"
        store.mark_delivered(hook["id"], channel, False, reason)
        return {"channel": channel, "ok": False, "reason": reason}
    label = _event_name(str(hook.get("name") or hook.get("target") or "webhook"), 80)
    subject = f"Webhook {label}" + (f" · {_event_name(event, 64)}" if event else "")
    room = outbound.MAX_TEXT_CHARS - len(subject) - 2
    body = str(text or "")
    if len(body) > room:
        body = body[:room - len(_CUT_NOTE)] + _CUT_NOTE
    result = await outbound.send_to_target(orch, channel, body, subject=subject, source=f"webhook:{hook['id']}")
    ok = bool(result.get("ok"))
    reason = "" if ok else str(result.get("reason") or "not delivered")
    store.mark_delivered(hook["id"], channel, ok, reason)
    return {"channel": channel, "ok": True} if ok else {"channel": channel, "ok": False, "reason": reason}


def _workflow_text(pipeline, result) -> str:
    """The last step's output: what a workflow run hands on."""
    for step in reversed(list(getattr(pipeline, "steps", None) or [])):
        out = result.get(getattr(step, "id", None)) if isinstance(result, dict) else None
        if isinstance(out, str) and out and not out.startswith("[error:"):
            return out
    return ""


def _skipped(store, hook_id: str, event: str, reason: str):
    store.mark_skipped(hook_id, event)
    return nocache_json({"ok": True, "skipped": reason}, status_code=202)


@router.post("/api/webhooks/{hook_id}")
async def trigger_webhook(hook_id: str, request: Request):
    """Token-authenticated trigger → runs the configured agent/workflow."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    # H153 — the receiver switch is read before the body (a refusal reads no body) and
    # again after authentication (a switch that lands mid-body).
    refusal = await _receiver_refusal()
    if refusal is not None:
        return refusal
    store = _get_webhook_store()
    hook = store.get(hook_id)
    if hook is None:
        return nocache_json({"error": "webhook not found"}, status_code=404)

    raw = await _capped_body(request)
    if raw is None:
        return nocache_json({"error": f"the body is larger than {MAX_BODY_BYTES} bytes"}, status_code=413)
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
    refusal = await _receiver_refusal()
    if refusal is not None:
        return refusal
    live = store.get(hook_id)           # the read above awaited: take the record as it is now
    if live is None:
        return nocache_json({"error": "webhook not found"}, status_code=404)
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
    if not text.strip():
        return _skipped(store, hook_id, event, "the prompt template rendered nothing")
    store.mark_called(hook_id)

    if store.delivers_only(live):
        # Deliver only: the rendered text goes where the hook says, and no turn runs.
        delivery = await _deliver(orch, store, live, text, event)
        return nocache_json({"ok": True, "target": hook["target"], "delivery": delivery})

    if hook["target_type"] == "agent":
        reply = await orch.handle_input(text, channel="webhook", agent_override=hook["target"])
        delivery = await _deliver(orch, store, live, reply if isinstance(reply, str) else str(reply), event)
        return nocache_json({"ok": True, "target": hook["target"], "response": reply, "delivery": delivery})

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
    out = _workflow_text(pipeline, result)
    delivery = await _deliver(orch, store, live, out, event) if out else {
        "channel": store.destination(live), "ok": False, "reason": "the workflow produced no text"}
    return nocache_json({"ok": result.get("_ok", True), "target": hook["target"], "result": result,
                         "delivery": delivery})
