"""
slack.py — Slack channel adapter for Jarvis.

Port of OpenJarvis's Slack channel to pure Python.
Uses slack-sdk for message handling.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
from collections import OrderedDict
from contextlib import suppress
from typing import Optional

from .base import ChannelAdapter
from .descriptor import DIALECT_SLACK_MRKDWN, ChannelDescriptor
from .render import render_outbound

logger = logging.getLogger("jarvis.channels.slack")

#: Slack's cap on the ``text`` of one chat.postMessage.
SLACK_MAX_MESSAGE_LENGTH = 40_000
SLACK_INBOUND_QUEUE_SIZE = 128
SLACK_EVENT_CACHE_SIZE = 2048
SLACK_HTTP_TIMEOUT = 10

_USER_ID = re.compile(r"[UW][A-Z0-9]{1,63}")
_CHANNEL_ID = re.compile(r"[CDG][A-Z0-9]{1,63}")
_TEAM_ID = re.compile(r"T[A-Z0-9]{1,63}")
_EVENT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_TIMESTAMP = re.compile(r"[0-9]{1,20}\.[0-9]{1,6}")

try:
    from slack_sdk import WebClient
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.response import SocketModeResponse
    SLACK_AVAILABLE = True
except ImportError:
    SLACK_AVAILABLE = False


class _TransportLogger(logging.Logger):
    """SDK error strings can include websocket URLs, response bodies or tokens."""

    def handle(self, record):
        if record.levelno >= logging.WARNING:
            logger.log(record.levelno, "Slack SDK transport operation failed")


_SDK_LOGGER = _TransportLogger("jarvis.channels.slack.sdk", level=logging.WARNING)


def _socket_client(app_token, web_client):
    # Resolve the optional SDK at construction time (also a fake-SDK test seam).
    class BoundedSocketModeClient(SocketModeClient):
        def issue_new_wss_url(self):
            # The SDK default recursively retries rate-limit responses forever,
            # even during shutdown. One timed HTTP attempt lets lifecycle settle;
            # the SDK's normal connection monitor can make a later attempt.
            return self.web_client.apps_connections_open(app_token=self.app_token)["url"]

        def close(self):
            try:
                super().close()
            finally:
                # The SDK joins its reconnect monitor *after* disconnecting. A
                # reconnect in progress may have installed a session meanwhile.
                self.auto_reconnect_enabled = False
                self.disconnect()
                self.current_session_state.terminated = True
                if self.current_session_runner.is_alive():
                    self.current_session_runner.shutdown()

    return BoundedSocketModeClient(
        app_token=app_token, web_client=web_client, logger=_SDK_LOGGER,
    )


async def _finish_cleanup(coroutine):
    """Finish cleanup even if a caller cancels shutdown more than once."""
    task = asyncio.create_task(coroutine)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()
        raise


class SlackChannel(ChannelAdapter):
    descriptor = ChannelDescriptor(
        dialect=DIALECT_SLACK_MRKDWN,
        max_message_length=SLACK_MAX_MESSAGE_LENGTH,
        supports_edit=True,
        supports_media=True,
        supports_threads=True,
    )

    def __init__(self, token: str = "", handler=None, *, app_token: str = ""):
        super().__init__("slack", handler)
        self.token = token
        self.app_token = app_token
        self._client: Optional[WebClient] = None
        self._socket_client = None
        self._team_id = ""
        self._bot_user_id = ""
        self._dispatch_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._inbound_ready: asyncio.Event | None = None
        self._inbound_queue: queue.Queue = queue.Queue(maxsize=SLACK_INBOUND_QUEUE_SIZE)
        self._seen_events: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._ingress_lock = threading.Lock()
        self._wake_pending = False
        self._lifecycle_lock = asyncio.Lock()

    async def start(self):
        async with self._lifecycle_lock:
            if self._running:
                return
            if not SLACK_AVAILABLE:
                logger.warning("slack-sdk not installed — Slack channel unavailable")
                return
            if not self.token:
                logger.warning("No Slack token configured")
                return
            startup_task = None
            try:
                options = ({"timeout": SLACK_HTTP_TIMEOUT, "retry_handlers": [], "logger": _SDK_LOGGER}
                           if self.app_token else {})
                self._client = WebClient(token=self.token, **options)
                if not self.app_token:
                    self._running = True
                    logger.info("Slack channel ready (manual event ingress)")
                    return
                startup_task = asyncio.create_task(asyncio.to_thread(self._client.auth_test))
                identity = await asyncio.shield(startup_task)
                team, user = identity.get("team_id"), identity.get("user_id")
                if (identity.get("ok") is not True
                        or not isinstance(team, str) or not _TEAM_ID.fullmatch(team)
                        or not isinstance(user, str) or not _USER_ID.fullmatch(user)):
                    raise ValueError("Slack bot identity unavailable")
                self._team_id, self._bot_user_id = team, user
                self._loop = asyncio.get_running_loop()
                self._inbound_ready = asyncio.Event()
                self._socket_client = _socket_client(self.app_token, self._client)
                self._socket_client.socket_mode_request_listeners.append(self._on_socket_request)
                self._running = True
                self._dispatch_task = asyncio.create_task(
                    self._dispatch_events(), name="slack-socket-ingress",
                )
                # The built-in SDK uses blocking HTTP/websocket calls. Shield the
                # worker so cancellation can wait for connect, then close it: a
                # cancelled to_thread alone could reopen a connection after stop.
                startup_task = asyncio.create_task(asyncio.to_thread(self._socket_client.connect))
                await asyncio.shield(startup_task)
                if not self._socket_client.is_connected():
                    raise ConnectionError("Slack Socket Mode handshake failed")
                logger.info("Slack Socket Mode ingress connected")
            except asyncio.CancelledError:
                with self._ingress_lock:
                    self._running = False
                await _finish_cleanup(self._shutdown_after(startup_task))
                raise
            except Exception:
                logger.warning("Slack Socket Mode startup failed; channel stopped")
                await _finish_cleanup(self._shutdown())

    async def stop(self):
        async with self._lifecycle_lock:
            await _finish_cleanup(self._shutdown())

    async def _shutdown_after(self, startup_task):
        if startup_task is not None:
            with suppress(Exception):
                await startup_task
        await self._shutdown()

    async def _shutdown(self):
        with self._ingress_lock:
            self._running = False
            client, self._socket_client = self._socket_client, None
            self._loop = None
            self._wake_pending = False
            self._seen_events.clear()
            self._team_id = self._bot_user_id = ""
            while not self._inbound_queue.empty():
                self._inbound_queue.get_nowait()
        task, self._dispatch_task = self._dispatch_task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if client is not None:
            try:
                await asyncio.to_thread(client.close)
            except Exception:
                logger.warning("Slack Socket Mode close failed")
        self._inbound_ready = None
        self._client = None

    def _normalize_event(self, payload) -> tuple[tuple[str, str], dict] | None:
        """Admit new human DMs and addressed room messages, never raw metadata."""
        if not isinstance(payload, dict) or payload.get("type") != "event_callback":
            return None
        event = payload.get("event")
        team, event_id = payload.get("team_id"), payload.get("event_id")
        if (not isinstance(event, dict)
                or not isinstance(team, str) or not _TEAM_ID.fullmatch(team)
                or not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id)):
            return None
        if team != self._team_id:
            return None
        if (event.get("subtype") or event.get("hidden") or event.get("bot_id")
                or "bot_profile" in event):
            return None
        user, channel = event.get("user"), event.get("channel")
        text, timestamp = event.get("text"), event.get("ts")
        if (not isinstance(user, str) or not _USER_ID.fullmatch(user)
                or not isinstance(channel, str) or not _CHANNEL_ID.fullmatch(channel)
                or not isinstance(text, str) or not text.strip()
                or len(text) > SLACK_MAX_MESSAGE_LENGTH
                or not isinstance(timestamp, str) or not _TIMESTAMP.fullmatch(timestamp)):
            return None
        if user == self._bot_user_id:
            return None
        mention = event.get("type") == "app_mention" and channel.startswith(("C", "G"))
        direct = (event.get("type") == "message" and event.get("channel_type") == "im"
                  and channel.startswith("D"))
        if not (mention or direct):
            return None
        # Slack member IDs are workspace-local. Socket ingress requires fresh
        # workspace-scoped pairing; a prior bot token's bare ID cannot confer it.
        normalized = {"text": text, "channel": channel, "user": f"{team}:{user}"}
        thread = event.get("thread_ts")
        if "thread_ts" in event:
            if not isinstance(thread, str) or not _TIMESTAMP.fullmatch(thread):
                return None
            normalized["thread_ts"] = thread
        elif mention:
            # Root mentions are answered in their own Slack thread. An unthreaded
            # DM keeps its existing direct-conversation target.
            normalized["thread_ts"] = timestamp
        return (team, event_id), normalized

    def _on_socket_request(self, client, request):
        """SDK-thread callback: ACK first, then enqueue bounded validated data."""
        envelope_id = getattr(request, "envelope_id", None)
        if not isinstance(envelope_id, str) or not envelope_id or len(envelope_id) > 256:
            return
        with self._ingress_lock:
            if not self._running or client is not self._socket_client:
                return
        try:
            client.send_socket_mode_response(SocketModeResponse(envelope_id=envelope_id))
        except Exception:
            logger.warning("Slack Socket Mode acknowledgement failed; event not admitted")
            return
        if getattr(request, "type", None) != "events_api":
            return
        admitted = self._normalize_event(getattr(request, "payload", None))
        if admitted is None:
            return
        event_key, event = admitted
        with self._ingress_lock:
            if not self._running or client is not self._socket_client:
                return
            if event_key in self._seen_events:
                return
            try:
                self._inbound_queue.put_nowait(event)
            except queue.Full:
                logger.warning("Slack Socket Mode ingress queue full; event dropped")
                return
            self._seen_events[event_key] = None
            if len(self._seen_events) > SLACK_EVENT_CACHE_SIZE:
                self._seen_events.popitem(last=False)
            if not self._wake_pending:
                # Coalesce wakeups: the loop's own callback queue must not become
                # an unbounded second ingress buffer while a handler is busy.
                self._wake_pending = True
                try:
                    self._loop.call_soon_threadsafe(self._inbound_ready.set)
                except RuntimeError:
                    logger.warning("Slack Socket Mode event loop unavailable; event dropped")

    async def _dispatch_events(self):
        while self._running:
            await self._inbound_ready.wait()
            while self._running:
                with self._ingress_lock:
                    try:
                        event = self._inbound_queue.get_nowait()
                    except queue.Empty:
                        self._inbound_ready.clear()
                        self._wake_pending = False
                        break
                try:
                    await self.receive_event(**event)
                except Exception:
                    # Exception strings may contain credentials or message text.
                    logger.warning("Slack Socket Mode event dispatch failed")
                await asyncio.sleep(0)

    async def send(self, message: str, **kwargs) -> bool:
        if not self._client:
            return False
        channel = kwargs.get("slack_channel") or kwargs.get("channel")
        if not channel:
            logger.warning("No Slack channel specified")
            return False
        try:
            target = {"channel": channel}
            if kwargs.get("thread_ts"):
                target["thread_ts"] = kwargs["thread_ts"]
            # Rendered to mrkdwn and chunked on the source (Hermes absorption 4d).
            # slack_sdk.WebClient is the blocking (urllib) client; run it in an
            # executor so a slow/unreachable Slack API can't freeze the event loop.
            loop = asyncio.get_running_loop()
            for piece in render_outbound(str(message or ""), self.descriptor):
                result = await loop.run_in_executor(
                    None, lambda text=piece: self._client.chat_postMessage(**target, text=text)
                )
                if result.get("ok") is not True:
                    return False
            return True
        except Exception:
            logger.error("Slack send failed")
            return False

    async def receive_event(self, text: str, channel: str, user: str = "", **kwargs):
        """Route one inbound Slack event through the handler.

        ``user`` is the Slack member id from the event payload; it is threaded as
        ``sender`` so the gateway's pairing gate can hold a stranger. An event that
        names no user is dropped rather than routed anonymously: with no identity
        there is nothing for pairing to hold, and a front door that routes the
        unidentifiable is not a door. (Hermes absorption 5b)
        """
        if not self.handler:
            return None
        sender = str(user or "").strip()
        if not sender:
            logger.warning("Slack event without a user id dropped (unpairable)")
            return None
        # An adapter that forwards the raw event kwargs may carry its own ``sender``;
        # the member id from the payload is the identity pairing holds, so it wins
        # rather than colliding with the handler's keyword. Adapters never raise.
        kwargs.pop("sender", None)
        return await self.handler(
            text, channel="slack", slack_channel=channel, sender=sender, **kwargs
        )
