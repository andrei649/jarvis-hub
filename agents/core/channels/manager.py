"""
manager.py — ChannelManager: the channel registry + per-channel I/O (CLN-2).

Extracted from the Orchestrator god-object so the "which channels exist and how we
start/stop/send on them" concern is decoupled from orchestration lifecycle. The
Orchestrator keeps a `channels` property that delegates here, so existing
`orch.channels[...]` access is unchanged.
"""

import logging
import re
import time
from typing import Any

from ..automation_contracts import ContractTemplate, contract_denial, predicate
from .base import ChannelAdapter
from ..errors import E_CHANNEL_START_FAIL
from ..log import log_error

logger = logging.getLogger("jarvis.channels.manager")

CHANNEL_SEND_CONTRACT_KIND = "channel.send"
CHANNEL_REPLY_TRANSPORT_CONTRACT_KIND = "channel.reply.transport"
_SAFE_CONTRACT_TOKEN = re.compile(r"^[A-Za-z0-9_.:/@\-]{1,200}$")
# Generic orchestrator responses are intentionally limited to channels whose
# direct-send posture predates Safe Comms. Email is excluded: inbound email is
# untrusted input and may only reach SMTP through the governed channel-reply
# executor below.
_SUPPORTED_SEND_CHANNELS = frozenset({"telegram", "web", "voice"})
_SUPPORTED_REPLY_CHANNELS = frozenset({"telegram", "web", "email"})


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

    def register(self, channel: ChannelAdapter) -> None:
        self.channels[channel.channel_id] = channel
        logger.info(f"Channel registered: {channel.channel_id}")

    def get(self, channel_id: str):
        return self.channels.get(channel_id)

    async def start_all(self) -> None:
        for cid, ch in self.channels.items():
            try:
                await ch.start()
            except Exception as e:
                log_error(logger, E_CHANNEL_START_FAIL, name=cid, detail=str(e))

    async def stop_all(self) -> None:
        for cid, ch in self.channels.items():
            await ch.stop()

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
        if self._contract_denial(channel, response, kwargs) is not None:
            return False
        if channel == "telegram":
            return bool(await ch.send(response, **kwargs))
        elif channel == "web":
            return bool(await ch.send(response, **kwargs))
        elif channel == "voice":
            return bool(await ch.send(response))
        return False

    async def send_channel_reply(self, channel: str, response, **kwargs) -> bool:
        """Dispatch an already-governed `channel.reply` task.

        This is the transport seam consumed by ChannelReplyBroker.execute after the
        durable approval/Ultron path. It is intentionally separate from `send()` so
        merely registering an EmailChannel cannot make inbound email auto-send SMTP.
        """
        ch = self.channels.get(channel)
        if not ch:
            return False
        if self._reply_contract_denial(channel, response, kwargs) is not None:
            return False
        if channel in {"telegram", "web", "email"}:
            return bool(await ch.send(response, **kwargs))
        return False

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
