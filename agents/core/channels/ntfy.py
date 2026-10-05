"""ntfy.py — a push to the owner's phone with no bot and no account (Hermes absorption 4g).

The cheapest path from "Nerva wants to tell you something" to a buzz in your pocket: one
HTTP POST to an ntfy server, ``httpx`` only, no SDK, no daemon, no bot token. Self-hostable,
so with your own server nothing leaves the LAN — which is why ``NTFY_URL`` has no default:
the owner names the server, Nerva never assumes a public one.

Receiving is opt-in with NTFY_INBOUND=1. The configured topic is the identity, never
a publisher's title or sender. Receiving uses the shared gateway/pairing and Inbox;
automatic replies require channel.reply approval and a live configuration recheck.
The stream/dedup/backoff algorithm is adapted from MIT-licensed Hermes, pinned at
59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e, plugins/platforms/ntfy/adapter.py.

What it carries: the plain-text rendering of a reply (the channel has no markup), chunked
at ntfy's message cap, with a title and a priority (1–5) as headers, and a bearer token
when the server wants one. Every send is a ``channel.send`` through the manager's contract
gate; the escalation router and the jobs engine reach it like any other registered
adapter.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import hashlib
import json
import logging
import re
import secrets
from asyncio import sleep
from collections import OrderedDict
from collections.abc import Mapping
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..env_config import truthy
from ..http_client import PluginEgressError, PluginHTTPClient
from ..plugin_gate import register_dynamic_domain
from .base import ChannelAdapter
from .descriptor import DIALECT_PLAIN, ChannelDescriptor
from .pairing import channel_open_acknowledged, pairing_enabled
from .render import chunk, render_outbound

logger = logging.getLogger("jarvis.channels.ntfy")
_private_http_logs = contextvars.ContextVar("ntfy-private-http-logs", default=False)


class _PrivateHTTPLogFilter(logging.Filter):
    """HTTPX logs request URLs at INFO; topics may be bearer-like identities."""

    def filter(self, record: logging.LogRecord) -> bool:
        if _private_http_logs.get():
            record.msg = "ntfy HTTP transport"
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(_PrivateHTTPLogFilter())


@contextlib.contextmanager
def _private_transport_logs():
    token = _private_http_logs.set(True)
    try:
        yield
    finally:
        _private_http_logs.reset(token)

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
INBOUND_ENV = ENV_PREFIX + "INBOUND"
SERVER_ENV = ENV_PREFIX + "SERVER_URL"
PUBLISH_TOPIC_ENV = ENV_PREFIX + "PUBLISH_TOPIC"
MARKDOWN_ENV = ENV_PREFIX + "MARKDOWN"
DEFAULT_TITLE = "Nerva"
DEFAULT_PRIORITY = 3
_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_URL_RE = re.compile(r"^https?://[^\s/]+(?:/[^\s]*)?$")
_MAX_TITLE = 120
_ECHO_TAG = "nerva-agent"
_RECONNECT_BACKOFF = (2, 5, 10, 30, 60)
_MAX_FRAME = 65_536


class _NtfyHTTPClient(PluginHTTPClient):
    """Recheck a reply after DNS/policy waits, before entering the HTTP transport."""

    def __init__(self, guard):
        super().__init__("ntfy")
        self._guard = guard

    async def _prepare_target(self, method, url):
        target = await super()._prepare_target(method, url)
        if not self._guard():
            raise PluginEgressError("ntfy reply authorization changed")
        return target


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


def _byte_chunks(text: str):
    data = text.encode("utf-8")
    if not data:
        yield b""
    while data:
        end = min(len(data), NTFY_MAX_MESSAGE_LENGTH)
        while end < len(data) and data[end] & 0xC0 == 0x80:
            end -= 1
        yield data[:end]
        data = data[end:]


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
        handler=None,
        pairing=None,
        inbound: bool = False,
        publish_topic: str = "",
        markdown: bool = False,
        pending_reply_handler=None,
    ) -> None:
        super().__init__(CHANNEL_ID, handler)
        url = str(url or "").strip().rstrip("/")
        topic = str(topic or "").strip()
        if not _URL_RE.match(url):
            raise ValueError("ntfy needs an http(s) server URL")
        try:
            parsed = urlsplit(url)
            if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError
            _ = parsed.port  # Validate the configured port before creating a transport.
        except ValueError:
            raise ValueError("ntfy needs a server URL without credentials, query or fragment") from None
        if not _TOPIC_RE.match(topic):
            raise ValueError("ntfy topic must be 1-64 letters, digits, '_' or '-'")
        publish_topic = str(publish_topic or topic).strip()
        if not _TOPIC_RE.match(publish_topic):
            raise ValueError("ntfy publish topic must be 1-64 letters, digits, '_' or '-'")
        self.url = url
        self.topic = topic
        self._token = str(token or "").strip()
        self.title = _clean_title(title)
        self.inbound = bool(inbound)
        self.pairing = pairing
        self.publish_topic = publish_topic
        self.markdown = bool(markdown)
        self.pending_reply_handler = pending_reply_handler
        self._timeout = timeout
        self._epoch = secrets.token_hex(32)
        self._stream_task: asyncio.Task | None = None
        self._dispatch_task: asyncio.Task | None = None
        self._events: asyncio.Queue | None = None
        self._pending_callback_generation = None
        self._subscription_context: str | None = None
        self._dedup: OrderedDict[str, float] = OrderedDict()
        self.fatal_error: str | None = None
        self._reply_binding: contextvars.ContextVar = contextvars.ContextVar("ntfy-reply", default=None)
        register_dynamic_domain("ntfy", url)
        self.client = client if client is not None else _NtfyHTTPClient(self._request_guard)

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> NtfyChannel | None:
        """The configured channel, or None when ``NTFY_URL`` / ``NTFY_TOPIC`` are not both
        set; a malformed value is refused with a warning rather than half-wired."""
        url = str(environ.get(URL_ENV) or environ.get(SERVER_ENV) or "").strip()
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
                inbound=truthy(environ.get(INBOUND_ENV)),
                publish_topic=str(environ.get(PUBLISH_TOPIC_ENV, "") or ""),
                markdown=truthy(environ.get(MARKDOWN_ENV)),
            )
        except ValueError as exc:
            logger.warning("ntfy channel disabled: %s", exc)
            return None

    async def start(self) -> None:
        if self._running:
            return
        if self.inbound and not self._guard_configured():
            raise ValueError("ntfy inbound requires a shared handler and pairing gate")
        self._running = True
        self.fatal_error = None
        if self.inbound:
            self._epoch = secrets.token_hex(32)
            self._pending_callback_generation = object()
            self._subscription_context = self._context()
            if callable(self.pending_reply_handler):
                self._events = asyncio.Queue(maxsize=128)
                self._dispatch_task = asyncio.create_task(self._dispatch_events(), name="ntfy-inbound")
            self._stream_task = asyncio.create_task(self._run_stream(), name="ntfy-subscription")
        logger.info("ntfy channel ready")

    async def stop(self) -> None:
        self._running = False
        task, self._stream_task = self._stream_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        task, self._dispatch_task = self._dispatch_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._events = None
        self._pending_callback_generation = None
        self._dedup.clear()
        close = getattr(self.client, "aclose", None) or getattr(self.client, "close", None)
        if callable(close):
            await close()

    def _guard_configured(self) -> bool:
        return (callable(self.handler) and callable(getattr(self.pairing, "is_allowed", None))
                and (pairing_enabled() or channel_open_acknowledged()))

    def _context(self) -> str:
        # Private random epoch prevents exposing a testable digest of weak Basic
        # credentials. A new adapter invalidates old queued reply destinations.
        values = [self._epoch, self.url, self.topic, self._token, self.publish_topic, self.markdown]
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            return {}
        if ":" in self._token:
            encoded = base64.b64encode(self._token.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        return {"Authorization": f"Bearer {self._token}"}

    async def _run_stream(self) -> None:
        backoff = 0
        while self._running:
            if self._subscription_context != self._context():
                self.fatal_error = "configuration_changed"
                self._running = False
                return
            started = monotonic()
            try:
                async with contextlib.AsyncExitStack() as stack:
                    # Restrict redaction to opening the subscription. Inbound
                    # handlers keep their ordinary HTTP diagnostics afterwards.
                    with _private_transport_logs():
                        response = await stack.enter_async_context(self.client.stream(
                            "GET", f"{self.url}/{self.topic}/json", params={"poll": "false"},
                            headers=self._auth_headers(),
                            timeout=httpx.Timeout(15.0, read=90.0),
                        ))
                    if response.status_code in {401, 403, 404}:
                        self.fatal_error = f"http_{response.status_code}"
                        self._running = False
                        logger.warning("ntfy subscription stopped: HTTP %s", response.status_code)
                        return
                    response.raise_for_status()
                    await self._consume_stream(response)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("ntfy stream error: %s", exc.__class__.__name__)
            if not self._running:
                return
            if monotonic() - started >= 60:
                backoff = 0
            await sleep(_RECONNECT_BACKOFF[min(backoff, len(_RECONNECT_BACKOFF) - 1)])
            backoff += 1

    async def _consume_stream(self, response) -> None:
        # aiter_lines buffers an unbounded unterminated frame. Bound bytes before
        # parsing, dropping an oversized frame through its next newline.
        pending = bytearray()
        oversized = False
        async for block in response.aiter_bytes():
            if not self._running:
                return
            pieces = block.split(b"\n")
            for index, piece in enumerate(pieces):
                if not oversized:
                    if len(pending) + len(piece) > _MAX_FRAME:
                        pending.clear()
                        oversized = True
                    else:
                        pending.extend(piece)
                if index < len(pieces) - 1:
                    if pending and not oversized:
                        try:
                            value = json.loads(pending)
                        except (ValueError, UnicodeError):
                            value = None
                        if isinstance(value, dict):
                            await self._on_message(value)
                    pending.clear()
                    oversized = False

    async def _on_message(self, event: dict) -> None:
        if (not self._running or not self.inbound or not self._guard_configured()
                or self._subscription_context != self._context()
                or event.get("event") != "message"
                or event.get("topic") != self.topic):
            return
        text = event.get("message")
        if not isinstance(text, str) or not text.strip():
            return
        try:
            if len(text.encode()) > NTFY_MAX_MESSAGE_LENGTH:
                return
        except UnicodeError:
            return
        tags = event.get("tags")
        if isinstance(tags, list) and _ECHO_TAG in tags:
            return
        key = event.get("id")
        if not isinstance(key, str) or not key or len(key) > 200:
            return
        now = monotonic()
        while self._dedup and next(iter(self._dedup.values())) <= now - 300:
            self._dedup.popitem(last=False)
        if key in self._dedup:
            return
        self._dedup[key] = now
        if len(self._dedup) > 1000:
            self._dedup.popitem(last=False)
        metadata = {"sender": self.topic, "chat_id": self.topic,
                    "ntfy_topic": self.topic, "ntfy_context": self._context()}
        if self._events is None:
            await self.receive(text.strip(), **metadata)
            return
        if callable(self.pending_reply_handler):
            try:
                if await self.pending_reply_handler(text.strip(), channel=CHANNEL_ID, **metadata) is True:
                    return
            except Exception:
                logger.warning("ntfy pending ingress not applied")
        try:
            self._events.put_nowait((text.strip(), metadata))
        except asyncio.QueueFull:
            logger.warning("ntfy inbound queue full; message discarded")

    async def _dispatch_events(self):
        while self._running:
            text, metadata = await self._events.get()
            try:
                if (self._running and metadata["ntfy_context"] == self._context()
                        and self._subscription_context == self._context()):
                    await self.receive(text, **metadata)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("ntfy inbound dispatch failed")
            finally:
                self._events.task_done()

    def _reply_allowed(self, ntfy_topic: str, ntfy_context: str) -> bool:
        if (not self._running or not self.inbound or not self._guard_configured()
                or ntfy_topic != self.topic or ntfy_context != self._context()):
            return False
        try:
            if not self.pairing.is_allowed(CHANNEL_ID, self.topic):
                return False
        except Exception:
            return False
        return True

    def _request_guard(self) -> bool:
        binding = self._reply_binding.get()
        if binding is None:
            return True
        topic, context, current = binding
        try:
            return self._reply_allowed(topic, context) and (current is None or current() is True)
        except Exception:
            return False

    async def send_reply(self, message: str, *, ntfy_topic: str, ntfy_context: str,
                         current=None, plain=False) -> bool:
        if (not self._reply_allowed(ntfy_topic, ntfy_context)
                or (current is not None and not callable(current))):
            return False
        token = self._reply_binding.set((ntfy_topic, ntfy_context, current))
        try:
            return await self.send(message, plain=plain)
        finally:
            self._reply_binding.reset(token)

    async def send(self, message: str, **kwargs) -> bool:
        """POST the plain-text rendering, chunked; True only when every chunk was accepted.

        ``plain=True`` sends every chunk as it is, never rendered: a notice whose text
        came from outside (a webhook's sender) keeps its file names and addresses."""
        headers = {
            "Title": _clean_title(kwargs.get("title") or self.title),
            "Priority": str(_clean_priority(kwargs.get("priority", DEFAULT_PRIORITY))),
        }
        headers.update(self._auth_headers())
        if self.inbound:
            headers["X-Tags"] = _ECHO_TAG
        if self.markdown:
            headers["X-Markdown"] = "true"
        text = str(message or "")
        pieces = (chunk(text, self.descriptor.max_message_length) if kwargs.get("plain") is True or self.markdown
                  else render_outbound(text, self.descriptor))
        for piece in pieces:
            try:
                for body in _byte_chunks(piece):
                    if not self._request_guard():
                        return False
                    with _private_transport_logs():
                        resp = await self.client.post(
                            f"{self.url}/{self.publish_topic}", content=body, headers=headers,
                            timeout=self._timeout,
                        )
                    resp.raise_for_status()
            except Exception as exc:
                logger.error("ntfy send error: %s", exc.__class__.__name__)
                return False
        return True


__all__ = [
    "CHANNEL_ID", "DEFAULT_PRIORITY", "DEFAULT_TITLE", "NTFY_MAX_MESSAGE_LENGTH",
    "NtfyChannel", "TITLE_ENV", "TOKEN_ENV", "TOPIC_ENV", "URL_ENV",
    "INBOUND_ENV", "SERVER_ENV", "PUBLISH_TOPIC_ENV", "MARKDOWN_ENV",
]
