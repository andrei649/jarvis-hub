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

from . import delivery_ledger
from .base import ChannelAdapter
from .connect_deadline import DEFAULT_CONNECT_TIMEOUT, channel_connect_timeout
from .credentials import credential_is_configured
from .descriptor import DIALECT_SLACK_MRKDWN, ChannelDescriptor
from .ephemeral import EphemeralDeletes, EphemeralReply, ephemeral_ttl
from .render import render_outbound

logger = logging.getLogger("jarvis.channels.slack")

#: Slack's cap on the ``text`` of one chat.postMessage.
SLACK_MAX_MESSAGE_LENGTH = 40_000
SLACK_INBOUND_QUEUE_SIZE = 128
SLACK_EVENT_CACHE_SIZE = 2048
SLACK_HTTP_TIMEOUT = 10
SLACK_PENDING_FAST_LIMIT = 32

_USER_ID = re.compile(r"[UW][A-Z0-9]{1,63}")
_CHANNEL_ID = re.compile(r"[CDG][A-Z0-9]{1,63}")
_TEAM_ID = re.compile(r"T[A-Z0-9]{1,63}")
_EVENT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_TIMESTAMP = re.compile(r"[0-9]{1,20}\.[0-9]{1,6}")
_PENDING_DATA = re.compile(r"h067:[A-Za-z0-9_-]{16}:[0-9]{1,10}:[a-z][0-9]?")
_TRIGGER_ID = re.compile(r"[A-Za-z0-9._-]{1,256}")

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


