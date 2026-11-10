"""
manager.py — ChannelManager: the channel registry + per-channel I/O (CLN-2).

Extracted from the Orchestrator god-object so the "which channels exist and how we
start/stop/send on them" concern is decoupled from orchestration lifecycle. The
Orchestrator keeps a `channels` property that delegates here, so existing
`orch.channels[...]` access is unchanged.
"""

import asyncio
import logging
import re
import time
from typing import Any

from ..automation_contracts import ContractTemplate, contract_denial, predicate
from . import delivery_ledger
from .base import ChannelAdapter
from ..errors import E_CHANNEL_START_FAIL
from ..log import log_error
from .pending_input_workspace import valid_markup, valid_receipt

logger = logging.getLogger("jarvis.channels.manager")

CHANNEL_SEND_CONTRACT_KIND = "channel.send"
CHANNEL_REPLY_TRANSPORT_CONTRACT_KIND = "channel.reply.transport"
_SAFE_CONTRACT_TOKEN = re.compile(r"^[A-Za-z0-9_.:/@\-]{1,200}$")
# Generic orchestrator responses are intentionally limited to channels whose
# direct-send posture predates Safe Comms. Email is excluded: inbound email is
# untrusted input and may only reach SMTP through the governed channel-reply
# executor below.
_SUPPORTED_SEND_CHANNELS = frozenset({"telegram", "web", "voice", "ntfy"})
_SUPPORTED_REPLY_CHANNELS = frozenset({"telegram", "web", "email", "slack", "discord", "ntfy"})


#: H081 — which send kwarg names the chat a reply goes to, per channel (for the ledger
#: row and the dead-target registry). A channel with no per-chat target is "default".
_TARGET_KEYS = {
    "telegram": ("chat_id",),
    "web": ("client_id",),
    "slack": ("slack_channel",),
    "discord": ("channel_id",),
    "email": ("to",),
    "ntfy": ("ntfy_topic",),
}


def _delivery_target(channel: str, adapter, kwargs: dict) -> str:
    for key in _TARGET_KEYS.get(channel, ()):
        value = kwargs.get(key)
        if value not in (None, ""):
            return str(value)
    if channel == "ntfy":
        return str(getattr(adapter, "publish_topic", "") or "default")
    return "default"


def _delivery_text(response) -> str:
    text = getattr(response, "text", None)
    return text if isinstance(text, str) else str(response if response is not None else "")


def _safe_contract_token(value: Any) -> bool:
    return bool(_SAFE_CONTRACT_TOKEN.match(str(value or "")))


def _safe_kwarg_keys(view, now) -> bool:
    keys = view.get("kwarg_keys")
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        return False
    return keys == sorted(keys) and all(_safe_contract_token(k) for k in keys)


def _send_shape_valid(view, now) -> bool:
    return (
        view.get("kind") == CHANNEL_SEND_CONTRACT_KIND
        and view.get("channel") in _SUPPORTED_SEND_CHANNELS
        and _safe_contract_token(view.get("channel"))
    )


def _reply_shape_valid(view, now) -> bool:
    return (
        view.get("kind") == CHANNEL_REPLY_TRANSPORT_CONTRACT_KIND
        and view.get("channel") in _SUPPORTED_REPLY_CHANNELS
        and _safe_contract_token(view.get("channel"))
    )


def _message_len_valid(view, now) -> bool:
    length = view.get("message_len")
    return isinstance(length, int) and not isinstance(length, bool) and length >= 0


def _kwarg_count_valid(view, now) -> bool:
    count = view.get("kwarg_count")
    return isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= 32


def _channel_send_contract_template() -> ContractTemplate:
    return ContractTemplate(
        kind=CHANNEL_SEND_CONTRACT_KIND,
        description="Generic channel-send transport gate.",
        constraints=(
            predicate("send_shape_valid", _send_shape_valid, reason="invalid_shape"),
            predicate("kwarg_keys_safe", _safe_kwarg_keys, reason="bad_kwarg_keys"),
            predicate("message_len_valid", _message_len_valid, reason="bad_message_len"),
            predicate("kwarg_count_valid", _kwarg_count_valid, reason="bad_kwarg_count"),
        ),
        requires_approval=False,
    )


def _channel_reply_transport_contract_template() -> ContractTemplate:
    return ContractTemplate(
        kind=CHANNEL_REPLY_TRANSPORT_CONTRACT_KIND,
        description="Transport gate used only by the governed channel.reply executor.",
        constraints=(
            predicate("reply_shape_valid", _reply_shape_valid, reason="invalid_shape"),
            predicate("kwarg_keys_safe", _safe_kwarg_keys, reason="bad_kwarg_keys"),
            predicate("message_len_valid", _message_len_valid, reason="bad_message_len"),
            predicate("kwarg_count_valid", _kwarg_count_valid, reason="bad_kwarg_count"),
        ),
        requires_approval=False,
    )


CHANNEL_SEND_CONTRACT = _channel_send_contract_template()
CHANNEL_REPLY_TRANSPORT_CONTRACT = _channel_reply_transport_contract_template()


