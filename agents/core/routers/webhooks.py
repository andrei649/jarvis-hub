"""Inbound webhook trigger endpoints (H10.8) — extracted from web.py (CLN-3).

H153/H200: a hook can be switched off without losing its token (PATCH), and
creating, switching and deleting one each write an audit row that names the hook,
its target and whether it is signed, never its token or signing secret.

H153 (the rest of a Hermes subscription): a hook's event list and prompt template,
set on create or by PATCH, and the receiver switch (setting
``webhooks.receiver_enabled``) that refuses every delivery at once.

H153 review: where a delivery goes (``deliver``: the log, or one of the owner's own
channels through ``send_to_target``; ``deliver_only`` skips the agent; quiet hours hold
a push, which is then noted on the hook), a description, a receiver switch that fails
closed and is read off the event loop, and a body cap.

H153 third round: a delivery reaches its channel for real (the quiet-hours rule ran for
the first time), a push that fails is recorded on the hook and is never a 500 after the
turn, the text goes as plain text, each hook is capped per hour, and the hook and the
receiver are read again after the turn, before anything is pushed.
"""

import asyncio
import json
import logging
import math
import re
import time
import unicodedata

from typing import Annotated

from fastapi import APIRouter, Request, Depends
from pydantic import (AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictStr, WithJsonSchema,
                      model_validator)
from pydantic.json_schema import SkipJsonSchema

from agents.core.action_origin import INBOUND_ACTION_ORIGIN, bind_action_origin, reset_action_origin
from agents.core.web_helpers import nocache_json, error_json
from agents.core.app_state import get_orch
from agents.core.routers._deps import admin_guard
from agents.core.webhooks import DELIVER_CHOICES

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
# The schema names the choices; the validator (not an enum) gives a refused Hermes
# destination its own reason.
Destination = Annotated[StrictStr, AfterValidator(_destination),
                        WithJsonSchema({"type": "string", "enum": list(DELIVER_CHOICES)})]
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

    @model_validator(mode="after")
    def _somewhere_to_go(self):
        from agents.core.webhooks import delivery_problem

        problem = delivery_problem(self.deliver, self.deliver_only)
        if problem:
            raise ValueError(problem)
        return self


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
    store = _get_webhook_store()
    current = store.get(hook_id)
    if current is not None and ("deliver" in changes or "deliver_only" in changes):
        from agents.core.webhooks import delivery_problem

        problem = delivery_problem(changes.get("deliver", store.destination(current)),
                                   changes.get("deliver_only", store.delivers_only(current)))
        if problem:      # a fixed sentence, not exception text
            return nocache_json({"error": problem}, status_code=422)
    try:
        rec = store.update(hook_id, **changes)
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
    from agents.core import safe_mode
    from agents.core.webhooks import RECEIVER

    if safe_mode.enabled():
        # H490: an owner-configured hook starts agent runs and pushes out; not in safe mode.
        safe_mode.note("outbound_webhooks")
        return nocache_json({"error": "the webhook receiver is off in safe mode"}, status_code=503)
    state = await RECEIVER.astate()
    if state is True:
        return None
    if state is None:
        return nocache_json({"error": "the webhook receiver's state cannot be read"}, status_code=503)
    return nocache_json({"error": "the webhook receiver is off"}, status_code=503)


async def _capped_body(request: Request):
    """The raw body, or None when it is larger than :data:`MAX_BODY_BYTES`."""
    declared = request.headers.get("content-length", "")
    if declared.isascii() and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


#: The router's clock (seconds since the epoch): quiet hours read the local hour from it.
_now = time.time