def _socket_workers_stopped(client) -> bool:
    """Only explicit stopped SDK runners prove the socket connection has settled."""
    try:
        return all(getattr(client, name).is_alive() is False for name in (
            "current_session_runner", "current_app_monitor", "message_processor"))
    except Exception:
        return False


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

    def __init__(self, token: str = "", handler=None, *, app_token: str = "",
                 pairing=None, pending_reply_handler=None, pending_callback_handler=None,
                 pre_turn_refused=None, command_registry=None,
                 connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT):
        super().__init__("slack", handler)
        # H058: a probe (Gateway.pre_lane_refused) for a command its sender may not run here.
        self.pre_turn_refused = pre_turn_refused
        # H057: the same registry the gateway dispatches is the native slash allowlist.
        # The adapter never grants authority; pairing and the target's slash tier still
        # run in the normal channel handler after this envelope is acknowledged.
        self.command_registry = command_registry
        self.token = token
        self.app_token = app_token
        self._connect_timeout_seconds = channel_connect_timeout(connect_timeout_seconds)
        self.pairing = pairing
        self.pending_reply_handler = pending_reply_handler
        self.pending_callback_handler = pending_callback_handler
        self._pending_callback_generation = None
        self._pending_fast: dict[int, asyncio.Task] = {}
        self._pending_fast_reserved = 0
        self._pending_fast_serial = 0
        # H117: a burst from one member in one channel (and thread) is one turn. One batch
        # on its way at a time: the dispatcher is held while a turn runs, as it was before
        # batching, so the bounded ingress queue stays the only buffer. H058: a command the
        # member may not run here is handed over beside the key's running turn (like /btw),
        # so its refusal neither waits for that turn nor holds the dispatcher behind it.
        from .batching import AsyncBatcher, configured
        self._batch = AsyncBatcher(self._deliver_turn, *configured(), max_pending=1,
                                   beside=self._refused_here)
        self._client: Optional[WebClient] = None
        self._socket_client = None
        self._socket_generation = None
        self._socket_ready_generation = None
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
        self._ephemeral_deletes = EphemeralDeletes()
        self._slack_app_claim = None
        self._slack_bot_claim = None
        self._startup_cleanup_task: asyncio.Task | None = None

    async def start(self):
        async with self._lifecycle_lock:
            if self._running:
                return
            if (not credential_is_configured(self.token)
                    or not ((type(self.app_token) is str and not self.app_token)
                            or credential_is_configured(self.app_token))):
                self.health.failed_fatally("invalid_credential")
                logger.warning("Slack channel credential is not configured")
                return
            if not SLACK_AVAILABLE:
                logger.warning("slack-sdk not installed — Slack channel unavailable")
                return
            if (self._startup_cleanup_task is not None or self._slack_app_claim is not None
                    or self._slack_bot_claim is not None):
                self.health.failed_fatally("connection_cleanup_required")
                logger.warning("Slack startup refused: prior connection cleanup incomplete")
                return
            if self.app_token:
                from .polling_claims import (
                    ClaimUnavailable,
                    acquire_slack_app_claim,
                    acquire_slack_bot_claim,
                )

                try:
                    app_claim = acquire_slack_app_claim(self.app_token)
                except ClaimUnavailable as exc:
                    reason = ("connection_claim_busy" if exc.reason == "busy"
                              else "connection_claim_unavailable")
                    self.health.failed_fatally(reason)
                    logger.warning("Slack startup refused: connection claim unavailable")
                    return
                self._slack_app_claim = app_claim
                try:
                    bot_claim = acquire_slack_bot_claim(self.token)
                except ClaimUnavailable as exc:
                    # No SDK work has begun. Keep the handle on self if release
                    # fails, so an explicit stop can finish the prefix rollback.
                    self._slack_app_claim.release()
                    self._slack_app_claim = None
                    reason = ("connection_claim_busy" if exc.reason == "busy"
                              else "connection_claim_unavailable")
                    self.health.failed_fatally(reason)
                    logger.warning("Slack startup refused: connection claim unavailable")
                    return
                self._slack_bot_claim = bot_claim
            if self._ephemeral_deletes._closed:
                self._ephemeral_deletes = EphemeralDeletes()
            self._socket_generation = object()
            self._socket_ready_generation = None
            self.health.starting()
            startup_task = None
            deadline = (asyncio.get_running_loop().time() + self._connect_timeout_seconds
                        if self.app_token else None)
            try:
                options = ({"timeout": SLACK_HTTP_TIMEOUT, "retry_handlers": [], "logger": _SDK_LOGGER}
                           if self.app_token else {})
                self._client = WebClient(token=self.token, **options)
                if not self.app_token:
                    self._pending_callback_generation = object()
                    self._running = True
                    logger.info("Slack channel ready (manual event ingress)")
                    return
                if asyncio.get_running_loop().time() >= deadline:
                    self._opening_expired(startup_task)
                    return
                startup_task = asyncio.create_task(asyncio.to_thread(self._client.auth_test))
                if not await self._within_opening_budget(startup_task, deadline):
                    self._opening_expired(startup_task)
                    return
                identity = startup_task.result()
                team, user = identity.get("team_id"), identity.get("user_id")
                if (identity.get("ok") is not True
                        or not isinstance(team, str) or not _TEAM_ID.fullmatch(team)
                        or not isinstance(user, str) or not _USER_ID.fullmatch(user)):
                    raise ValueError("Slack bot identity unavailable")
                self._team_id, self._bot_user_id = team, user
                if asyncio.get_running_loop().time() >= deadline:
                    self._opening_expired(startup_task)
                    return
                self._loop = asyncio.get_running_loop()
                self._inbound_ready = asyncio.Event()
                self._socket_client = _socket_client(self.app_token, self._client)
                if asyncio.get_running_loop().time() >= deadline:
                    # Constructing the SDK client starts its own runners; even
                    # before connect, it needs an owned close on expiry.
                    self._opening_expired(startup_task)
                    return
                self._socket_client.socket_mode_request_listeners.append(self._on_socket_request)
                self._pending_callback_generation = object()
                self._running = True
                self._dispatch_task = asyncio.create_task(
                    self._dispatch_events(), name="slack-socket-ingress",
                )
                if asyncio.get_running_loop().time() >= deadline:
                    self._opening_expired(startup_task)
                    return
                # The built-in SDK uses blocking HTTP/websocket calls. Shield the
                # worker so cancellation can wait for connect, then close it: a
                # cancelled to_thread alone could reopen a connection after stop.
                startup_task = asyncio.create_task(asyncio.to_thread(self._socket_client.connect))
                if not await self._within_opening_budget(startup_task, deadline):
                    self._opening_expired(startup_task)
                    return
                startup_task.result()
                if self._observe_socket(self._socket_client, self._socket_generation) is True:
                    logger.info("Slack Socket Mode ingress connected")
                else:
                    # A returned handshake without an active session is a startup
                    # failure, not evidence of a previously live disconnect.
                    raise ConnectionError("Slack Socket Mode handshake failed")
            except asyncio.CancelledError:
                with self._ingress_lock:
                    self._running = False
                await _finish_cleanup(self._shutdown_after(startup_task))
                raise
            except Exception as exc:
                logger.warning("Slack Socket Mode startup failed; channel stopped")
                # H100: an auth refusal is fatal and named; anything else is a failed start.
                text = str(getattr(getattr(exc, "response", None), "data", "") or "")
                self.health.failed_fatally(
                    "unauthorized" if any(code in text for code in (
                        "invalid_auth", "not_authed", "token_revoked", "account_inactive"))
                    else "startup_failed")
                await _finish_cleanup(self._shutdown())

    async def stop(self):
        async with self._lifecycle_lock:
            cleanup = self._startup_cleanup_task
            if cleanup is not None:
                # asyncio.wait leaves the retained worker/cleanup running if a
                # bounded manager stop cancels this caller. Only a successful
                # explicit stop clears the restart fence.
                await asyncio.wait({cleanup})
                if cleanup.cancelled():
                    self.health.failed_fatally("connection_cleanup_required")
                    raise RuntimeError("Slack Socket Mode cleanup unconfirmed")
                if cleanup.exception() is not None:
                    await _finish_cleanup(self._shutdown())
                self._startup_cleanup_task = None
            else:
                await _finish_cleanup(self._shutdown())
            self.health.stopped()

    async def _within_opening_budget(self, task: asyncio.Task, deadline: float) -> bool:
        loop = asyncio.get_running_loop()
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        done, _ = await asyncio.wait({task}, timeout=remaining)
        return bool(done) and loop.time() < deadline

    def _opening_expired(self, startup_task: asyncio.Task | None) -> None:
        # The SDK can finish a blocking worker after this caller returns. Revoke
        # ingress immediately, then let exactly one owned cleanup join that
        # worker before closing the SDK and releasing both claims.
        with self._ingress_lock:
            self._running = False
            self._pending_callback_generation = None
            self._socket_generation = None
            self._socket_ready_generation = None
        self.health.failed_fatally("connect_timeout")
        logger.warning("Slack Socket Mode opening timed out")
        cleanup = asyncio.create_task(self._shutdown_after(startup_task),
                                      name="slack-opening-cleanup")
        self._startup_cleanup_task = cleanup
        cleanup.add_done_callback(lambda done: None if done.cancelled() else done.exception())

    def _observe_socket(self, client, generation) -> bool | None:
        """True/False for a valid probe, None if the probe or generation is unknown."""
        if (not self._running or client is None or client is not self._socket_client
                or generation is None or generation is not self._socket_generation):
            return None
        try:
            connected = bool(client.is_connected())
        except Exception:
            return None
        if connected:
            with self._ingress_lock:
                if (not self._running or client is not self._socket_client
                        or generation is not self._socket_generation):
                    return None
                self._socket_ready_generation = generation
        return connected

    def health_snapshot(self) -> dict:
        """H100 — Socket Mode's own monitor reconnects; this reports what it sees: connected
        (healthy), running but disconnected (retrying, the SDK is reconnecting), or the
        fatal reason a start failed with."""
        row = super().health_snapshot()
        client = self._socket_client
        if self._running and client is not None and row["state"] != "fatal":
            generation = self._socket_generation
            connected = self._observe_socket(client, generation)
            if connected is None:
                row.update(state="unknown", error="probe_failed", failures=0)
            else:
                row["state"] = "healthy" if connected else "retrying"
                row["error"] = None if connected else "disconnected"
                row["failures"] = 0 if connected else int(self._socket_ready_generation is generation)
        return row

    async def _shutdown_after(self, startup_task):
        if startup_task is not None:
            with suppress(Exception):
                await startup_task
        await self._shutdown()

    async def _shutdown(self):
        await self._ephemeral_deletes.aclose()
        self._batch.discard()              # H117: like the undelivered event queue below
        with self._ingress_lock:
            self._running = False
            self._pending_callback_generation = None
            client = self._socket_client
            self._socket_generation = None
            self._socket_ready_generation = None
            self._loop = None
            self._wake_pending = False
            self._seen_events.clear()
            self._team_id = self._bot_user_id = ""
            while not self._inbound_queue.empty():
                self._inbound_queue.get_nowait()
        pending = tuple(self._pending_fast.values())
        for work in pending:
            work.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._pending_fast.clear()
        with self._ingress_lock:
            self._pending_fast_reserved = 0
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
                self.health.failed_fatally("connection_cleanup_required")
                raise RuntimeError("Slack Socket Mode cleanup unconfirmed") from None
            if not _socket_workers_stopped(client):
                self.health.failed_fatally("connection_cleanup_required")
                logger.warning("Slack Socket Mode cleanup unconfirmed")
                raise RuntimeError("Slack Socket Mode cleanup unconfirmed")
        self._socket_client = None
        self._inbound_ready = None
        self._client = None
        # Both identities remain held until SDK close and every runner settle.
        if self._slack_bot_claim is not None:
            self._slack_bot_claim.release()
            self._slack_bot_claim = None
        if self._slack_app_claim is not None:
            self._slack_app_claim.release()
            self._slack_app_claim = None

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
        normalized = {"text": text, "channel": channel, "user": f"{team}:{user}",
                      # H120: a message's ts is unique in its channel: the provider id.
                      "provider_id": f"{team}:{channel}:{timestamp}"}
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

    def _normalize_slash(self, payload) -> tuple[tuple[str, str], dict] | None:
        """Convert a native Socket Mode slash payload into the ordinary channel path.

        Slack's response URL and any claimed role are deliberately discarded. Only
        the authenticated workspace/member/channel identifiers reach pairing and
        principal construction, exactly as they do for a DM or app mention.
        """
        from ..commands import CommandRegistry, slack_native_slashes

        registry = self.command_registry
        if not isinstance(payload, dict) or not isinstance(registry, CommandRegistry):
            return None
        team, user, channel = payload.get("team_id"), payload.get("user_id"), payload.get("channel_id")
        command, text, trigger = payload.get("command"), payload.get("text"), payload.get("trigger_id")
        if (not isinstance(team, str) or team != self._team_id or not _TEAM_ID.fullmatch(team)
                or not isinstance(user, str) or not _USER_ID.fullmatch(user)
                or user == self._bot_user_id
                or not isinstance(channel, str) or not _CHANNEL_ID.fullmatch(channel)
                or not isinstance(command, str)
                or not isinstance(text, str) or len(text) > SLACK_MAX_MESSAGE_LENGTH - 40
                or not isinstance(trigger, str) or not _TRIGGER_ID.fullmatch(trigger)):
            return None
        native = {entry["command"] for entry in slack_native_slashes(registry)}
        if command not in native:
            return None
        normalized = {"text": f"{command} {text}".strip(), "channel": channel,
                      "user": f"{team}:{user}",
                      "provider_id": f"{team}:{channel}:{trigger}",
                      "pending_input_eligible": False}
        return (team, f"slash:{trigger}"), normalized

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
        if getattr(request, "type", None) == "interactive":
            payload = getattr(request, "payload", None)
            callback = self._normalize_action(payload)
            hook = self.pending_callback_handler
            if callback is not None and callable(hook):
                original = payload["message"].get("text")
                self._start_pending_fast(client, self._handle_pending_callback,
                                         callback, original, hook,
                                         self._pending_callback_generation)
            return
        request_type = getattr(request, "type", None)
        if request_type == "slash_commands":
            admitted = self._normalize_slash(getattr(request, "payload", None))
        elif request_type == "events_api":
            admitted = self._normalize_event(getattr(request, "payload", None))
        else:
            return
        if admitted is None:
            return
        event_key, event = admitted
        # A slash command never answers a pending free-text prompt. It is its own
        # command turn; the ordinary command/access path decides what it may do.
        hook = self.pending_reply_handler if request_type == "events_api" else None
        with self._ingress_lock:
            if not self._running or client is not self._socket_client:
                return
            if event_key in self._seen_events:
                return
            # Reserve the bounded pending lane before posting to the loop. An
            # SDK reader thread may receive more requests while a turn blocks.
            fast = callable(hook) and self._pending_fast_reserved < SLACK_PENDING_FAST_LIMIT
            if fast:
                self._pending_fast_reserved += 1
            elif not self._enqueue_event_locked(event):
                return
            self._seen_events[event_key] = None
            if len(self._seen_events) > SLACK_EVENT_CACHE_SIZE:
                self._seen_events.popitem(last=False)
        if fast:
            self._post_pending_fast(client, self._handle_pending_reply, event, hook,
                                    self._pending_callback_generation)

    def _enqueue_event_locked(self, event):
        try:
            self._inbound_queue.put_nowait(event)
        except queue.Full:
            logger.warning("Slack Socket Mode ingress queue full; event dropped")
            return False
        if not self._wake_pending:
            self._wake_pending = True
            try:
                self._loop.call_soon_threadsafe(self._inbound_ready.set)
            except RuntimeError:
                logger.warning("Slack Socket Mode event loop unavailable; event dropped")
                self._wake_pending = False
                return False
        return True

    def _post_pending_fast(self, client, worker, *args):
        try:
            self._loop.call_soon_threadsafe(self._create_pending_fast, client, worker, args)
        except RuntimeError:
            with self._ingress_lock:
                self._pending_fast_reserved -= 1
            logger.warning("Slack pending ingress event loop unavailable")

    def _start_pending_fast(self, client, worker, *args):
        with self._ingress_lock:
            if (not self._running or client is not self._socket_client
                    or self._pending_fast_reserved >= SLACK_PENDING_FAST_LIMIT):
                return
            self._pending_fast_reserved += 1
        self._post_pending_fast(client, worker, *args)

    def _create_pending_fast(self, client, worker, args):
        if not self._running or client is not self._socket_client:
            with self._ingress_lock:
                self._pending_fast_reserved -= 1
            return
        self._pending_fast_serial += 1
        key = self._pending_fast_serial
        task = asyncio.create_task(worker(*args), name="slack-pending-input")
        self._pending_fast[key] = task

        def finished(done):
            self._pending_fast.pop(key, None)
            with self._ingress_lock:
                self._pending_fast_reserved = max(0, self._pending_fast_reserved - 1)
            with suppress(asyncio.CancelledError):
                done.exception()

        task.add_done_callback(finished)

    async def _handle_pending_reply(self, event, hook, generation):
        if not self._pending_live(generation):
            return
        pairing = self._pending_pairing(hook)
        if pairing is None or not self._pairing_allowed(pairing, event["user"]):
            with self._ingress_lock:
                if self._running:
                    self._enqueue_event_locked(event)
            return
        try:
            consumed = await hook(event["text"], channel="slack", sender=event["user"],
                                  slack_channel=event["channel"],
                                  thread_ts=event.get("thread_ts"))
        except Exception:
            logger.warning("Slack pending reply not applied")
            consumed = False
        if self._pending_live(generation) and consumed is not True:
            with self._ingress_lock:
                if self._running:
                    self._enqueue_event_locked(event)

    def _pending_live(self, generation):
        return self._running and generation is not None and generation is self._pending_callback_generation

    def _pending_pairing(self, hook):
        return self.pairing or getattr(getattr(hook, "__self__", None), "pairing", None)

    @staticmethod
    def _pairing_allowed(pairing, sender):
        try:
            return pairing.is_allowed("slack", sender) is True
        except Exception:
            return False

    def _normalize_action(self, payload):
        if not isinstance(payload, dict) or payload.get("type") != "block_actions":
            return None
        team = (payload.get("team") or {}).get("id") if isinstance(payload.get("team"), dict) else None
        user = (payload.get("user") or {}).get("id") if isinstance(payload.get("user"), dict) else None
        container, message, room = (payload.get("container"), payload.get("message"),
                                     payload.get("channel"))
        if (team != self._team_id or not isinstance(team, str) or not _TEAM_ID.fullmatch(team)
                or not isinstance(user, str) or not _USER_ID.fullmatch(user)
                or user == self._bot_user_id or not isinstance(container, dict)
                or container.get("type") != "message" or not isinstance(message, dict)
                or not isinstance(room, dict)):
            return None
        channel, timestamp = container.get("channel_id"), container.get("message_ts")
        if (not isinstance(channel, str) or not _CHANNEL_ID.fullmatch(channel)
                or not isinstance(timestamp, str) or not _TIMESTAMP.fullmatch(timestamp)
                or room.get("id") != channel or message.get("ts") != timestamp
                or (message.get("user") is not None
                    and message.get("user") != self._bot_user_id)):
            return None
        thread = message.get("thread_ts")
        if thread is not None and (not isinstance(thread, str) or not _TIMESTAMP.fullmatch(thread)):
            return None
        actions = payload.get("actions")
        if not isinstance(actions, list) or len(actions) != 1 or not isinstance(actions[0], dict):
            return None
        action = actions[0]
        data = action.get("value")
        if (action.get("type") != "button" or action.get("action_id") != "h067_pending"
                or not isinstance(data, str) or not _PENDING_DATA.fullmatch(data)):
            return None
        return {"channel": "slack", "target": channel, "message_id": timestamp,
                "thread_id": thread, "team_id": team, "sender": f"{team}:{user}", "data": data}

    async def _handle_pending_callback(self, callback, original, hook, generation):
        if not self._pending_live(generation):
            return
        pairing = self._pending_pairing(hook)
        try:
            if pairing is None or not self._pairing_allowed(pairing, callback["sender"]):
                return
            result = await hook(callback, channel="slack")
            if not self._pending_live(generation) or getattr(result, "applied", False) is not True:
                return
            markup = getattr(result, "markup", None)
            if markup is None:
                markup = {"inline_keyboard": []}
            text = original if isinstance(original, str) and original.strip() else "Pending prompt updated"
            blocks = self._pending_blocks(text, markup)
            if blocks is None:
                return
            client = self._client
            if client is None:
                return
            response = await asyncio.to_thread(client.chat_update, channel=callback["target"],
                                               ts=callback["message_id"], blocks=blocks,
                                               text=text)
            if not self._pending_live(generation) or client is not self._client:
                return
            if response.get("ok") is not True:
                logger.warning("Slack pending prompt buttons could not be updated")
        except Exception:
            logger.warning("Slack pending callback not applied")

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

    @staticmethod
    def _pending_blocks(text, markup, *, include_text=True):
        """Translate the canonical keyboard into conservative Block Kit buttons."""
        if type(markup) is not dict or set(markup) != {"inline_keyboard"}:
            return None
        rows = markup["inline_keyboard"]
        if type(rows) is not list or len(rows) > 40:
            return None
        blocks = []
        if include_text:
            if not isinstance(text, str) or not text:
                return None
            for offset in range(0, len(text), 3000):
                blocks.append({"type": "section", "text": {
                    "type": "mrkdwn", "text": text[offset:offset + 3000]}})
        for row in rows:
            if type(row) is not list or not 1 <= len(row) <= 5:
                return None
            elements = []
            for button in row:
                if type(button) is not dict or set(button) != {"text", "callback_data"}:
                    return None
                label, data = button["text"], button["callback_data"]
                if (type(label) is not str or not label
                        or type(data) is not str or not _PENDING_DATA.fullmatch(data)):
                    return None
                from .outbound_safety import sanitize_label

                label = sanitize_label(label)      # H069 review M3
                # Slack caps a button's plain_text at 75 characters. Keep the
                # numbered/selected prefix visible; the value still identifies
                # the full canonical choice in the pending-card registry.
                if len(label) > 75:
                    label = label[:74] + "…"
                elements.append({"type": "button", "text": {"type": "plain_text", "text": label},
                                 "action_id": "h067_pending", "value": data})
            blocks.append({"type": "actions", "elements": elements})
        return blocks if len(blocks) <= 50 else None

    async def send_pending_card(self, message: str, *, reply_markup: dict, **kwargs):
        """Post canonical buttons only with the final, verified bot-owned message."""
        client = self._client
        generation = self._pending_callback_generation
        channel = kwargs.get("slack_channel", kwargs.get("channel"))
        thread = kwargs.get("thread_ts")
        if (not self._pending_live(generation) or client is None or not self._team_id
                or type(message) is not str or not message.strip()
                or type(channel) is not str or not _CHANNEL_ID.fullmatch(channel)
                or (thread is not None and (type(thread) is not str
                                            or not _TIMESTAMP.fullmatch(thread)))
                or set(kwargs) - {"slack_channel", "channel", "thread_ts"}):
            delivery_ledger.note_send_failure()
            return None
        pieces = render_outbound(message, self.descriptor)
        if not pieces:
            delivery_ledger.note_send_failure()
            return None
        final_blocks = self._pending_blocks(pieces[-1], reply_markup)
        if final_blocks is None:
            delivery_ledger.note_send_failure()
            return None
        receipt = None
        for index, piece in enumerate(pieces):
            if not self._pending_live(generation) or client is not self._client:
                delivery_ledger.note_send_failure()
                return None
            payload = {"channel": channel, "text": piece}
            if thread is not None:
                payload["thread_ts"] = thread
            if index == len(pieces) - 1:
                payload["blocks"] = final_blocks
            try:
                response = await asyncio.to_thread(client.chat_postMessage, **payload)
                ack_channel, timestamp = response.get("channel"), response.get("ts")
                if (response.get("ok") is not True or type(ack_channel) is not str
                        or ack_channel != channel or type(timestamp) is not str
                        or not _TIMESTAMP.fullmatch(timestamp)):
                    delivery_ledger.note_unconfirmed_ack()
                    return None
                receipt = timestamp
                # An accepted prefix stays partial if a later part fails or the
                # callback generation changes before this card can be bound.
                delivery_ledger.note_partial()
            except Exception:
                delivery_ledger.note_unconfirmed_ack()
                logger.warning("Slack pending prompt delivery failed")
                return None
            if not self._pending_live(generation) or client is not self._client:
                return None
        return {"channel": "slack", "target": channel, "message_id": receipt,
                "thread_id": thread, "team_id": self._team_id}

    def discard_pending_card(self, receipt):
        """Slack offers have no adapter-owned remote cleanup operation."""
        return None

    async def send(self, message: str, **kwargs) -> bool:
        if not self._client:
            return False
        channel = kwargs.get("slack_channel") or kwargs.get("channel")
        if not channel:
            logger.warning("No Slack channel specified")
            return False
        try:
            client, generation = self._client, self._pending_callback_generation
            ttl = 0
            if isinstance(message, EphemeralReply):
                from ..settings_db import get_value

                default = get_value("display", "ephemeral_system_ttl", 0) if message.ttl_seconds is None else 0
                ttl = min(ephemeral_ttl(message, default=default), 86400)
            target = {"channel": channel}
            if kwargs.get("thread_ts"):
                target["thread_ts"] = kwargs["thread_ts"]
            # Rendered to mrkdwn and chunked on the source (Hermes absorption 4d).
            # slack_sdk.WebClient is the blocking (urllib) client; run it in an
            # executor so a slow/unreachable Slack API can't freeze the event loop.
            loop = asyncio.get_running_loop()
            for piece in render_outbound(str(message or ""), self.descriptor):
                result = await loop.run_in_executor(
                    None, lambda text=piece: client.chat_postMessage(**target, text=text)
                )
                if result.get("ok") is not True:
                    return False
                timestamp = result.get("ts")
                if (ttl and result.get("channel") == channel and type(timestamp) is str
                        and _TIMESTAMP.fullmatch(timestamp) and generation is not None):
                    async def delete(ts=timestamp):
                        if (not self._running or self._client is not client
                                or self._pending_callback_generation is not generation):
                            return False
                        outcome = await asyncio.to_thread(client.chat_delete, channel=channel, ts=ts)
                        return outcome.get("ok") is True

                    self._ephemeral_deletes.schedule(ttl, delete)
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
        # H117: held for the batch window, keyed by channel, member and thread.
        key = (str(channel), sender, str(kwargs.get("thread_ts") or ""))
        return await self._batch.submit(key, text, slack_channel=channel, sender=sender, **kwargs)

    def _refused_here(self, _key, text: str, meta: dict) -> bool:
        """H058 — whether *text* is a command this member may not run in this conversation
        (judged by the hub through ``pre_turn_refused``; a missing probe says no). The hub
        reads a ``D`` channel as a DM, as it does for the turn itself."""
        probe = self.pre_turn_refused
        return callable(probe) and probe(
            channel="slack", sender=meta.get("sender"), chat_id=meta.get("slack_channel"),
            text=text, chat_type=meta.get("chat_type")) is True

    async def _deliver_turn(self, key, text: str, meta: dict):
        if not self.handler:
            return None
        return await self.handler(text, channel="slack", **meta)
