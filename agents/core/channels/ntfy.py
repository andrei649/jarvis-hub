"""ntfy.py — a push to the owner's phone with no bot and no account (Hermes absorption 4g).

The cheapest path from "Nerva wants to tell you something" to a buzz in your pocket: one
HTTP POST to an ntfy server, ``httpx`` only, no SDK, no daemon, no bot token. Self-hostable,
so with your own server nothing leaves the LAN — which is why ``NTFY_URL`` has no default:
the owner names the server, Nerva never assumes a public one.

Outbound only, on purpose. On ntfy the *topic* is the identity — anyone who knows it can
publish to it and read it — so this adapter never reads a topic: nothing that arrives on
ntfy can become a turn, a command or a pairing, and the publisher-supplied title of a
message is never trusted for anything. If an inbound path is ever wanted it goes through
the pairing gate like every other channel, not through here.

What it carries: the plain-text rendering of a reply (the channel has no markup), chunked
at ntfy's message cap, with a title and a priority (1–5) as headers, and a bearer token
when the server wants one. Every send is a ``channel.send`` through the manager's contract
gate; the escalation router and the jobs engine reach it like any other registered
adapter.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import httpx

from .base import ChannelAdapter
from .descriptor import DIALECT_PLAIN, ChannelDescriptor
from .render import render_outbound

logger = logging.getLogger("jarvis.channels.ntfy")

CHANNEL_ID = "ntfy"
#: ntfy's cap on one message body.
NTFY_MAX_MESSAGE_LENGTH = 4096
# Names of the environment variables (not values): the server, the topic, the bearer token
# the server may require, the notification title.
ENV_PREFIX = "NTFY_"
URL_ENV = ENV_PREFIX + "URL"
TOPIC_ENV = ENV_PREFIX + "TOPIC"
TOKEN_ENV = ENV_PREFIX + "TOKEN"  # nosec B105 — an env-var name, the token itself is never in code
TITLE_ENV = ENV_PREFIX + "TITLE"
DEFAULT_TITLE = "Nerva"
DEFAULT_PRIORITY = 3
_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_URL_RE = re.compile(r"^https?://[^\s/]+(?:/[^\s]*)?$")
_MAX_TITLE = 120


def _clean_title(raw: object) -> str:
    """HTTP headers carry ASCII; anything else is dropped rather than mis-encoded."""
    text = str(raw or "").strip()[:_MAX_TITLE]
    ascii_only = "".join(ch for ch in text if 32 <= ord(ch) < 127)
    return ascii_only.strip() or DEFAULT_TITLE


def _clean_priority(raw: object) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PRIORITY
    return max(1, min(5, value))


class NtfyChannel(ChannelAdapter):
    descriptor = ChannelDescriptor(dialect=DIALECT_PLAIN, max_message_length=NTFY_MAX_MESSAGE_LENGTH)

    def __init__(
        self,
        url: str,
        topic: str,
        *,
        token: str = "",
        title: str = DEFAULT_TITLE,
        client: Any = None,
        timeout: float = 10.0,
    ) -> None:
        super().__init__(CHANNEL_ID, None)
        url = str(url or "").strip().rstrip("/")
        topic = str(topic or "").strip()
        if not _URL_RE.match(url):
            raise ValueError("ntfy needs an http(s) server URL")
        if not _TOPIC_RE.match(topic):
            raise ValueError("ntfy topic must be 1-64 letters, digits, '_' or '-'")
        self.url = url
        self.topic = topic
        self._token = str(token or "").strip()
        self.title = _clean_title(title)
        self.client = client if client is not None else httpx.AsyncClient(timeout=timeout)

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> NtfyChannel | None:
        """The configured channel, or None when ``NTFY_URL`` / ``NTFY_TOPIC`` are not both
        set; a malformed value is refused with a warning rather than half-wired."""
        url = str(environ.get(URL_ENV, "") or "").strip()
        topic = str(environ.get(TOPIC_ENV, "") or "").strip()
        if not url and not topic:
            return None
        if not url or not topic:
            logger.warning("ntfy needs both %s and %s; channel disabled", URL_ENV, TOPIC_ENV)
            return None
        try:
            return cls(
                url, topic,
                token=str(environ.get(TOKEN_ENV, "") or ""),
                title=str(environ.get(TITLE_ENV, "") or DEFAULT_TITLE),
            )
        except ValueError as exc:
            logger.warning("ntfy channel disabled: %s", exc)
            return None

    async def start(self) -> None:
        self._running = True
        logger.info("ntfy channel ready")

    async def stop(self) -> None:
        self._running = False
        close = getattr(self.client, "aclose", None)
        if callable(close):
            await close()

    async def send(self, message: str, **kwargs) -> bool:
        """POST the plain-text rendering, chunked; True only when every chunk was accepted."""
        headers = {
            "Title": _clean_title(kwargs.get("title") or self.title),
            "Priority": str(_clean_priority(kwargs.get("priority", DEFAULT_PRIORITY))),
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        for piece in render_outbound(str(message or ""), self.descriptor):
            try:
                resp = await self.client.post(
                    f"{self.url}/{self.topic}", content=piece.encode("utf-8"), headers=headers,
                )
                resp.raise_for_status()
            except Exception as exc:
                logger.error("ntfy send error: %s", exc.__class__.__name__)
                return False
        return True


__all__ = [
    "CHANNEL_ID", "DEFAULT_PRIORITY", "DEFAULT_TITLE", "NTFY_MAX_MESSAGE_LENGTH",
    "NtfyChannel", "TITLE_ENV", "TOKEN_ENV", "TOPIC_ENV", "URL_ENV",
]