def _quiet_hours(orch) -> bool:
    """The owner's night, as the jobs read it: ``ambient.quiet_hours_start`` to
    ``ambient.quiet_hours_end`` (22 to 7 by default), hours taken modulo 24, on the
    router's clock."""
    from agents.core.autonomy.jobs import (
        DEFAULT_QUIET_END, DEFAULT_QUIET_START, QUIET_END_SETTING, QUIET_START_SETTING, setting_hour)
    from agents.core.autonomy.schedule_runtime import is_night

    return is_night(time.localtime(_now()).tm_hour,
                    start=setting_hour(orch, QUIET_START_SETTING, DEFAULT_QUIET_START),
                    end=setting_hour(orch, QUIET_END_SETTING, DEFAULT_QUIET_END))


#: Where the whole text of a delivery is kept, by what produced it: ``(the quiet-hours
#: note, the cut note)``. An agent's reply is in its session; the rendered text of a
#: deliver-only hook and a workflow's output are not kept by this route.
_KEPT = {
    True: ("the reply is in the session", "the whole reply is in the session"),
    False: ("the text was not kept", "the rest was not kept"),
}


def _ascii_title(text: str) -> str:
    """*text* as printable ASCII (a letter keeps its base, anything else is "?")."""
    folded = unicodedata.normalize("NFKD", text)
    return "".join(ch if ch.isascii() else "?" for ch in folded if not unicodedata.combining(ch))


#: Characters that render as nothing but are not format or control characters: the
#: combining grapheme joiner, the Hangul fillers, Mongolian variation selectors and the
#: blank braille pattern (review-H153e NIT-1).
_BLANKS = "\u034f\u115f\u1160\u180b\u180c\u180d\u180f\u2800\u3164\uffa0"
#: A zero-width joiner and non-joiner stay (an emoji sequence, a Persian word), and so do
#: a newline and a tab.
_KEPT_FORMAT = "\n\t\u200c\u200d"


def _hidden_class() -> str:
    """Every format (Cf) and control (Cc) character but :data:`_KEPT_FORMAT`, plus
    :data:`_BLANKS`, as one regex character class of ranges: the bidi controls and marks,
    zero-width spaces, word joiners, invisible operators, the soft hyphen, the BOM, the
    interlinear annotation and musical format characters, and the TAG plane (the "ASCII
    smuggling" alphabet). Planes 0, 1 and 14 hold every one of them."""
    points = [cp for plane in (range(0x0000, 0x20000), range(0xE0000, 0xF0000)) for cp in plane
              if (unicodedata.category(chr(cp)) in ("Cf", "Cc") and chr(cp) not in _KEPT_FORMAT)
              or chr(cp) in _BLANKS]
    ranges, start = [], None
    for index, cp in enumerate(points):
        if start is None:
            start = cp
        if index + 1 == len(points) or points[index + 1] != cp + 1:
            ranges.append(re.escape(chr(start)) + ("" if start == cp else "-" + re.escape(chr(cp))))
            start = None
    return "[" + "".join(ranges) + "]"


#: A subdivision flag emoji (🏴, TAG letters, CANCEL TAG: England, Scotland, Wales) is
#: ordinary text, as heartbeat reads it; any other TAG character hides text.
_FLAG_EMOJI = "\U0001F3F4[\U000E0030-\U000E0039\U000E0061-\U000E007A]{1,8}\U000E007F"
_HIDDEN = re.compile(f"({_FLAG_EMOJI})|{_hidden_class()}")
_SURROGATE = re.compile("[\ud800-\udfff]")


def _visible(text: str) -> str:
    """*text* as the owner will read it: nothing hidden, and a lone surrogate (which no
    transport can encode) as U+FFFD. Linear time: no markup is rendered."""
    return _SURROGATE.sub("\ufffd", _HIDDEN.sub(lambda m: m.group(1) or "", text))


def _record(store, hook_id: str, channel: str, ok: bool, reason: str = "") -> dict:
    """Note a delivery's outcome on the hook (a note that cannot be saved is logged, not
    raised: the delivery happened either way) and answer it."""
    try:
        store.mark_delivered(hook_id, channel, ok, reason)
    except Exception:
        logger.warning("webhook %s: the delivery outcome could not be saved", hook_id, exc_info=True)
    return {"channel": channel, "ok": True} if ok else {"channel": channel, "ok": False, "reason": reason}