class ChannelManager:
    def __init__(self):
        self.channels: dict[str, ChannelAdapter] = {}
        self._notices: set = set()

    def register(self, channel: ChannelAdapter) -> None:
        self.channels[channel.channel_id] = channel
        health = getattr(channel, "health", None)
        if health is not None and hasattr(health, "on_fatal"):
            cid = channel.channel_id
            health.on_fatal = lambda reason, cid=cid: self._fatal_notice(cid, reason)
        logger.info(f"Channel registered: {channel.channel_id}")

    def get(self, channel_id: str):
        return self.channels.get(channel_id)

    async def start_all(self) -> None:
        # H081: close the ledger rows a previous process left open (never resent).
        store = delivery_ledger.store()
        if store is not None:
            try:
                store.recover()
            except Exception:
                logger.warning("Delivery ledger recovery failed", exc_info=True)
        for cid, ch in self.channels.items():
            try:
                await ch.start()
            except Exception as e:
                log_error(logger, E_CHANNEL_START_FAIL, name=cid, detail=str(e))

    async def stop_all(self) -> None:
        """Stop every channel, each within CHANNEL_STOP_BUDGET (H677): one that hangs is
        named and left behind, never allowed to hold the rest of shutdown."""
        from agents.core.lifecycle_budget import CHANNEL_STOP_BUDGET, bounded

        for cid, ch in list(self.channels.items()):
            await bounded(ch.stop(), CHANNEL_STOP_BUDGET, f"channel {cid} stop")

    def _fatal_notice(self, channel_id: str, reason: str) -> None:
        """H100 — a channel went fatal (a refused token): tell the owner on another channel
        that can still reach them (ntfy, or the owner's Telegram chat), once per transition.
        Best effort, never awaited by the failing channel."""
        from .outbound import resolve_destination

        text = (f"Nerva's {channel_id} channel stopped: the service refused its credentials "
                f"({reason}). Fix them; Nerva looks again every 10 minutes.")
        for other in ("ntfy", "telegram"):
            adapter = self.channels.get(other)
            health = getattr(adapter, "health", None)
            if (other == channel_id or adapter is None or not getattr(adapter, "_running", False)
                    or getattr(health, "state", None) == "fatal"):
                continue
            kwargs, _why = resolve_destination(self, other)
            if kwargs is None:
                continue
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            task = loop.create_task(self.send(other, text, voice=False, plain=True, **kwargs))
            self._notices.add(task)
            task.add_done_callback(self._notices.discard)
            return
        logger.error("Channel %s is fatal (%s) and no other channel can tell the owner",
                     channel_id, reason)

    async def send(self, channel: str, response, **kwargs) -> bool:
        """Dispatch a generic response on a direct-send channel.

        Email is deliberately not a generic direct-send channel. An inbound email
        passes through Orchestrator.channel_handler(), which calls this method; keeping
        email out of this API prevents untrusted inbound mail from creating an SMTP
        side effect without the `channel.reply` approval path.
        """
        ch = self.channels.get(channel)
        if not ch:
            return False
        delivery_key = kwargs.pop("delivery_key", None)
        if self._contract_denial(channel, response, kwargs) is not None:
            return False
        if channel in ("telegram", "web", "ntfy"):
            # ntfy: outbound-only push (Hermes absorption 4g); title / priority ride in kwargs.
            return await self._ledgered(channel, ch, response, kwargs, delivery_key,
                                        lambda: ch.send(response, **kwargs))
        elif channel == "voice":
            return await self._ledgered(channel, ch, response, kwargs, delivery_key,
                                        lambda: ch.send(response))
        return False

    async def _ledgered(self, channel: str, adapter, response, kwargs: dict,
                        delivery_key, send) -> bool:
        """H081 — one send with its ledger row: pending, attempting, then sent / failed /
        partial / unknown. A dead target or a duplicate ``delivery_key`` is not sent (a
        duplicate of a delivered send answers True). The ledger is best effort: if it
        cannot be written the send still goes out."""
        store = delivery_ledger.store()
        target = _delivery_target(channel, adapter, kwargs)
        delivery = None
        if store is not None:
            try:
                delivery = store.open_delivery(channel, target, _delivery_text(response),
                                               key=delivery_key if isinstance(delivery_key, str) else None)
            except Exception:
                logger.warning("Delivery ledger unavailable; sending without a receipt", exc_info=True)
        if delivery is not None and not delivery.send:
            return delivery.already_sent
        outcome, token = delivery_ledger.begin_outcome()
        try:
            if delivery is not None:
                delivery.attempting()
            try:
                ok = bool(await send())
            except BaseException as exc:
                if delivery is not None:
                    delivery.raised(exc)
                raise
        finally:
            delivery_ledger.end_outcome(token)
        if delivery is not None:
            delivery.finished(ok, outcome)
        try:
            if store is not None and ok:
                store.clear_dead(channel, target)
            elif store is not None and outcome.dead and target != "default":
                store.mark_dead(channel, target, outcome.kind or "gone")
        except Exception:
            logger.warning("Dead-target registry unavailable", exc_info=True)
        health = getattr(adapter, "health", None)
        if (outcome.fatal and health is not None and hasattr(health, "failed_fatally")
                and getattr(health, "state", None) != "healthy"):
            # H100: the platform refused the credential on a send of a channel with no
            # healthy poll proving otherwise (ntfy's publish): show it, do not hide it.
            health.failed_fatally(outcome.fatal)
        return ok

    async def send_pending_card(self, channel: str, response, markup: dict, **kwargs) -> int | None:
        """Direct Telegram prompt delivery through the existing send contract.

        A verified Bot API message receipt is required to bind buttons. Workspace
        channels retain their governed reply path; this API cannot send to them.
        """
        ch = self.channels.get(channel)
        send = getattr(ch, "send_pending_card", None)
        if (channel != "telegram" or not callable(send) or type(markup) is not dict
                or self._contract_denial(channel, response, {**kwargs, "reply_markup": markup})
                is not None):
            return None
        receipt = await send(response, reply_markup=markup, **kwargs)
        return receipt if type(receipt) is int and receipt > 0 else None

    async def send_channel_reply(self, channel: str, response, **kwargs) -> bool:
        """Dispatch an already-governed `channel.reply` task.

        This is the transport seam consumed by ChannelReplyBroker.execute after the
        durable approval/Ultron path. It is intentionally separate from `send()` so
        merely registering an EmailChannel cannot make inbound email auto-send SMTP.
        """
        ch = self.channels.get(channel)
        if not ch:
            return False
        delivery_key = kwargs.pop("delivery_key", None)
        if self._reply_contract_denial(channel, response, kwargs) is not None:
            return False
        if channel == "ntfy":
            return await self._ledgered(channel, ch, response, kwargs, delivery_key,
                                        lambda: ch.send_reply(response, **kwargs))
        if channel in _SUPPORTED_REPLY_CHANNELS:
            return await self._ledgered(channel, ch, response, kwargs, delivery_key,
                                        lambda: ch.send(response, **kwargs))
        return False

    async def send_channel_prompt(self, channel: str, response, markup: dict, **kwargs) -> dict | None:
        """Native transport used only by the governed channel.reply executor."""
        adapter = self.channels.get(channel)
        send = getattr(adapter, "send_pending_card", None)
        if (channel not in {"slack", "discord"} or not callable(send) or not valid_markup(markup)
                or self._reply_contract_denial(channel, response, kwargs) is not None):
            return None
        receipt = await send(response, reply_markup=markup, **kwargs)
        return receipt if valid_receipt(receipt) and receipt["channel"] == channel else None

    async def send_channel_text_prompt(self, channel: str, response, *, current, **kwargs) -> bool:
        """Text-only prompt transport, consumed by the governed reply executor."""
        adapter = self.channels.get(channel)
        send = getattr(adapter, "send_reply", None)
        if (channel != "ntfy" or not callable(send) or not callable(current)
                or self._reply_contract_denial(channel, response, kwargs) is not None):
            return False
        return await send(response, current=current, plain=True, **kwargs) is True

    def discard_pending_card(self, channel: str, receipt: dict):
        discard = getattr(self.channels.get(channel), "discard_pending_card", None)
        if callable(discard) and valid_receipt(receipt) and receipt["channel"] == channel:
            discard(receipt)

    @staticmethod
    def _contract_payload_for(kind: str, channel: str, response, kwargs: dict) -> dict:
        keys = sorted(str(k) for k in kwargs)
        return {
            "kind": kind,
            "channel": channel,
            "message_len": len(str(response or "")),
            "kwarg_keys": keys,
            "kwarg_count": len(keys),
        }

    def _contract_payload(self, channel: str, response, kwargs: dict) -> dict:
        return self._contract_payload_for(CHANNEL_SEND_CONTRACT_KIND, channel, response, kwargs)

    def _reply_contract_payload(self, channel: str, response, kwargs: dict) -> dict:
        return self._contract_payload_for(
            CHANNEL_REPLY_TRANSPORT_CONTRACT_KIND, channel, response, kwargs
        )

    def _contract_denial(self, channel: str, response, kwargs: dict) -> str | None:
        try:
            decision = CHANNEL_SEND_CONTRACT.evaluate(
                self._contract_payload(channel, response, kwargs),
                now=time.time(),
            )
        except Exception:
            logger.warning(
                "channel-send contract evaluation failed for %s",
                channel,
                exc_info=True,
            )
            return "contract_error"
        return contract_denial(decision)

    def _reply_contract_denial(self, channel: str, response, kwargs: dict) -> str | None:
        try:
            decision = CHANNEL_REPLY_TRANSPORT_CONTRACT.evaluate(
                self._reply_contract_payload(channel, response, kwargs),
                now=time.time(),
            )
        except Exception:
            logger.warning(
                "channel-reply transport contract evaluation failed for %s",
                channel,
                exc_info=True,
            )
            return "contract_error"
        return contract_denial(decision)
