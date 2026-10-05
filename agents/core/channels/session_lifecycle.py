"""H063 integration: persistent route generations and genuine turn activity.

Routing-index pruning never deletes conversation data. A stable base-route lease
survives generation changes, so resetting cannot bypass an active turn's lease.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import math
from contextlib import AsyncExitStack, contextmanager
from datetime import UTC, datetime
from time import time

from ..paths import data_path
from .session import SessionSource, build_session_key, session_type
from .session_reset import (
    SessionResetError,
    SessionResetStore,
    generation_key,
    resolve_policy,
    should_reset,
)
from .session_stall import StallWatcher

logger = logging.getLogger("jarvis.channels.session_lifecycle")
RESET_ACK = "Started a new conversation. Your previous conversation is still saved."
UNAVAILABLE = "Session state is unavailable; this request could not be completed."
_activity = contextvars.ContextVar("nerva-session-activity", default=None)


def note_session_activity() -> None:
    """Token/tool/processing activity, scoped to the actual inbound turn."""
    callback = _activity.get()
    if callback is not None:
        callback()


def session_activity_callback():
    """Observer for genuine model tokens; None outside a tracked channel turn."""
    return _activity.get()


class ChannelSessionLifecycle:
    def __init__(self, orch):
        self.orch = orch
        self.clock = getattr(orch, "_session_clock", time)
        self.path = getattr(orch, "_session_lifecycle_path", None) or data_path("channel_routes.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.store = SessionResetStore(self.path)
        self.closed = False
        progress_clock = getattr(orch, "_session_progress_clock", None)
        self.stalls = StallWatcher(clock=progress_clock) if progress_clock is not None else StallWatcher()

    def now(self) -> datetime:
        value = self.clock()
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise SessionResetError("Invalid session clock")
        try:
            return datetime.fromtimestamp(value, UTC)
        except (OverflowError, ValueError, OSError):
            raise SessionResetError("Invalid session clock") from None

    def reset_requested(self, text: str) -> bool:
        triggers = self.orch.get_setting("sessions.reset_triggers", ["/new", "/reset"])
        if (not isinstance(triggers, list) or len(triggers) > 32
                or any(not isinstance(t, str) or not t.strip() or len(t) > 120 for t in triggers)):
            raise SessionResetError("Invalid reset triggers")
        return text.strip() in triggers

    @contextmanager
    def track(self, base):
        if self.closed:
            raise SessionResetError("Session lifecycle is closed")
        episode = self.stalls.begin(base)
        token = _activity.set(lambda: self.stalls.progress(base, episode))
        try:
            yield
        finally:
            self.stalls.finish(base, episode)
            _activity.reset(token)

    async def run(self, source: SessionSource, text: str, *, observe_only=False, draft=None,
                  shared=False, authorize_reset=None):
        from ..memory.manager import RewindRefused
        from ..orchestrator import TURN_BUSY_REPLY

        base = self.orch._session_id_default if shared else build_session_key(source)
        kind = session_type(source)
        try:
            if self.closed:
                raise SessionResetError("Session lifecycle is closed")
            if observe_only:
                return await self._observe(source, text, base=base, kind=kind, draft=draft, shared=shared)
            async with self.orch.turn_lease(base) as acquired:
                if not acquired:
                    return TURN_BUSY_REPLY
                state = self.store.state(base)
                policy = resolve_policy(self.orch.get_setting, source.channel, kind)
                explicit = not observe_only and self.reset_requested(text)
                now = self.now()
                reset = explicit or (not observe_only and state.last_activity is not None
                                     and should_reset(state.last_activity, now, policy))
                current = self.orch._channel_sessions.get(base, generation_key(base, state.generation))
                async with AsyncExitStack() as leases:
                    held = await leases.enter_async_context(self.orch.turn_lease(current))
                    if not held:
                        return TURN_BUSY_REPLY
                    key = generation_key(base, state.generation + int(reset))
                    selected_held = await leases.enter_async_context(self.orch.turn_lease(key))
                    if not selected_held:
                        return TURN_BUSY_REPLY
                    selected = None if reset else self.orch._channel_sessions.get(base)
                    if selected is None:
                        if shared and state.generation == 0 and not reset:
                            selected = self.orch._session_id_default
                        elif await self.orch.memory.resume_session(key):
                            selected = key
                        else:
                            selected = await self.orch.memory.new_session(key)
                    actual_held = await leases.enter_async_context(self.orch.turn_lease(selected))
                    if not actual_held:
                        return TURN_BUSY_REPLY
                    # Prepare the new memory session before committing the route.
                    # A refused create/resume must leave the old route intact.
                    if reset:
                        if authorize_reset is not None and authorize_reset() is not True:
                            raise SessionResetError("Reset authority changed")
                        state = self.store.rotate(base, now, source.channel, kind)
                    self.store.touch(base, now, source.channel, kind)
                    self.orch._channel_sessions[base] = selected
                    if explicit:
                        return RESET_ACK
                    try:
                        if observe_only:
                            return await self.orch._run_channel_session_turn(
                                selected, text, source.channel, observe_only=True, draft=draft)
                        with self.track(base):
                            return await self.orch._run_channel_session_turn(
                                selected, text, source.channel, observe_only=False, draft=draft)
                    finally:
                        # Completion is route activity; pending eligibility is a
                        # separate ephemeral record, never persisted inbound text.
                        self.store.touch(base, self.now(), source.channel, kind)
        except (SessionResetError, RewindRefused, OverflowError, OSError):
            logger.warning("channel session lifecycle unavailable")
            return UNAVAILABLE

    async def _observe(self, source, text, *, base, kind, draft, shared):
        """Context-only ingress keeps the existing no-turn-lease contract.

        It never rotates a generation or overwrites a route selected while the
        memory call awaited. Conversation memory serializes its own append.
        """
        state = self.store.state(base)
        key = generation_key(base, state.generation)
        selected = self.orch._channel_sessions.get(base)
        if selected is None:
            if shared and state.generation == 0:
                selected = self.orch._session_id_default
            elif await self.orch.memory.resume_session(key):
                selected = key
            else:
                selected = await self.orch.memory.new_session(key)
            self.orch._channel_sessions.setdefault(base, selected)
        self.store.touch(base, self.now(), source.channel, kind)
        return await self.orch._run_channel_session_turn(
            selected, text, source.channel, observe_only=True, draft=draft)

    async def expire(self) -> dict:
        """Retire/reset idle routing entries; skip every active route/session."""
        if self.closed:
            return {"retired": 0, "rotated": 0}
        now = self.now()
        days = self.orch.get_setting("sessions.store_max_age_days", 90)
        if type(days) is not int or not 0 <= days <= 36_500:
            raise SessionResetError("Invalid session index age")
        retired = rotated = 0
        for state in self.store.entries():
            if not state.active:
                continue
            locks = self.orch.__dict__.setdefault("_turn_leases", {})
            temporary = state.base not in locks
            lock = locks.setdefault(state.base, asyncio.Lock())
            current = self.orch._channel_sessions.get(state.base, generation_key(state.base, state.generation))
            actual = locks.get(current)
            if lock.locked() or (actual is not None and actual.locked()):
                if temporary:
                    del locks[state.base]
                continue
            # Acquiring a just-checked unlocked asyncio.Lock does not suspend.
            await lock.acquire()
            try:
                policy = resolve_policy(self.orch.get_setting, state.channel, state.kind)
                age = (now - state.last_activity).total_seconds()
                if days and age >= days * 86_400:
                    self.store.retire(state.base)
                    self.orch._channel_sessions.pop(state.base, None)
                    retired += 1
                elif should_reset(state.last_activity, now, policy):
                    self.store.rotate(state.base, now, state.channel, state.kind)
                    self.orch._channel_sessions.pop(state.base, None)
                    rotated += 1
            finally:
                lock.release()
                if temporary and locks.get(state.base) is lock:
                    del locks[state.base]
        return {"retired": retired, "rotated": rotated}

    async def check_stalls(self) -> int:
        return await self.stalls.check(self.orch.get_setting("sessions.stall_seconds", 300), self._notify_stall)

    async def close(self) -> int:
        self.closed = True
        return await self.stalls.close()

    async def _notify_stall(self, base, episode, idle) -> bool:
        from .outbound import send_to_target

        timeout = self.orch.get_setting("sessions.stall_seconds", 300)
        if not self.stalls.is_due(base, episode, timeout):
            return False
        target = self.orch.get_setting("sessions.stall_channel", "telegram")
        if target not in {"telegram", "ntfy", "web"}:
            return False
        minutes = max(1, int(idle // 60))
        notice = f"Nerva has made no progress on a pending conversation for {minutes} min."
        result = await send_to_target(self.orch, target, notice, source="session.stall", plain=True)
        return bool(result.get("ok"))


def lifecycle(orch) -> ChannelSessionLifecycle:
    service = orch.__dict__.get("_channel_lifecycle")
    if service is None:
        service = ChannelSessionLifecycle(orch)
        orch._channel_lifecycle = service
    return service
