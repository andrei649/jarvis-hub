"""Integrations endpoints (transcripts / write-back / social / webhook channels) — extracted from web.py (CLN-3)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.core.routers._deps import admin_guard, user_guard

from agents.core.web_helpers import nocache_json, safe_reflect
from agents.core.app_state import get_orch


router = APIRouter(tags=["integrations"])


class TranscriptIngestBody(BaseModel):
    transcript: str = Field(..., max_length=200_000)
    source: str = Field("", max_length=200)
    target: str | None = Field(None, max_length=16)   # todoist | notion


@router.post("/api/transcripts/ingest", dependencies=[Depends(user_guard)])
async def transcript_ingest(body: TranscriptIngestBody):
    """H12.25 — meeting transcript → action items → approval queue (governed).

    Nothing is created externally here; each item lands as an ask-tier task the
    owner approves. Without a live queue, returns an extraction-only preview."""
    orch = get_orch()
    from agents.core.autonomy.transcript_watcher import TranscriptWatcher
    q = getattr(orch, "autonomy_queue", None) if orch else None
    watcher = TranscriptWatcher(enqueue=q.enqueue if q is not None else None)
    return nocache_json(watcher.ingest(body.transcript, source=body.source, target=body.target))


class WriteBackBody(BaseModel):
    target: str = Field(..., max_length=40)
    action: str = Field(..., max_length=40)
    fields: dict = Field(default_factory=dict)
    agent: str | None = Field(None, max_length=40)
    source: str = Field("", max_length=120)


@router.get("/api/integrations/writeback", dependencies=[Depends(user_guard)])
async def writeback_targets():
    """H10.30 — list supported governed write-back targets (Notion/GitHub/Calendar)."""
    orch = get_orch()
    from agents.core.writeback import WriteBackBroker
    wb = getattr(orch, "writeback", None) if orch else None
    targets = wb.targets() if wb is not None else WriteBackBroker().targets()
    return nocache_json({"targets": targets})


@router.post("/api/integrations/writeback", dependencies=[Depends(user_guard)])
async def writeback_request(body: WriteBackBody):
    """H10.30 — request a governed write-back into an external system.

    Validates against the allowlist and enqueues an ask-tier task. Nothing is
    written externally here; on approval the autonomy worker dispatches it to the
    write-back executor (credentials resolved at action time, behind approval).
    Without a live queue, returns a validation-only preview."""
    orch = get_orch()
    from agents.core.writeback import WriteBackBroker
    wb = getattr(orch, "writeback", None) if orch else None
    if wb is None:
        q = getattr(orch, "autonomy_queue", None) if orch else None
        wb = WriteBackBroker(enqueue=q.enqueue if q is not None else None)
    result = wb.request(body.target, body.action, body.fields,
                        agent=body.agent, source=body.source)
    return nocache_json(result, status_code=200 if result.get("ok") else 422)


class SocialActionBody(BaseModel):
    platform: str = Field(..., max_length=40)
    action: str = Field(..., max_length=40)
    fields: dict = Field(default_factory=dict)
    agent: str | None = Field(None, max_length=40)
    source: str = Field("", max_length=120)


@router.get("/api/integrations/social", dependencies=[Depends(user_guard)])
async def social_targets():
    """H12.21 — list supported governed social actions (X post/reply/DM)."""
    orch = get_orch()
    from agents.core.social import SocialBroker
    sb = getattr(orch, "social", None) if orch else None
    targets = sb.targets() if sb is not None else SocialBroker().targets()
    return nocache_json({"targets": targets})


@router.post("/api/integrations/social", dependencies=[Depends(user_guard)])
async def social_request(body: SocialActionBody):
    """H12.21 — request a governed social write (X/Twitter post/reply/DM).

    Validates against the allowlist and enqueues an ask-tier task. Nothing is
    posted here; on approval the autonomy worker dispatches it to the social
    executor (OAuth/bearer resolved at action time, behind approval — never raw
    cookies). Without a live queue, returns a validation-only preview."""
    orch = get_orch()
    from agents.core.social import SocialBroker
    sb = getattr(orch, "social", None) if orch else None
    if sb is None:
        q = getattr(orch, "autonomy_queue", None) if orch else None
        sb = SocialBroker(enqueue=q.enqueue if q is not None else None)
    result = sb.request(body.platform, body.action, body.fields,
                        agent=body.agent, source=body.source)
    return nocache_json(result, status_code=200 if result.get("ok") else 422)


class ChannelReplyBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4_000)
    agent: str | None = Field(None, max_length=40)
    source: str = Field("", max_length=120)


def _channel_inbox(orch=None):
    orch = get_orch() if orch is None else orch
    return getattr(orch, "channel_inbox", None) if orch else None


@router.get("/api/channels/inbox/status", dependencies=[Depends(user_guard)])
async def channels_inbox_status():
    """Safe Comms v0: status for the bounded live channel inbox.

    Only telegram/web are considered live reply transports in this wave.
    """
    inbox = _channel_inbox()
    if inbox is None:
        from agents.core.channel_inbox import SUPPORTED_INBOX_CHANNELS
        return nocache_json({"enabled": False, "stats": {
            "enabled": False,
            "channels": sorted(SUPPORTED_INBOX_CHANNELS),
            "threads": 0,
            "messages": 0,
        }})
    return nocache_json({"enabled": True, "stats": inbox.stats()})


@router.get("/api/channels/inbox", dependencies=[Depends(user_guard)])
async def channels_inbox_list(limit: int = 50):
    """Safe Comms v0: list persisted telegram/web inbox threads."""
    inbox = _channel_inbox()
    if inbox is None:
        return nocache_json({"threads": []})
    return nocache_json({"threads": inbox.threads(limit=max(1, min(int(limit or 50), 200)))})


@router.get("/api/channels/inbox/{thread_id}", dependencies=[Depends(user_guard)])
async def channels_inbox_thread(thread_id: str, limit: int = 50):
    """Safe Comms v0: read messages in one persisted inbox thread."""
    inbox = _channel_inbox()
    if inbox is None:
        return JSONResponse({"error": "channel inbox unavailable"}, status_code=503)
    thread = inbox.thread(thread_id)
    if thread is None:
        return JSONResponse({"error": "thread not found"}, status_code=404)
    return nocache_json({
        "thread": thread,
        "messages": inbox.messages(thread_id, limit=max(1, min(int(limit or 50), 200))),
    })


@router.post("/api/channels/inbox/{thread_id}/reply", dependencies=[Depends(user_guard)])
async def channels_inbox_reply(thread_id: str, body: ChannelReplyBody):
    """Safe Comms v0: queue a governed reply to a live telegram/web thread.

    Nothing sends here. The reply is executed only if the owner approves the
    task in the existing autonomy decision inbox.
    """
    orch = get_orch()
    if orch is None:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    broker = getattr(orch, "channel_replies", None)
    if broker is None:
        from agents.core.channel_reply import ChannelReplyBroker
        worker = getattr(orch, "autonomy_worker", None)
        enqueue = getattr(worker, "govern_enqueue", None)
        broker = ChannelReplyBroker(
            inbox=_channel_inbox(orch),
            enqueue=enqueue,
            channel_manager=getattr(orch, "channel_manager", None),
        )
    result = broker.request(thread_id, body.text, agent=body.agent, source=body.source)
    return nocache_json(result, status_code=200 if result.get("ok") else 422)


@router.get("/api/channels/webhook", dependencies=[Depends(user_guard)])
async def channels_webhook_list():
    """H12.16 — supported governed webhook channels + which are live."""
    orch = get_orch()
    from agents.core.channels.webhook_channels import SUPPORTED_CHANNELS, WebhookChannel
    live = []
    if orch and hasattr(orch, "channels"):
        live = [cid for cid, ch in orch.channels.items() if isinstance(ch, WebhookChannel)]
    return nocache_json({"supported": list(SUPPORTED_CHANNELS), "live": live})


@router.get("/api/channels/send-rate-limit", dependencies=[Depends(admin_guard)])
async def channels_send_rate_limit():
    """0.44 read surface: the per-channel OUTBOUND send rate-limiter status —
    configured caps (global + per-channel) and current in-window usage. Reports
    ``enabled: false`` (the default) when no cap is set: sends are unlimited and
    nothing is recorded, so the limiter is byte-identical until an operator opts in
    via JARVIS_CHANNEL_SEND_RATE / JARVIS_CHANNEL_SEND_RATES."""
    from agents.core.channels.send_rate_limit import status_snapshot
    return nocache_json(status_snapshot())


@router.post("/api/channels/{channel_id}/inbound", dependencies=[Depends(user_guard)])
async def channel_inbound(channel_id: str, request: Request):
    """H12.16 — deliver an inbound webhook payload to a governed channel adapter.

    The adapter parses (text, sender) and routes through the governed gateway, so
    the H12.19 pairing gate + rate-limit + guardrails all apply before the
    orchestrator sees the text. (Provider signature verification is the host
    seam — front this with the H16.4 signed-webhook path in production.)"""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    ch = orch.channels.get(channel_id) if hasattr(orch, "channels") else None
    if ch is None or not hasattr(ch, "handle_inbound"):
        return JSONResponse({"error": f"no webhook channel '{safe_reflect(channel_id)}'"}, status_code=404)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    reply = await ch.handle_inbound(payload)
    return nocache_json({"ok": True, "channel": channel_id, "reply": reply})
