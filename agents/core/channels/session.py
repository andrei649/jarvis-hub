"""Channel session identity and delivery decisions.

This is the Hermes-style gateway session layer for Jarvis: pure helpers that
derive filesystem-safe session keys from channel metadata and decide where a
response should be delivered. DRA-08 phase 5 wired them into the live inbound
path — ``Orchestrator.channel_handler`` builds one :class:`SessionSource` per
turn, keys its memory session off :func:`build_session_key`, and asks
:class:`DeliveryRouter` whether to reply before touching the transport.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from ..validation import is_valid_session_id

_TOKEN_RE = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True)
class SessionSource:
    """Origin metadata for a channel-backed conversation."""

    channel: str = "web"
    sender: str | None = None
    thread_id: str | None = None
    client_id: str | None = None
    explicit_session_id: str | None = None
    local_only: bool = False
    silent: bool = False


@dataclass(frozen=True)
class DeliveryTarget:
    """Concrete outbound target for a response."""

    channel: str
    recipient: str | None = None
    thread_id: str | None = None


@dataclass(frozen=True)
class DeliveryDecision:
    """Decision returned by DeliveryRouter.resolve()."""

    send: bool
    target: DeliveryTarget | None
    reason: str


def _slug(value: object, *, fallback: str = "unknown") -> str:
    token = _TOKEN_RE.sub("_", str(value or "").strip()).strip("_").lower()
    return token[:32] or fallback


def _identity(source: SessionSource) -> tuple[str, str]:
    if source.thread_id:
        return "thread", str(source.thread_id)
    if source.sender:
        return "sender", str(source.sender)
    if source.client_id:
        return "client", str(source.client_id)
    return "local", "default"


def build_session_key(source: SessionSource) -> str:
    """Return a deterministic, filesystem-safe session id for a channel turn."""

    if source.explicit_session_id and is_valid_session_id(source.explicit_session_id):
        return source.explicit_session_id
    channel = _slug(source.channel, fallback="channel")
    kind, identity = _identity(source)
    digest = hashlib.sha256(
        f"{channel}\0{kind}\0{identity}".encode()
    ).hexdigest()[:20]
    key = f"ch_{channel}_{kind}_{digest}"
    if is_valid_session_id(key):
        return key
    return f"ch_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]}"


class DeliveryRouter:
    """Pure reply-target resolver for channel sessions."""

    def __init__(self, default_channel: str = "web"):
        self.default_channel = default_channel

    def resolve(
        self,
        source: SessionSource,
        *,
        text: str = "reply",
        explicit_target: DeliveryTarget | None = None,
    ) -> DeliveryDecision:
        if not str(text or "").strip():
            return DeliveryDecision(False, None, "empty-message")
        if source.silent:
            return DeliveryDecision(False, None, "silent-source")
        if source.local_only:
            return DeliveryDecision(False, None, "local-only")
        if explicit_target is not None:
            return DeliveryDecision(True, explicit_target, "explicit-target")
        target = DeliveryTarget(
            channel=str(source.channel or self.default_channel),
            recipient=source.sender or source.client_id,
            thread_id=source.thread_id,
        )
        return DeliveryDecision(True, target, "home-channel")


__all__ = [
    "DeliveryDecision",
    "DeliveryRouter",
    "DeliveryTarget",
    "SessionSource",
    "build_session_key",
]