async def _deliver(orch, store, hook: dict, text: str, event: str, *, in_session: bool) -> dict:
    """Send a delivery's result where the hook says, and note how it went. Never raises:
    whatever fails is recorded on the hook and answered, so a sender is never told 500
    after its turn ran. *in_session* is whether the whole text is in a session (an
    agent's reply) or kept nowhere (deliver-only text, a workflow's output)."""
    try:
        return await _push(orch, store, hook, text, event, in_session=in_session)
    except Exception as exc:
        logger.warning("webhook %s: the delivery failed", hook.get("id"), exc_info=True)
        return _record(store, hook["id"], store.destination(hook), False, f"the delivery failed: {type(exc).__name__}")


async def _push(orch, store, hook: dict, text: str, event: str, *, in_session: bool) -> dict:
    from agents.core.channels import outbound
    from agents.core.webhooks import DELIVER_LOG, PUSH_CHANNELS, PUSHES, RECEIVER, _event_name

    hook_id = hook["id"]
    # The turn can take minutes: what the owner did meanwhile (switched the hook or the
    # receiver off, deleted the hook, moved it to another channel) decides the push.
    live = store.get(hook_id)
    if live is None:
        return {"channel": store.destination(hook), "ok": False,
                "reason": "the hook was deleted before its delivery: not sent"}
    channel = store.destination(live)
    if channel == DELIVER_LOG:
        if store.delivers_only(hook):
            return _record(store, hook_id, channel, False,
                           "deliver only to the log keeps nothing: the text was dropped")
        return _record(store, hook_id, channel, True)
    if not store.is_enabled(live):
        return _record(store, hook_id, channel, False, "the hook was switched off before its delivery: not sent")
    receiver = await RECEIVER.astate()
    if receiver is not True:
        return _record(store, hook_id, channel, False,
                       "the webhook receiver was switched off before this delivery: not sent" if receiver is False
                       else "the webhook receiver's state cannot be read: not sent")
    kept, rest = _KEPT[in_session]
    if channel in PUSH_CHANNELS and _quiet_hours(orch):
        return _record(store, hook_id, channel, False, f"quiet hours: not pushed; {kept}")
    if not PUSHES.allow(hook_id):
        return _record(store, hook_id, channel, False,
                       f"over this hook's push limit ({PUSHES.limit} an hour): not pushed; {kept}")
    label = _event_name(str(live.get("name") or live.get("target") or "webhook"), 80)
    subject = f"Webhook {label}" + (f" - {_event_name(event, 64)}" if event else "")
    if channel == "ntfy":                        # a title is an HTTP header: printable ASCII
        subject = _ascii_title(subject)[:outbound.NTFY_TITLE_CHARS]   # send_to_target strips it
    # The text as written: the sender wrote it, or steered the turn that did, so no
    # markup is rendered (a link shows its address) and nothing is rewritten. Rendering
    # it here cost quadratic time on one long line of a 5 MiB body, on the event loop
    # (H153 fourth review); what is left is linear and cut before it is sent.
    body = _visible(str(text or ""))
    room = outbound.MAX_TEXT_CHARS - len(subject) - 2
    if len(body) > room:
        note = f"… (cut: {rest})"
        body = body[:room - len(note)] + note
    result = await outbound.send_to_target(orch, channel, body, subject=subject, source=f"webhook:{hook_id}",
                                           plain=True)
    ok = bool(result.get("ok"))
    return _record(store, hook_id, channel, ok, "" if ok else str(result.get("reason") or "not delivered"))


def _run_order(pipeline) -> list:
    """The pipeline's steps in the order they run (its batches, in turn), or as listed
    when the order cannot be worked out: a pipeline listed out of dependency order still
    ends with the step that ran last."""
    steps = list(getattr(pipeline, "steps", None) or [])
    batches = getattr(pipeline, "execution_batches", None)
    if callable(batches):
        try:
            ordered = [step for batch in batches() for step in batch]
        except Exception:        # a cycle: the engine refused to run it anyway
            return steps
        if len(ordered) == len(steps):
            return ordered
    return steps


