"""
webhook_channels.py — H12.16 Broaden governed channels.

A family of HTTP/webhook-based channel adapters (WhatsApp, Signal, Matrix,
Microsoft Teams, Google Chat) that plug into the SAME governed gateway as the
existing channels. The governance guarantee is the whole point: every inbound
message threads its ``sender`` so the H12.19 pairing gate, the per-channel
rate-limit, and the guardrails all apply; outbound sends go through an
INJECTABLE HTTP transport, so this layer is fully offline-testable with the real
network call deferred to a host-side seam.

Each provider differs only in two pure functions — how an outbound message maps
onto an HTTP request (:meth:`build_send`) and how an inbound webhook payload maps
onto ``(text, sender, …)`` (:meth:`parse_inbound`) — mirroring the
write-back/social ``build_request`` pattern.

iMessage is intentionally excluded: it is macOS/host bound with no clean HTTP
surface and belongs to a host bridge, not this layer.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from .base import ChannelAdapter

logger = logging.getLogger("jarvis.channels.webhook")


class WebhookChannel(ChannelAdapter):
    """Base for HTTP/webhook channels: governed inbound + injectable outbound."""

    channel_id = "webhook"

    # SEC-5b: config keys whose value carries this channel's egress host (e.g.
    # Signal ``base_url``, Matrix ``homeserver``). Registered with the egress
    # gate at init so a config-driven host is allowed without a FULL escape.
    _DYNAMIC_HOST_CONFIG_KEYS: "tuple[str, ...]" = ()

    def __init__(self, handler: Optional[Callable] = None,
                 config: Optional[dict] = None, transport=None) -> None:
        super().__init__(self.channel_id, handler)
        self.config = config or {}
        self._transport = transport  # async request(method, url, headers=, json=)
        for key in self._DYNAMIC_HOST_CONFIG_KEYS:
            val = self.config.get(key)
            if val:
                from ..plugin_gate import register_dynamic_domain
                register_dynamic_domain(f"channel_{self.channel_id}", val)

    async def start(self):
        # Webhook-driven: inbound arrives via the HTTP endpoint, no poll loop.
        self._running = True

    async def stop(self):
        self._running = False
        t = self._transport
        if t is not None and hasattr(t, "aclose"):
            try:
                await t.aclose()
            except Exception:  # pragma: no cover - best-effort
                logger.warning("%s transport close failed", self.channel_id, exc_info=True)

    async def send(self, message: str, **kwargs) -> bool:
        # 0.44: opt-in per-channel outbound rate limit (default-off — unlimited
        # unless JARVIS_CHANNEL_SEND_RATE[S] is set). Scoped to these external
        # broadcast channels; the interactive reply path is never limited.
        from .send_rate_limit import allow_send
        if not allow_send(self.channel_id):
            logger.warning("%s outbound send rate-limited — dropped (raise "
                           "JARVIS_CHANNEL_SEND_RATE[S] to allow more)", self.channel_id)
            return False
        try:
            spec = self.build_send(message, kwargs)
        except Exception:
            logger.warning("%s build_send failed", self.channel_id, exc_info=True)
            return False
        if not spec:
            logger.warning("%s send skipped — incomplete config/target", self.channel_id)
            return False
        transport = await self._get_transport()
        try:
            resp = await transport.request(spec["method"], spec["url"],
                                           headers=spec.get("headers"), json=spec.get("json"))
            if hasattr(resp, "raise_for_status"):
                resp.raise_for_status()
            return True
        except Exception:
            logger.warning("%s send failed", self.channel_id, exc_info=True)
            return False

    async def handle_inbound(self, payload) -> Optional[str]:
        """Parse a provider webhook payload and route it through the gateway.

        ``receive()`` forwards to the gateway with ``channel`` + ``sender`` set,
        so pairing / rate-limit / guardrails all apply before the orchestrator
        ever sees the text.
        """
        try:
            parsed = self.parse_inbound(payload)
        except Exception:
            logger.warning("%s parse_inbound failed", self.channel_id, exc_info=True)
            return None
        if not parsed:
            return None
        text = parsed.get("text", "")
        if not text:
            return None
        meta = {k: v for k, v in parsed.items() if k != "text"}
        return await self.receive(text, **meta)

    async def _get_transport(self):
        if self._transport is None:  # pragma: no cover - real network path
            from ..http_client import PluginHTTPClient
            self._transport = PluginHTTPClient.for_plugin(f"channel_{self.channel_id}")
        return self._transport

    # provider hooks ----------------------------------------------------------
    def build_send(self, message: str, kwargs: dict) -> Optional[dict]:
        raise NotImplementedError

    def parse_inbound(self, payload: dict) -> Optional[dict]:
        raise NotImplementedError


class WhatsAppChannel(WebhookChannel):
    """WhatsApp Cloud API (Meta Graph)."""

    channel_id = "whatsapp"

    def build_send(self, message, kwargs):
        to = kwargs.get("to") or self.config.get("default_to")
        phone_id = self.config.get("phone_id")
        token = self.config.get("token", "")
        if not to or not phone_id:
            return None
        return {"method": "POST",
                "url": f"https://graph.facebook.com/v20.0/{phone_id}/messages",
                "headers": {"Authorization": f"Bearer {token}",
                            "Content-Type": "application/json"},
                "json": {"messaging_product": "whatsapp", "to": to,
                         "type": "text", "text": {"body": message}}}

    def parse_inbound(self, payload):
        try:
            value = payload["entry"][0]["changes"][0]["value"]
            msg = value["messages"][0]
        except (KeyError, IndexError, TypeError):
            return None
        text = (msg.get("text") or {}).get("body", "") or (msg.get("button") or {}).get("text", "")
        sender = msg.get("from", "")
        if not text or not sender:
            return None
        return {"text": text, "sender": sender, "to": sender}


class SignalChannel(WebhookChannel):
    """Signal via the signal-cli REST API (local daemon)."""

    channel_id = "signal"
    _DYNAMIC_HOST_CONFIG_KEYS = ("base_url",)

    def build_send(self, message, kwargs):
        base = (self.config.get("base_url", "") or "").rstrip("/")
        number = self.config.get("number")
        to = kwargs.get("to") or self.config.get("default_to")
        if not base or not number or not to:
            return None
        return {"method": "POST", "url": f"{base}/v2/send",
                "headers": {"Content-Type": "application/json"},
                "json": {"message": message, "number": number, "recipients": [to]}}

    def parse_inbound(self, payload):
        env = payload.get("envelope", payload) or {}
        text = (env.get("dataMessage") or {}).get("message", "")
        sender = env.get("source", "") or env.get("sourceNumber", "")
        if not text or not sender:
            return None
        return {"text": text, "sender": sender, "to": sender}


class MatrixChannel(WebhookChannel):
    """Matrix client-server API (any homeserver)."""

    channel_id = "matrix"
    _DYNAMIC_HOST_CONFIG_KEYS = ("homeserver",)

    def build_send(self, message, kwargs):
        room = kwargs.get("room_id") or self.config.get("default_room")
        hs = (self.config.get("homeserver", "") or "").rstrip("/")
        token = self.config.get("token", "")
        if not room or not hs:
            return None
        return {"method": "POST",
                "url": f"{hs}/_matrix/client/v3/rooms/{room}/send/m.room.message",
                "headers": {"Authorization": f"Bearer {token}",
                            "Content-Type": "application/json"},
                "json": {"msgtype": "m.text", "body": message}}

    def parse_inbound(self, payload):
        events = payload.get("events") if isinstance(payload, dict) else None
        ev = (events[0] if events else payload) or {}
        if ev.get("type") not in (None, "m.room.message"):
            return None
        text = (ev.get("content") or {}).get("body", "")
        sender = ev.get("sender", "")
        room = ev.get("room_id", "") or self.config.get("default_room", "")
        if not text or not sender:
            return None
        return {"text": text, "sender": sender, "room_id": room}


class TeamsChannel(WebhookChannel):
    """Microsoft Teams — outbound via incoming webhook; inbound via Bot activity."""

    channel_id = "teams"
    # A config-supplied webhook host is registered too; the manifest's static
    # allowlist covers the common Microsoft hosts for kwargs-supplied webhooks.
    _DYNAMIC_HOST_CONFIG_KEYS = ("webhook",)

    def build_send(self, message, kwargs):
        url = kwargs.get("webhook") or self.config.get("webhook")
        if not url:
            return None
        return {"method": "POST", "url": url,
                "headers": {"Content-Type": "application/json"},
                "json": {"text": message}}

    def parse_inbound(self, payload):
        text = payload.get("text", "")
        sender = (payload.get("from") or {}).get("id", "")
        convo = (payload.get("conversation") or {}).get("id", "")
        if not text or not sender:
            return None
        return {"text": text, "sender": sender, "conversation": convo}


class GoogleChatChannel(WebhookChannel):
    """Google Chat — outbound via incoming webhook; inbound via event payload."""

    channel_id = "google_chat"

    def build_send(self, message, kwargs):
        url = kwargs.get("webhook") or self.config.get("webhook")
        if not url:
            return None
        return {"method": "POST", "url": url,
                "headers": {"Content-Type": "application/json"},
                "json": {"text": message}}

    def parse_inbound(self, payload):
        msg = payload.get("message", {}) or {}
        text = msg.get("text", "") or payload.get("text", "")
        sender = (msg.get("sender") or {}).get("name", "") or (payload.get("user") or {}).get("name", "")
        space = (payload.get("space") or {}).get("name", "")
        if not text or not sender:
            return None
        return {"text": text, "sender": sender, "space": space}


_REGISTRY: "dict[str, type[WebhookChannel]]" = {
    "whatsapp": WhatsAppChannel,
    "signal": SignalChannel,
    "matrix": MatrixChannel,
    "teams": TeamsChannel,
    "google_chat": GoogleChatChannel,
}

SUPPORTED_CHANNELS = tuple(_REGISTRY)


def build_channel(kind: str, handler: Optional[Callable] = None,
                  config: Optional[dict] = None, transport=None) -> Optional[WebhookChannel]:
    """Construct a governed webhook channel by kind, or None if unsupported."""
    cls = _REGISTRY.get((kind or "").lower())
    if cls is None:
        return None
    return cls(handler=handler, config=config or {}, transport=transport)


def channels_from_config(raw: Optional[dict], handler: Callable) -> "list[WebhookChannel]":
    """Build all configured webhook channels from a ``{kind: config}`` mapping."""
    out: list[WebhookChannel] = []
    for kind, cfg in (raw or {}).items():
        ch = build_channel(kind, handler=handler, config=cfg or {})
        if ch is not None:
            out.append(ch)
        else:
            logger.warning("unknown webhook channel kind ignored: %s", kind)
    return out
