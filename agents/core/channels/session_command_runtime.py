"""Owner-confirmed conversation changes, fenced before any history append."""

import hashlib
import json
from contextlib import AsyncExitStack
from dataclasses import dataclass

from ..memory.manager import RewindRefused
from ..memory.session_undo import undo_last_exchange
from .ephemeral import EphemeralReply
from .pending_input_runtime import pending_key
from .session import build_session_key, session_type
from .session_command_consent import SessionCommandConsent
from .session_lifecycle import lifecycle
from .session_reset import SessionResetError, generation_key


@dataclass(frozen=True)
class _Snapshot:
    base: str
    generation: int
    actual: str
    clock: object
    history_instance: str | None
    history_revision: int | None
    shared: bool
    transport_generation: object


class SessionCommandRuntime:
    def __init__(self, pending):
        self.pending = pending
        self.orch = pending.orch

    def _owner(self, source, delivery):
        return (self.pending._allowed(source)
                and self.orch._channel_principal(
                    source.channel, source.sender, delivery.get("chat_id")).admin)

    def _actual(self, service, base, shared):
        state = service.store.state(base)
        default = (self.orch._session_id_default if shared and state.generation == 0
                   else generation_key(base, state.generation))
        return state, self.orch._channel_sessions.get(base, default)

    def _clock(self, actual):
        checkpoints = getattr(self.orch, "checkpoints", None)
        if checkpoints is None:
            raise RewindRefused("conversation clock unavailable")
        return checkpoints.clock_snapshot(actual)

    def _history_head(self, actual):
        conversation = getattr(getattr(self.orch, "memory", None), "conversation", None)
        if conversation is None:
            raise RewindRefused("conversation history unavailable")
        return conversation.instances.get(actual), conversation.revisions.get(actual)

    def _route_current(self, service, source, delivery, base, generation, actual, shared):
        if service.closed or not self._owner(source, delivery):
            return False
        if self.orch.get_setting("memory.cross_channel_sessions", False) != shared:
            return False
        state, current = self._actual(service, base, shared)
        return state.generation == generation and current == actual

    def _current(self, snap, service, source, delivery):
        if not self._route_current(service, source, delivery, snap.base, snap.generation,
                                   snap.actual, snap.shared):
            return False
        if source.channel == "ntfy":
            adapter = (getattr(self.orch, "channels", None) or {}).get("ntfy")
            allowed = getattr(adapter, "_reply_allowed", None)
            if not callable(allowed) or not allowed(delivery.get("ntfy_topic"), delivery.get("ntfy_context")):
                return False
        return (self._clock(snap.actual) == snap.clock
                and getattr((getattr(self.orch, "channels", None) or {}).get(source.channel),
                            "_pending_callback_generation", None) is snap.transport_generation
                and self._history_head(snap.actual) ==
                (snap.history_instance, snap.history_revision))

    def _consent(self):
        worker = getattr(self.orch, "autonomy", None)
        return SessionCommandConsent(getattr(self.orch, "permission_ledger", None),
                                     getattr(worker, "govern_enqueue", None))

    def _consent_key(self, source):
        key = pending_key(source)
        if source.channel != "ntfy":
            return key
        adapter = (getattr(self.orch, "channels", None) or {}).get("ntfy")
        authority = [getattr(adapter, field, None) for field in ("url", "topic", "publish_topic")]
        if key is None or any(type(value) is not str or not value for value in authority):
            raise RewindRefused("ntfy consent authority unavailable")
        # Stable across restart and credential rotation; a different endpoint
        # or topic cannot inherit the previous server's standing approval.
        digest = hashlib.sha256(json.dumps(authority, separators=(",", ":")).encode()).hexdigest()
        return key[0], f"{key[1]}:ntfy:{digest}", key[2]

    async def handle(self, source, text, delivery):
        if source.channel not in {"telegram", "slack", "discord", "ntfy"}:
            return None
        service = lifecycle(self.orch)
        operation = "undo" if text.strip() == "/undo" else (
            "reset" if service.reset_requested(text) else None)
        if operation is None:
            return None
        if (delivery.get("pending_input_eligible", True) is not True
                or not self._owner(source, delivery)):
            return EphemeralReply("Only the current owner can confirm this conversation change.")
        from ..orchestrator import TURN_BUSY_REPLY

        shared = self.orch.get_setting("memory.cross_channel_sessions", False)
        base = self.orch._session_id_default if shared else build_session_key(source)
        try:
            async with AsyncExitStack() as locks:
                if not await locks.enter_async_context(self.orch.turn_lease(base)):
                    return EphemeralReply(TURN_BUSY_REPLY)
                state, actual = self._actual(service, base, shared)
                if not await locks.enter_async_context(self.orch.turn_lease(actual)):
                    return EphemeralReply(TURN_BUSY_REPLY)
                if not self._route_current(service, source, delivery, base,
                                           state.generation, actual, shared):
                    return EphemeralReply("Conversation or authority changed; nothing was applied.")
                conversation = getattr(self.orch.memory, "conversation", None)
                if conversation is None:
                    raise RewindRefused("conversation history unavailable")
                if actual not in conversation.sessions:
                    # Loading an existing transcript is a read-only prerequisite:
                    # never create an unknown session to make /undo appear valid.
                    expected_history = state.active or self._clock(actual) is not None
                    resumed = await self.orch.memory.resume_session(actual)
                    if not self._route_current(service, source, delivery, base,
                                               state.generation, actual, shared):
                        return EphemeralReply("Conversation or authority changed; nothing was applied.")
                    if not resumed and expected_history:
                        raise RewindRefused("existing conversation transcript unavailable")
                history_instance, history_revision = self._history_head(actual)
                snap = _Snapshot(base, state.generation, actual, self._clock(actual),
                                 history_instance, history_revision, shared,
                                 getattr((getattr(self.orch, "channels", None) or {}).get(source.channel),
                                         "_pending_callback_generation", None))
                if operation == "undo" and snap.clock is None:
                    return EphemeralReply("There is no conversation to undo; nothing changed.")
            key = self._consent_key(source)
            consent = self._consent()
            status = consent.check(key, operation)
            if status == "deny":
                return EphemeralReply("This conversation change is denied; nothing changed.")
            choice = None
            if status != "allow":
                question = ("Undo the last exchange?" if operation == "undo"
                            else "Start a new conversation? Your existing conversation stays saved.")
                choice = await self.pending.confirmation(operation, question)
                if choice not in {"once", "always"}:
                    return EphemeralReply("Conversation change cancelled; nothing changed.")
            async with AsyncExitStack() as locks:
                if not await locks.enter_async_context(self.orch.turn_lease(base)):
                    return EphemeralReply(TURN_BUSY_REPLY)
                if not await locks.enter_async_context(self.orch.turn_lease(snap.actual)):
                    return EphemeralReply(TURN_BUSY_REPLY)
                status = consent.check(key, operation)
                if (not self._current(snap, service, source, delivery) or status == "deny"
                        or (choice is None and status != "allow")):
                    return EphemeralReply("Conversation or authority changed; nothing was applied.")
                notice = ""
                if choice == "always":
                    try:
                        task_id = consent.request_always(key, operation, f"{source.channel}:{source.sender}")
                        notice = f" Permanent approval is pending in Decision Inbox (task {task_id})."
                    except Exception:
                        notice = " Permanent approval could not be requested; this applies once only."
                def authorize():
                    return self._current(snap, service, source, delivery)
                if operation == "reset":
                    result = await service.run(source, text, shared=shared, authorize_reset=authorize)
                else:
                    await undo_last_exchange(self.orch.memory, snap.actual, snap.clock,
                                             authorize=authorize)
                    service.store.touch(base, service.now(), source.channel, session_type(source))
                    result = "Removed the last exchange. Earlier conversation is preserved."
                return EphemeralReply(result + notice)
        except (SessionResetError, RewindRefused, OSError, ValueError):
            return EphemeralReply("Conversation change unavailable; nothing was applied.")