def _steps_that_ran(pipeline, result) -> list[str]:
    """The ids of the steps that left an output, in the order they ran."""
    if not isinstance(result, dict):
        return []
    return [step.id for step in _run_order(pipeline)
            if isinstance(getattr(step, "id", None), str) and result.get(step.id) is not None]


def _workflow_output(pipeline, result) -> tuple[str, str]:
    """``(text, "")``, the last step's output, which is what a workflow run hands on; or
    ``("", why)`` when there is none. A run that failed delivers nothing: an earlier
    step's output is not the run's result. A step with no output did not run (the run
    stopped early), so the last step that ran is the one read."""
    from agents.core.webhooks import _event_name

    if not isinstance(result, dict):
        return "", "the workflow returned no result"
    if result.get("_ok") is False:
        errors = result.get("_errors")
        failed = [_event_name(step, 64) for step in errors if isinstance(step, str)] if isinstance(errors, list) else []
        return "", "the workflow run failed" + (f" at {', '.join(failed)}" if failed else "") + ": nothing delivered"
    for step in reversed(_run_order(pipeline)):
        out = result.get(getattr(step, "id", None))
        if out is None:
            continue
        if isinstance(out, str) and out.startswith("[error:"):
            return "", "the workflow's last step failed: nothing delivered"
        if isinstance(out, str) and out.strip():
            return out, ""
        return "", "the workflow's last step produced no text"
    return "", "the workflow produced no text"


