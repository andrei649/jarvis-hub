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

import asyncio
import logging
from typing import Any, Callable, Optional
from urllib.parse import quote

from .base import ChannelAdapter

logger = logging.getLogger("jarvis.channels.webhook")

#: How long a Matrix command waits for the homeserver to say whether its room is a DM.
_MATRIX_LOOKUP_SECONDS = 5.0


#: H120 — a provider message id handed to the gateway's dedup window, bounded.
_DEDUP_ID_MAX = 200


def _dedup(channel: str, value: Any) -> dict:
    """``{"dedup_key": "channel:id"}`` for the gateway's duplicate window, or ``{}`` when
    the payload carries no usable id."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return {}
    text = str(value)
    if not text or len(text) > _DEDUP_ID_MAX or not text.isprintable():
        return {}
    return {"dedup_key": f"{channel}:{text}"}


def _matrix_id(value: Any, sigil: str) -> bool:
    """A Matrix room (``!``) or user (``@``) id as the spec bounds it: 255 printable chars."""
    return (isinstance(value, str) and 1 < len(value) <= 255 and value.startswith(sigil)
            and value.isprintable() and not any(ch.isspace() for ch in value))


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
            if not await self.before_send(spec, kwargs):
                return False
        except Exception:
            logger.warning("%s pre-send check failed; not sent", self.channel_id, exc_info=True)
            return False
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
        if self.is_own_message(parsed):
            # H120: our own outbound read back (an echo) is never a turn: on Signal or
            # Matrix it would be a reply loop that runs until a rate limit or a bill.
            self.echoes_dropped = getattr(self, "echoes_dropped", 0) + 1
            logger.info("%s: own message read back, ignored", self.channel_id)
            return None
        parsed = await self.enrich_inbound(parsed)
        meta = {k: v for k, v in parsed.items() if k != "text"}
        return await self.receive(text, **meta)

    def is_own_message(self, parsed: dict) -> bool:
        """H120 provider hook: whether *parsed* was written by this bot itself."""
        own = self.config.get("own_id")
        return isinstance(own, str) and bool(own) and parsed.get("sender") == own

    async def enrich_inbound(self, parsed: dict) -> dict:
        """Provider hook: what the payload alone does not say but the provider's API does
        (Matrix: whether the room is a DM). Never raises; the default adds nothing."""
        return parsed

    async def before_send(self, spec: dict, kwargs: dict) -> bool:
        """Provider hook: a last check before the request leaves (Matrix: never plaintext
        into an end-to-end encrypted room). False drops the send; the default allows it."""
        return True

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


#: H120 — WhatsApp message types that are not something a person said to the agent.
_WHATSAPP_NOT_A_TURN = frozenset({"system", "unsupported", "ephemeral", "revoked"})
_WHATSAPP_BROADCAST_SUFFIXES = ("@broadcast", "@newsletter")


class WhatsAppChannel(WebhookChannel):
    """WhatsApp Cloud API (Meta Graph)."""

    channel_id = "whatsapp"

    def is_own_message(self, parsed):
        return parsed.pop("_own", False) is True or super().is_own_message(parsed)

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
            # Delivery/read `statuses` callbacks carry no message: never a turn.
            return None
        if not isinstance(msg, dict) or msg.get("type") in _WHATSAPP_NOT_A_TURN:
            return None
        text = (msg.get("text") or {}).get("body", "") or (msg.get("button") or {}).get("text", "")
        sender = msg.get("from", "")
        if not text or not isinstance(sender, str) or not sender:
            return None
        if sender.endswith(_WHATSAPP_BROADCAST_SUFFIXES) or sender == "status":
            # H120: status updates, broadcast lists and channels are not conversations.
            return None
        own = ((value.get("metadata") or {}).get("display_phone_number")
               if isinstance(value, dict) else None)
        parsed = {"text": text, "sender": sender, "to": sender,
                  **_dedup("whatsapp", msg.get("id"))}
        if isinstance(own, str) and own and own.lstrip("+") == sender.lstrip("+"):
            parsed["_own"] = True
        if msg.get("group_id"):
            # H058: the Cloud API names the group a participant wrote in; judged in group scope.
            parsed["chat_type"] = "group"
        return parsed


class SignalChannel(WebhookChannel):
    """Signal via the signal-cli REST API (local daemon)."""

    channel_id = "signal"
    _DYNAMIC_HOST_CONFIG_KEYS = ("base_url",)

    def is_own_message(self, parsed):
        number = self.config.get("number")
        return ((isinstance(number, str) and bool(number) and parsed.get("sender") == number)
                or super().is_own_message(parsed))

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
        if env.get("syncMessage") is not None:
            # H120: signal-cli reports what this account sent from another device as a
            # sync message; it is ours, never a turn.
            return None
        data = env.get("dataMessage") or {}
        text = data.get("message", "")
        sender = env.get("source", "") or env.get("sourceNumber", "")
        if not text or not sender:
            return None
        stamp = data.get("timestamp") or env.get("timestamp")
        parsed = {"text": text, "sender": sender, "to": sender,
                  **(_dedup("signal", f"{sender}:{stamp}") if stamp else {})}
        if data.get("groupInfo") or data.get("groupV2"):
            parsed["chat_type"] = "group"   # H058: a group message is judged in group scope
        return parsed


#: H120 — the content field marking a Matrix message this hub sent (namespaced, as the
#: spec asks of custom fields).
MATRIX_ORIGIN_KEY = "io.nerva.origin"


class MatrixChannel(WebhookChannel):
    """Matrix client-server API (any homeserver)."""

    channel_id = "matrix"
    _DYNAMIC_HOST_CONFIG_KEYS = ("homeserver",)
    #: This bot's own user id, from ``/account/whoami`` (read once, on the first command).
    _own_user_id: Optional[str] = None

    def build_send(self, message, kwargs):
        from .matrix_e2ee import quote_room, valid_room_id

        room = kwargs.get("room_id") or self.config.get("default_room")
        hs = (self.config.get("homeserver", "") or "").rstrip("/")
        token = self.config.get("token", "")
        if not hs or not valid_room_id(room):
            return None
        return {"method": "POST",
                "url": f"{hs}/_matrix/client/v3/rooms/{quote_room(room)}/send/m.room.message",
                "headers": {"Authorization": f"Bearer {token}",
                            "Content-Type": "application/json"},
                # H120: an origin field (invisible in clients) marks what this hub
                # sent, so a copy that comes back (another login of the same account, a
                # bridge echoing it) is recognised and never answered.
                "json": {"msgtype": "m.text", "body": message, MATRIX_ORIGIN_KEY: True}}

    def parse_inbound(self, payload):
        events = payload.get("events") if isinstance(payload, dict) else None
        ev = (events[0] if events else payload) or {}
        if ev.get("type") == "m.room.encrypted":
            # H127: an end-to-end encrypted event this hub cannot decrypt is counted and
            # logged, never answered (a plaintext reply would downgrade the room).
            from .matrix_e2ee import note_undecryptable

            room = ev.get("room_id") or self.config.get("default_room") or ""
            note_undecryptable(room if isinstance(room, str) else "")
            return None
        if ev.get("type") not in (None, "m.room.message"):
            return None
        content = ev.get("content") if isinstance(ev.get("content"), dict) else {}
        if content.get(MATRIX_ORIGIN_KEY) is not None:
            self.echoes_dropped = getattr(self, "echoes_dropped", 0) + 1
            return None   # H120: our own message, carried back
        text = (ev.get("content") or {}).get("body", "")
        sender = ev.get("sender", "")
        room = ev.get("room_id", "") or self.config.get("default_room", "")
        if not text or not sender:
            return None
        return {"text": text, "sender": sender, "room_id": room,
                **_dedup("matrix", ev.get("event_id"))}

    def is_own_message(self, parsed):
        """Our own user, or a bridge/appservice account the owner listed in
        ``ignore_users`` (a bridge that relays our replies back would otherwise loop)."""
        sender = parsed.get("sender")
        mine = {self.config.get("user_id"), self._own_user_id}
        ignored = self.config.get("ignore_users") or ()
        if isinstance(ignored, (list, tuple)):
            mine |= {u for u in ignored[:64] if isinstance(u, str)}
        return (isinstance(sender, str) and sender in mine) or super().is_own_message(parsed)

    async def enrich_inbound(self, parsed):
        """H058 — the scope a command is judged in. A room event never says whether its room
        is a DM, so for slash-shaped text (the only text the command gate judges by scope)
        the homeserver is asked: a room whose members are exactly the sender and this bot,
        both joined, is a DM. Anything not proven so — no homeserver or token, an error, a
        timeout, a malformed reply, a third member joined, invited, knocking or banned —
        stays group scope, the less trusted one."""
        text = parsed.get("text")
        if not (isinstance(text, str) and text.lstrip().startswith("/")):
            return parsed
        try:
            direct = await asyncio.wait_for(
                self._direct_room(parsed.get("room_id"), parsed.get("sender")), _MATRIX_LOOKUP_SECONDS)
        except Exception:  # noqa: BLE001 — unknown is group scope
            logger.debug("matrix room membership unavailable; judged as a group", exc_info=True)
            direct = False
        return {**parsed, "chat_type": "private"} if direct is True else parsed

    async def _direct_room(self, room, sender) -> bool:
        hs = (self.config.get("homeserver", "") or "").rstrip("/")
        token = self.config.get("token", "")
        if not (hs and isinstance(token, str) and token
                and _matrix_id(room, "!") and _matrix_id(sender, "@")):
            return False
        if self._own_user_id is None:
            body = await self._get_json(f"{hs}/_matrix/client/v3/account/whoami", token)
            me = body.get("user_id") if body is not None else None
            if not _matrix_id(me, "@"):
                return False
            self._own_user_id = me
        # Every membership but "leave": an invited user can join and read what is said here.
        body = await self._get_json(
            f"{hs}/_matrix/client/v3/rooms/{quote(room, safe='')}/members?not_membership=leave", token)
        chunk = body.get("chunk") if body is not None else None
        if not isinstance(chunk, list):
            return False
        members = {}
        for event in chunk:
            if not isinstance(event, dict) or event.get("type") != "m.room.member":
                return False                   # a reply it cannot read proves nothing
            content, user = event.get("content"), event.get("state_key")
            membership = content.get("membership") if isinstance(content, dict) else None
            if not _matrix_id(user, "@") or not isinstance(membership, str):
                return False
            if membership != "leave":
                members[user] = membership
        return (sender != self._own_user_id
                and members == {sender: "join", self._own_user_id: "join"})

    async def before_send(self, spec, kwargs):
        """H127: never a plaintext message into an end-to-end encrypted room. The room's
        encryption state is asked of the homeserver (unknown = encrypted); while this hub
        cannot encrypt, such a send is refused unless the owner set ``encrypted_rooms`` to
        ``allow_plaintext`` (``matrix_e2ee.send_decision``)."""
        from . import matrix_e2ee

        room = kwargs.get("room_id") or self.config.get("default_room")
        hs = (self.config.get("homeserver", "") or "").rstrip("/")
        token = self.config.get("token", "")
        if not (matrix_e2ee.valid_room_id(room) and hs):
            logger.warning("matrix send refused: room id is not a Matrix room id")
            return False
        state = await matrix_e2ee.room_encryption(await self._get_transport(), hs, token, room)
        decision = matrix_e2ee.send_decision(state, self.config)
        if not decision.allowed:
            logger.warning("matrix send refused in %s: %s", room[:64], decision.reason)
            return False
        if decision.reason == "plaintext_allowed_by_owner":
            logger.info("matrix: plaintext into encrypted room %s (owner allowed)", room[:64])
        return True

    async def _get_json(self, url: str, token: str) -> Optional[dict]:
        transport = await self._get_transport()
        resp = await transport.request("GET", url, headers={"Authorization": f"Bearer {token}"}, json=None)
        if getattr(resp, "status_code", None) != 200:
            return None
        body = resp.json()
        return body if isinstance(body, dict) else None


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
        if payload.get("type") not in (None, "message"):
            return None   # conversationUpdate, typing, invoke …: not something said
        text = payload.get("text", "")
        sender = (payload.get("from") or {}).get("id", "")
        conversation = payload.get("conversation") or {}
        convo = conversation.get("id", "")
        if not text or not sender:
            return None
        recipient = (payload.get("recipient") or {}).get("id")
        if recipient and sender == recipient:
            return None   # H120: the bot's own activity read back
        parsed = {"text": text, "sender": sender, "conversation": convo,
                  **_dedup("teams", payload.get("id"))}
        kind = conversation.get("conversationType")
        if type(kind) is str and kind:
            # H058: a one-to-one chat is a DM; a group chat or a team channel is a group.
            parsed["chat_type"] = "private" if kind == "personal" else "group"
        return parsed


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
        author = msg.get("sender") or payload.get("user") or {}
        sender = (msg.get("sender") or {}).get("name", "") or (payload.get("user") or {}).get("name", "")
        room = payload.get("space") or {}
        space = room.get("name", "")
        if not text or not sender:
            return None
        if isinstance(author, dict) and author.get("type") == "BOT":
            return None   # H120: a bot (this app included) is never a turn
        parsed = {"text": text, "sender": sender, "space": space,
                  **_dedup("google_chat", msg.get("name"))}
        kind = room.get("spaceType") or room.get("type")
        if room.get("singleUserBotDm") is True or kind in {"DIRECT_MESSAGE", "DM"}:
            parsed["chat_type"] = "private"           # H058: a DM with the app
        elif kind in {"GROUP_CHAT", "SPACE", "ROOM"}:
            parsed["chat_type"] = "group"
        return parsed


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
