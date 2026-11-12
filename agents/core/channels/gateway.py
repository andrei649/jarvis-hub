"""
gateway.py — Unified Gateway for all channels.
Single entry point for incoming messages, regardless of source channel.
Provides consistent message routing, rate limiting, and channel health.
"""

import logging
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

from ..action_origin import origin_for_channel
from ..log_safe import log_safe
from ..security import taint
from ..security.quarantine import detect_injection_normalized

logger = logging.getLogger("jarvis.gateway")

#: H120 — how long a provider message id is remembered, and how many are kept.
DEDUP_WINDOW_S = 600.0
DEDUP_MAX = 4096
_DEDUP_KEY_MAX = 256


class Gateway:
    """
    Unified message gateway. All channels (web, voice, telegram) route
    incoming messages through this single entry point before reaching
    the orchestrator. Provides rate limiting, message logging, and
    channel health tracking.
    """

    def __init__(self, handler: Optional[Callable] = None, pairing: Any = None,
                 inbox_store: Any = None, pending_handler: Optional[Callable] = None,
                 pending_callback_handler: Optional[Callable] = None,
                 interrupt_handler: Optional[Callable] = None,
                 command_probe: Optional[Callable] = None):
        self.handler = handler
        # A trusted, pending-only consumer: it cannot start a new model turn.
        self.pending_handler = pending_handler
        self.pending_callback_handler = pending_callback_handler
        self.interrupt_handler = interrupt_handler
        # H058: whether a command is one its sender may not run here (no answer, no audit).
        self.command_probe = command_probe
        # H12.19 — optional inbound sender-pairing gate. When set (and pairing is
        # enabled), unknown senders are held for approval instead of reaching the
        # handler. None → unchanged behavior.
        self.pairing = pairing
        self.inbox_store = inbox_store
        self._channels: dict[str, dict] = {}
        self._rate_limits: dict[str, list[float]] = {}
        self._max_rate = 10
        self._window = 60.0
        # H120: (channel, provider message id) -> first seen, upstream of pairing,
        # the handler and so of the approval queue: a provider retry is one turn.
        self._seen_ids: OrderedDict[tuple[str, str], float] = OrderedDict()

    def register_channel(self, channel_id: str, metadata: dict = None):
        self._channels[channel_id] = {
            "id": channel_id,
            "registered_at": time.time(),
            "last_activity": time.time(),
            "message_count": 0,
            "error_count": 0,
            # Held-by-pairing count (Hermes absorption 5b). A number only: it tells the
            # owner "someone is knocking" on /status without the gateway ever keeping
            # who knocked — the pairing store owns identities, this owns a tally. It
            # counts *holds*, not people: one stranger writing twice is 2, and a
            # silent drop (blocked sender, observe-only group message, gate error) is
            # counted too. The pairing store's pending count is the people figure.
            "held_senders": 0,
            "status": "active",
            **(metadata or {}),
        }
        logger.info("Gateway: channel '%s' registered", log_safe(channel_id))

    def unregister_channel(self, channel_id: str):
        self._channels.pop(channel_id, None)
        self._rate_limits.pop(channel_id, None)
        logger.info("Gateway: channel '%s' unregistered", log_safe(channel_id))

    async def route(self, text: str, channel: str = "web", **kwargs) -> Optional[str]:
        if channel not in self._channels:
            self.register_channel(channel)

        # H120: an adapter that knows the provider's id for this message passes it as
        # `dedup_key`; the same id again within the window (a webhook retry, a
        # redelivery after a reconnect) is dropped before anything else sees it.
        if self.is_duplicate(channel, kwargs.pop("dedup_key", None)):
            self._channels[channel]["duplicates"] = self._channels[channel].get("duplicates", 0) + 1
            logger.info("Gateway: duplicate inbound on '%s' dropped", log_safe(channel))
            return None

        # An observed group message (Hermes absorption 0.4) is recorded, never answered,
        # so it neither spends the reply rate budget nor earns a reply of any kind.
        observe_only = bool(kwargs.get("observe_only"))
        if await self.route_pending(text, channel=channel, **kwargs):
            return ""
        if not observe_only and not self._check_rate_limit(channel):
            logger.warning("Gateway: rate limit exceeded for channel '%s'", log_safe(channel))
            return "Rate limit exceeded. Please wait before sending another message."

        # H12.19 — inbound sender pairing. A `sender` identity (set by the channel)
        # that isn't allowed is held for owner approval; the message never reaches
        # the handler. No pairing gate or no sender → routes as before.
        sender = kwargs.get("sender")
        if channel == "ntfy" and (self.pairing is None or sender is None):
            return None
        if self.pairing is not None and sender is not None:
            try:
                decision = self.pairing.gate_inbound(channel, str(sender),
                                                      code=kwargs.get("pairing_code"))
            except Exception:
                # Fails CLOSED. This used to default to {"allowed": True}: a gate whose
                # store errored admitted the sender it exists to hold. The adversarial
                # audit narrowed the blast radius correctly — a BLOCKED sender cannot get
                # through this way (that path is pure in-memory and cannot raise) and
                # corrupt JSON normalises to {} which already fails closed — so the only
                # reachable case is an unknown first-contact sender during a write
                # failure. That is still the exact sender this gate is for, and holding
                # them costs one re-send while admitting them costs the guarantee.
                # Coverage confirmed these lines were executed by no test at all.
                logger.warning("Gateway: pairing gate error — holding sender", exc_info=True)
                decision = {
                    "allowed": False,
                    "status": "gate_error",
                    "message": None,
                }
            if not decision.get("allowed", True):
                logger.info("Gateway: held unpaired sender on '%s' (status=%s)",
                            log_safe(channel), decision.get('status'))
                # Count the hold, not the message: message_count stays what reached
                # the handler, and the sender identity is never stored here.
                self._channels[channel]["held_senders"] += 1
                return None if observe_only else (decision.get("message") or None)

        self._channels[channel]["message_count"] += 1
        self._channels[channel]["last_activity"] = time.time()

        if not self.handler:
            logger.error("Gateway: no handler registered")
            return None

        try:
            origin = origin_for_channel(channel)
            if channel in {"slack", "discord", "ntfy", "sms"}:
                kwargs["origin"] = origin
            else:
                kwargs.setdefault("origin", origin)
            inbound_meta = self._inbound_meta(channel, text, origin=origin)
            if inbound_meta:
                kwargs.setdefault("_inbound_meta", dict(inbound_meta))
            # Never accept an event-supplied claim about which stored message is
            # being answered. Only the successful inbox write may bind this turn.
            kwargs.pop("_inbox_message_id", None)
            metadata = {**kwargs, **inbound_meta}
            recorded = self._record_inbox(channel, text, sender=sender, metadata=metadata)
            if channel in {"slack", "discord", "ntfy", "sms"}:
                kwargs["_inbox_message_id"] = recorded.get("id", "") if recorded else ""
            from .. import code_interruptions
            admission_token = code_interruptions.bind_admitted_channel(channel)
            try:
                result = await self.handler(text, channel=channel, **kwargs)
            finally:
                code_interruptions.reset_admitted_channel(admission_token)
            self._channels[channel]["last_activity"] = time.time()
            return result
        except Exception as e:
            self._channels[channel]["error_count"] += 1
            logger.error("Gateway: handler error on channel '%s': %s", log_safe(channel), e)
            return None

    async def route_pending(self, text: str, channel: str = "telegram", **kwargs) -> bool:
        """Resolve an already delivered question without spending a new-turn slot.

        Native adapters also call this before chat batching/lanes. No model fallback is
        permitted here; false leaves normal routing responsible for the message.
        """
        target = {"telegram": "chat_id", "slack": "slack_channel", "discord": "channel_id",
                  "ntfy": "ntfy_topic"}.get(channel)
        if (target is None or kwargs.get("observe_only")
                or kwargs.get("pending_input_eligible", True) is not True
                or not isinstance(text, str) or not callable(self.pending_handler)
                or not kwargs.get("sender") or not kwargs.get(target)
                or (channel != "telegram" and self.pairing is None)):
            return False
        try:
            if self.pairing is not None and self.pairing.is_allowed(
                    channel, str(kwargs["sender"])) is not True:
                return False
            consumed = await self.pending_handler(text, channel=channel, **kwargs)
        except Exception:
            logger.warning("Gateway: pending reply not applied on '%s'", log_safe(channel))
            return False
        if consumed is not True:
            return False
        if channel not in self._channels:
            self.register_channel(channel)
        self._channels[channel]["message_count"] += 1
        self._channels[channel]["last_activity"] = time.time()
        return True

    async def route_pending_callback(self, callback: dict, channel: str = "telegram"):
        """Verified pending-only button ingress; never dispatch a model turn."""
        if not isinstance(callback, dict) or not callable(self.pending_callback_handler):
            return None
        if channel in {"slack", "discord"}:
            from .pending_input_workspace import valid_callback

            if not valid_callback(callback, channel) or self.pairing is None:
                return None
            try:
                if self.pairing.is_allowed(channel, callback["sender"]) is not True:
                    return None
                return await self.pending_callback_handler(callback, channel=channel)
            except Exception:
                logger.warning("Gateway: workspace pending callback not applied")
                return None
        if channel != "telegram":
            return None
        sender = callback.get("from")
        message = callback.get("message")
        if not isinstance(sender, dict) or not isinstance(message, dict):
            return None
        chat = message.get("chat")
        uid = sender.get("id")
        if (type(uid) is not int or uid <= 0 or not isinstance(chat, dict)
                or type(chat.get("id")) is not int or chat["id"] == 0):
            return None
        try:
            if self.pairing is not None and self.pairing.is_allowed("telegram", str(uid)) is not True:
                return None
            return await self.pending_callback_handler(callback)
        except Exception:
            logger.warning("Gateway: pending callback not applied")
            return None

    def is_duplicate(self, channel: str, key, *, now: float | None = None) -> bool:
        """H120 — True when *key* was already seen on *channel* within the window (and
        remember it otherwise). A missing or malformed key is never a duplicate."""
        if (not isinstance(key, str) or not key or len(key) > _DEDUP_KEY_MAX
                or not key.isprintable()):
            return False
        now = time.monotonic() if now is None else now
        seen = self._seen_ids
        while seen:
            oldest_key, oldest = next(iter(seen.items()))
            if now - oldest <= DEDUP_WINDOW_S and len(seen) <= DEDUP_MAX:
                break
            seen.pop(oldest_key)
        ident = (str(channel), key)
        if ident in seen:
            return True
        seen[ident] = now
        if len(seen) > DEDUP_MAX:
            seen.popitem(last=False)
        return False

    def _check_rate_limit(self, channel: str) -> bool:
        now = time.time()
        if channel not in self._rate_limits:
            self._rate_limits[channel] = []
        self._rate_limits[channel] = [
            t for t in self._rate_limits[channel] if now - t < self._window
        ]
        if len(self._rate_limits[channel]) >= self._max_rate:
            return False
        self._rate_limits[channel].append(now)
        return True

    def pre_lane_interrupt(self, *, channel: str, sender: str, chat_id,
                           message_thread_id=None, text: str = "", chat_type=None) -> bool:
        """Probe Telegram's current admission before its occupied chat lane.

        This does not reserve a rate slot or pair anyone. The later route still
        makes the actual admission decision against then-current state. *text* is the
        admitted message: a ``/btw`` side question (H414) asks beside the running work and
        never signals it, so it is not probed at all. *chat_type* rides along so the
        handler can tell a command this sender may not run (H058), which signals nothing.
        """
        if channel != "telegram" or not callable(self.interrupt_handler):
            return False
        from ..commands import side_question_command_name

        if side_question_command_name(text) is not None:
            return False
        now = time.time()
        if sum(now - stamp < self._window for stamp in self._rate_limits.get(channel, ())) >= self._max_rate:
            return False
        try:
            if self.pairing is not None and self.pairing.is_allowed(channel, str(sender)) is not True:
                return False
            return bool(self.interrupt_handler(
                channel=channel, sender=str(sender), chat_id=chat_id,
                message_thread_id=message_thread_id, text=text, chat_type=chat_type))
        except Exception:
            logger.warning("Telegram pre-lane code interruption unavailable", exc_info=True)
            return False

    def pre_lane_refused(self, *, channel: str, sender: str, chat_id, text: str = "",
                         chat_type=None) -> bool:
        """H058 — probe, before a chat lane, whether *text* is a command its admitted sender
        may not run here. Such a command changes nothing, so the adapter hands it over beside
        the lane instead of behind the running turn, and ``channel_handler`` answers its
        audited refusal at once (the busy path). This reserves nothing and pairs no one; the
        later route still makes the admission decision, and an unpaired sender is never
        probed."""
        if not callable(self.command_probe):
            return False
        try:
            if self.pairing is not None and self.pairing.is_allowed(channel, str(sender)) is not True:
                return False
            return self.command_probe(channel=channel, sender=str(sender), chat_id=chat_id,
                                      chat_type=chat_type, text=text) is True
        except Exception:
            logger.warning("pre-lane command access probe unavailable", exc_info=True)
            return False

    def get_channel_info(self, channel_id: str = None) -> dict:
        if channel_id:
            return self._channels.get(channel_id, {})
        return dict(self._channels)

    def get_summary(self) -> dict:
        return {
            "channels": list(self._channels.keys()),
            "total_messages": sum(c["message_count"] for c in self._channels.values()),
            "total_errors": sum(c["error_count"] for c in self._channels.values()),
            "total_held": sum(c.get("held_senders", 0) for c in self._channels.values()),
            "active_channels": sum(1 for c in self._channels.values() if c["status"] == "active"),
        }

    def set_rate_limit(self, max_per_minute: int):
        self._max_rate = max_per_minute

    @staticmethod
    def _inbound_meta(channel: str, text: str, *, origin: str) -> dict:
        if origin != "inbound":
            return {}
        source = f"inbound:{str(channel or '').strip().lower() or 'unknown'}"
        meta = taint.mark({}, source=source)
        # H117: scanned normalised too (whitespace collapsed, invisible characters taken
        # out), so a payload split across the pieces of a batched burst (or across lines,
        # or by a zero-width space) reads as the sentence it is.
        meta["injection_flags"] = detect_injection_normalized(str(text or ""))
        return meta

    def _record_inbox(self, channel: str, text: str, *, sender: Any = None,
                      metadata: dict | None = None) -> dict | None:
        if self.inbox_store is None or not hasattr(self.inbox_store, "record_inbound"):
            return
        try:
            return self.inbox_store.record_inbound(
                channel,
                text,
                sender="" if sender is None else str(sender),
                metadata=metadata or {},
            )
        except Exception:
            logger.debug("Gateway: channel inbox record failed", exc_info=True)