def _encodable(value):
    """*value* as JSON can carry it: a lone surrogate becomes U+FFFD and a number JSON
    has no spelling for (NaN, an infinity) becomes null. The answer to a sender is
    written after its turn ran and its push went out; it must never fail to encode."""
    if isinstance(value, str):
        return _SURROGATE.sub("\ufffd", value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {_encodable(str(key)): _encodable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encodable(item) for item in value]
    if value is None or isinstance(value, (bool, float)):
        return value
    if isinstance(value, int) and abs(value) < 10 ** 4000:
        return value
    # Anything else JSON cannot carry (a date, bytes, a set, an object, an int past the
    # interpreter's digit limit) is answered as its text (review-H153e NIT-3).
    try:
        return _SURROGATE.sub("\ufffd", str(value))
    except Exception:
        return None


def _answer(content: dict, status_code: int = 200):
    return nocache_json(_encodable(content), status_code=status_code)


def _skipped(store, hook_id: str, event: str, reason: str):
    store.mark_skipped(hook_id, event)
    return nocache_json({"ok": True, "skipped": reason}, status_code=202)


@router.post("/api/webhooks/{hook_id}")
async def trigger_webhook(hook_id: str, request: Request):
    """Token-authenticated trigger → runs the configured agent/workflow.

    H659: a delivery that carries an ``Idempotency-Key`` is run once per key and hook; a
    retry gets the first delivery's outcome back (not its reply) and nothing runs again."""
    from agents.core import idempotency

    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    refusal = idempotency.check_header(request)
    if refusal is not None:
        return refusal
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

    # H659 — reserved after authentication (a caller without the token or secret cannot
    # burn a key) and before the delivery is counted, run or sent.
    started = idempotency.begin(request, f"webhook:{hook_id}", raw)
    if started.refusal is not None:
        return started.refusal
    if started.replay is not None:
        return idempotency.replayed(started.replay.ref or {}, started.replay.status_code or 200)
    try:
        response = await _run_delivery(orch, store, hook, live, hook_id, raw, request)
    except BaseException:
        if started.claim is not None:
            started.claim.release()     # the delivery did not finish: its retry runs
        raise
    if started.claim is not None:
        if response.status_code >= 500:
            started.claim.release()
        else:
            started.claim.done(_public_outcome(response), response.status_code)
    return response


def _public_outcome(response) -> dict:
    """What a replayed delivery answers: whether it ran and where, never its reply or steps."""
    try:
        body = json.loads(response.body)
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return {k: body[k] for k in ("ok", "target", "skipped", "error") if isinstance(body.get(k), (bool, str))}


async def _run_delivery(orch, store, hook: dict, live: dict, hook_id: str, raw: bytes, request: Request):
    """Run one authenticated delivery of an enabled hook, as the route did before H659."""
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
        return _skipped(store, hook_id, event,
                        "the prompt template rendered nothing" if template else "the delivery carries no text")
    store.mark_called(hook_id)
    # From here every way out notes the delivery's outcome on the hook, so the detail
    # pane never shows an earlier success for a call that delivered nothing.
    channel = store.destination(live)

    if store.delivers_only(live):
        # Deliver only: the rendered text goes where the hook says, and no turn runs.
        delivery = await _deliver(orch, store, live, text, event, in_session=False)
        return _answer({"ok": True, "target": hook["target"], "delivery": delivery})

    if hook["target_type"] == "agent":
        try:
            reply = await orch.handle_input(text, channel="webhook", agent_override=hook["target"])
        except Exception as exc:
            # The turn did not finish: say so on the hook, and let the sender's retry run it.
            _record(store, hook_id, channel, False, f"the turn failed: {type(exc).__name__}")
            raise
        delivery = await _deliver(orch, store, live, reply if isinstance(reply, str) else str(reply), event,
                                  in_session=True)
        return _answer({"ok": True, "target": hook["target"], "response": reply, "delivery": delivery})

    # workflow target (requires the workflow engine)
    engine = getattr(orch, "workflow_engine", None)
    if engine is None or not hasattr(engine, "run"):
        _record(store, hook_id, channel, False, "workflow execution is not available on this hub")
        return nocache_json({"error": "workflow execution not available"}, status_code=501)
    from agents.core.routers.workflows import resolve_pipeline
    try:
        pipeline = resolve_pipeline(orch, hook["target"])
    except Exception as exc:
        _record(store, hook_id, channel, False, "the stored workflow is invalid")
        return error_json(exc, 200, "invalid stored pipeline", extra={"ok": False, "target": hook["target"]})
    if pipeline is None:
        _record(store, hook_id, channel, False, "workflow not found")
        return nocache_json({"ok": False, "error": "workflow not found", "target": hook["target"]}, status_code=404)
    # The text came from outside, so every step the workflow runs is an inbound turn.
    # The engine runs its steps through handle_input on the ``workflow`` channel,
    # which alone classifies as internal and trusted; bind_turn_action_origin never
    # downgrades an inbound parent, so this binding is what the kernel sees.
    origin_token = bind_action_origin(INBOUND_ACTION_ORIGIN)
    try:
        result = await engine.run(pipeline, initial_input=text)
    except Exception as exc:
        _record(store, hook_id, channel, False, f"the workflow run failed: {type(exc).__name__}")
        return error_json(exc, 200, "workflow run failed", extra={"ok": False, "target": hook["target"]})
    finally:
        reset_action_origin(origin_token)
    try:
        out, why = _workflow_output(pipeline, result)
    except Exception:
        logger.warning("webhook %s: the workflow's output could not be read", hook_id, exc_info=True)
        out, why = "", "the workflow's output could not be read: nothing delivered"
    delivery = (await _deliver(orch, store, live, out, event, in_session=False) if out
                else _record(store, hook_id, channel, False, why))
    ran_ok = result.get("_ok", True) is not False if isinstance(result, dict) else False
    # The steps that ran, never the run's context: it holds the sender's text and every
    # step's output (what the owner's tools returned), and the sender is not the owner.
    return _answer({"ok": ran_ok, "target": hook["target"], "steps": _steps_that_ran(pipeline, result),
                    "delivery": delivery})
