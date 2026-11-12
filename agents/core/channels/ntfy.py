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
from time import time as wall_time
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..env_config import truthy
from ..http_client import PluginEgressError, PluginHTTPClient
from ..plugin_gate import register_dynamic_domain
from . import delivery_ledger
from .backfill import (
    COMMAND_REFUSED,
    BackfillBudget,
    configured_window,
    is_backlog,
    looks_like_command,
)
from .base import ChannelAdapter
from .descriptor import DIALECT_PLAIN, ChannelDescriptor
from .outbound_safety import sanitize_text
from .pairing import channel_open_acknowledged, pairing_enabled
from .reconnect import FATAL_REPROBE_S, Backoff, classify_exception, classify_status
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
#: H116: ids of the most recent messages taken, remembered across restarts.
_SEEN_IDS = 64
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


def title_header(raw: object) -> str:
    """H069 review m4: the notification title through the outbound gate, then made a header."""
    return _clean_title(sanitize_text(str(raw or "")))


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
        # H100: the shared ladder (with jitter and reset-after-healthy), on ntfy's rungs.
        self._backoff = Backoff(_RECONNECT_BACKOFF, clock=lambda: monotonic())
        # H116: the since= cursor (last message time and ids), saved in the reliability
        # store; a backfill after a start is bounded (backfill.py).
        self._cursor_store = None
        self._since: int | None = None
        self._seen: list[str] = []
        self._started_wall: float | None = None
        self._cutoff: float | None = None
        self._backfill: BackfillBudget | None = None
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
        self.health.starting()
        self._backoff.reset()
        if self.inbound:
            self._resume_cursor()
            self._epoch = secrets.token_hex(32)
            self._pending_callback_generation = object()
            self._subscription_context = self._context()
            if callable(self.pending_reply_handler):
                self._events = asyncio.Queue(maxsize=128)
                self._dispatch_task = asyncio.create_task(self._dispatch_events(), name="ntfy-inbound")
            self._stream_task = asyncio.create_task(self._run_stream(), name="ntfy-subscription")
        logger.info("ntfy channel ready")

    def _cursor_name(self) -> str:
        return "ntfy:" + hashlib.sha256(json.dumps([self.url, self.topic]).encode()).hexdigest()[:16]

    def _resume_cursor(self) -> None:
        """H116 — read where the last run stopped reading (time and ids) and arm the
        bounded catch-up. No saved cursor: subscribe from now, as before."""
        self._cursor_store = delivery_ledger.store()
        self._since, self._seen = None, []
        saved = None
        if self._cursor_store is not None:
            try:
                saved = json.loads(self._cursor_store.cursor(self._cursor_name()) or "null")
            except (ValueError, TypeError):
                saved = None
            except Exception:
                logger.warning("ntfy saved cursor unreadable; subscribing from now")
        if isinstance(saved, dict):
            since, seen = saved.get("time"), saved.get("ids")
            if type(since) is int and since > 0:
                self._since = since
            if isinstance(seen, list):
                self._seen = [i for i in seen if isinstance(i, str) and 0 < len(i) <= 200][-_SEEN_IDS:]
        self._started_wall = wall_time()
        self._cutoff = None
        self._backfill = BackfillBudget()
        self.health.backfill = self._backfill.counts()

    def _stream_params(self) -> dict:
        params = {"poll": "false"}
        if self._since is not None and self._started_wall is not None:
            window = configured_window()
            if window > 0:
                params["since"] = str(max(self._since, int(wall_time()) - window))
        return params

    def _taken(self, key: str, sent_at) -> None:
        """Remember a message as taken, before it is handled: a restart never takes it again."""
        self._seen = [*self._seen[-(_SEEN_IDS - 1):], key]
        if type(sent_at) is int and sent_at > 0:
            self._since = max(self._since or 0, sent_at)
        store = self._cursor_store
        if store is None:
            return
        try:
            store.set_cursor(self._cursor_name(), json.dumps({"time": self._since, "ids": self._seen}))
        except Exception:
            logger.warning("ntfy cursor not saved")

    async def stop(self) -> None:
        self._running = False
        self.health.stopped()
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
        while self._running:
            if self._subscription_context != self._context():
                self.fatal_error = "configuration_changed"
                self.health.failed_fatally("configuration_changed")
                self._running = False
                return
            started = monotonic()
            kind = "stream_closed"
            fatal = False
            try:
                async with contextlib.AsyncExitStack() as stack:
                    # Restrict redaction to opening the subscription. Inbound
                    # handlers keep their ordinary HTTP diagnostics afterwards.
                    with _private_transport_logs():
                        response = await stack.enter_async_context(self.client.stream(
                            "GET", f"{self.url}/{self.topic}/json", params=self._stream_params(),
                            headers=self._auth_headers(),
                            timeout=httpx.Timeout(15.0, read=90.0),
                        ))
                    failure = (classify_status(response.status_code)
                               if response.status_code >= 400 else None)
                    if failure is not None and failure.fatal:
                        # H100: a wrong or revoked credential, or a topic that is gone:
                        # the ladder cannot fix it. Say so on the status surface and look
                        # again only every FATAL_REPROBE_S, so a fixed token heals by itself.
                        self.fatal_error = f"http_{response.status_code}"
                        self.health.failed_fatally(failure.kind, reprobe_in=FATAL_REPROBE_S)
                        logger.warning("ntfy subscription refused: HTTP %s; retrying in %.0f min",
                                       response.status_code, FATAL_REPROBE_S / 60)
                        fatal = True
                    else:
                        response.raise_for_status()
                        self.fatal_error = None
                        self._backoff.success(at=started)
                        self.health.ok()
                        # H116: what the server replays from before this connection opened
                        # is a backlog: bounded per connection, commands refused.
                        self._cutoff = wall_time()
                        if self._started_wall is not None:
                            self._backfill = BackfillBudget()
                        await self._consume_stream(response)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                kind = classify_exception(exc).kind
                logger.warning("ntfy stream error: %s", exc.__class__.__name__)
            if not self._running:
                return
            if fatal:
                await sleep(FATAL_REPROBE_S)
                continue
            delay = self._backoff.failure()
            self.health.retrying(kind, delay)
            await sleep(delay)

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
        sent_at = event.get("time")
        # A server clock ahead of ours never makes a message look newer than now.
        sent_at = min(sent_at, int(wall_time())) if type(sent_at) is int and sent_at > 0 else None
        # H116: an id taken before (this run or the last) that the server sends again
        # with a since= replay is not taken twice.
        if key in self._dedup or (sent_at is not None and key in self._seen):
            return
        self._dedup[key] = now
        if len(self._dedup) > 1000:
            self._dedup.popitem(last=False)
        budget = self._backfill
        backfilled = (budget is not None and self._started_wall is not None
                      and is_backlog(sent_at, self._cutoff if self._cutoff is not None
                                     else self._started_wall))
        if backfilled:
            # H116: sent while Nerva was not listening. Bounded; a command is never run
            # from a backfill; a plain message takes the live path below (gateway pairing,
            # inbox, approval) but never answers a pending prompt.
            self._taken(key, sent_at)
            if looks_like_command(text):
                if budget.fresh(sent_at, wall_time()):
                    budget.refused_commands += 1
                    if self._reply_allowed(self.topic, self._context()):
                        await self.send(COMMAND_REFUSED, plain=True)
                self.health.backfill = budget.counts()
                return
            admitted = budget.admit(sent_at, wall_time())
            self.health.backfill = budget.counts()
            if not admitted:
                return
        else:
            self._taken(key, sent_at)
        metadata = {"sender": self.topic, "chat_id": self.topic,
                    "ntfy_topic": self.topic, "ntfy_context": self._context()}
        if backfilled:
            metadata["pending_input_eligible"] = False
        if self._events is None:
            await self.receive(text.strip(), **metadata)
            return
        if callable(self.pending_reply_handler) and not backfilled:
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
            # H069 review m4: the notification title is text the phone shows, too.
            "Title": title_header(kwargs.get("title") or self.title),
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
        delivered = 0
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
                    delivered += 1
            except Exception as exc:
                # H081: why, for the delivery ledger; a refusal is the topic's credential.
                delivery_ledger.note_send_failure(exc=exc, partial=delivered > 0, channel_level=True)
                logger.error("ntfy send error: %s", exc.__class__.__name__)
                return False
        return True


__all__ = [
    "CHANNEL_ID", "DEFAULT_PRIORITY", "DEFAULT_TITLE", "NTFY_MAX_MESSAGE_LENGTH",
    "NtfyChannel", "TITLE_ENV", "TOKEN_ENV", "TOPIC_ENV", "URL_ENV",
    "INBOUND_ENV", "SERVER_ENV", "PUBLISH_TOPIC_ENV", "MARKDOWN_ENV",
]
