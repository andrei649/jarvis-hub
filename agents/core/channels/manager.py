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
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Literal

from ..automation_contracts import ContractTemplate, contract_denial, predicate
from ..errors import E_CHANNEL_START_FAIL
from ..log import log_error
from . import delivery_ledger
from . import escalation as escalation_policy
from .base import ChannelAdapter
from .pending_input_workspace import valid_markup, valid_receipt

logger = logging.getLogger("jarvis.channels.manager")

_NOTICE_LABELS = {
    "telegram": "Telegram", "discord": "Discord", "slack": "Slack",
    "ntfy": "ntfy", "web": "web", "voice": "voice", "email": "email",
    "sms": "SMS",
}


@dataclass(slots=True)
class CardAttempt:
    """One caller's metadata-only view of a Telegram card send.

    ``send_pending_card`` still returns only the native message ID. The pending
    input runtime uses this local observation to decide whether a plain fallback
    could duplicate a card whose delivery was sent, partial, or uncertain.
    """

    disposition: Literal["not_attempted", "skipped", "sent", "failed", "partial", "unknown"] = "not_attempted"


def _safe_mode_active() -> bool:
    """A failed policy read must never authorize a channel restart."""
    try:
        from agents.core import safe_mode

        return bool(safe_mode.enabled())
    except Exception:
        return True

CHANNEL_SEND_CONTRACT_KIND = "channel.send"
CHANNEL_REPLY_TRANSPORT_CONTRACT_KIND = "channel.reply.transport"
_SAFE_CONTRACT_TOKEN = re.compile(r"^[A-Za-z0-9_.:/@\-]{1,200}$")
# Generic orchestrator responses are intentionally limited to channels whose
# direct-send posture predates Safe Comms. Email is excluded: inbound email is
# untrusted input and may only reach SMTP through the governed channel-reply
# executor below.
_SUPPORTED_SEND_CHANNELS = frozenset({"telegram", "web", "voice", "ntfy"})
_SUPPORTED_REPLY_CHANNELS = frozenset({"telegram", "web", "email", "slack", "discord", "ntfy", "sms"})


#: H081 — which send kwarg names the chat a reply goes to, per channel (for the ledger
#: row and the dead-target registry). A channel with no per-chat target is "default".
_TARGET_KEYS = {
    "telegram": ("chat_id",),
    "web": ("client_id",),
    "slack": ("slack_channel",),
    "discord": ("channel_id",),
    "email": ("to",),
    "ntfy": ("ntfy_topic",),
    "sms": ("sms_to",),
}


def _delivery_target(channel: str, adapter, kwargs: dict) -> str:
    for key in _TARGET_KEYS.get(channel, ()):
        value = kwargs.get(key)
        if value not in (None, ""):
            if channel == "sms":
                # G16: a phone number is never written to the ledger, only its digest.
                from .sms import target_ref
                return target_ref(value)
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
        self._notice_owners: dict[asyncio.Task, tuple[str, ChannelAdapter, int, int]] = {}
        self._failure_escalation = escalation_policy.FailureEscalation()
        self._escalation_monitor: asyncio.Task | None = None
        self._escalation_loop: asyncio.AbstractEventLoop | None = None
        # H083: track the current adapter while preserving platform pause intent
        # across replacement. These controls do not write profile/config state.
        self._platform_paused: dict[str, tuple[ChannelAdapter, str]] = {}
        self._platform_locks: dict[str, asyncio.Lock] = {}
        self._platform_revisions: dict[str, int] = {}
        self._platform_epoch = 0
        self._platform_stopping = False
        self._platform_stop_in_progress = False
        self._platform_stop_calls = 0
        self._platform_starts: dict[str, asyncio.Task] = {}
        self._platform_cleanup: dict[str, set[asyncio.Task]] = {}
        self._platform_retired: dict[str, list[ChannelAdapter]] = {}
        self._platform_retire_tasks: dict[tuple[str, int], asyncio.Task] = {}

    def register(self, channel: ChannelAdapter) -> None:
        cid = channel.channel_id
        old = self.channels.get(cid)
        if old is not channel:
            self._failure_escalation.retire(cid)
            self._cancel_notice_tasks(cid)
            if old is not None:
                self._platform_retired.setdefault(cid, []).append(old)
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    pass  # An explicit async start/stop drains it before replacement starts.
                else:
                    task = loop.create_task(self._bounded_platform_stop(cid, old))
                    self._platform_retire_tasks[(cid, id(old))] = task
                    self._track_platform_cleanup(cid, task)
            self._platform_revisions[cid] = self._platform_revisions.get(cid, 0) + 1
            if cid in self._platform_paused:
                # The owner's pause applies to the platform even if its adapter
                # object is replaced. A stale operation still cannot start it.
                self._platform_paused[cid] = (channel, "paused")
            pending = self._platform_starts.get(cid)
            if pending is not None:
                pending.cancel()
        self.channels[channel.channel_id] = channel
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            if self._escalation_loop is None or self._escalation_loop.is_closed():
                self._escalation_loop = running_loop
        health = getattr(channel, "health", None)
        if health is not None and hasattr(health, "on_fatal"):
            revision = self._platform_revisions.get(cid, 0)
            health.on_fatal = lambda reason, cid=cid, source=channel, revision=revision: (
                self._fatal_notice(cid, reason, source, revision))
        logger.info(f"Channel registered: {channel.channel_id}")

    def get(self, channel_id: str):
        return self.channels.get(channel_id)

    def queue_command_menu_refresh(self, *, owner_current=None) -> asyncio.Task[bool] | None:
        """Queue one current Telegram menu publish after an owner skill reload.

        The adapter owns the task and its transport lifetime. This synchronous
        gate reads no private skill catalog and never calls a provider itself.
        """
        cid = "telegram"
        ch = self.channels.get(cid)
        if ch is None or (owner_current is not None and not callable(owner_current)):
            return None
        revision = self._platform_revisions.get(cid)
        epoch = self._platform_epoch

        def current() -> bool:
            try:
                paused = self._platform_paused.get(cid)
                return (not self._platform_stopping
                        and self._platform_epoch == epoch
                        and self._platform_revisions.get(cid) == revision
                        and self.channels.get(cid) is ch
                        and (paused is None or paused[0] is not ch)
                        and not self._platform_retired.get(cid)
                        and not self._platform_cleanup.get(cid)
                        and (owner_current is None or owner_current() is True))
            except Exception:
                return False

        if not current():
            return None
        request = getattr(ch, "request_command_menu_refresh", None)
        return request(guard=current) if callable(request) else None

    def _platform_lock(self, cid: str) -> asyncio.Lock:
        return self._platform_locks.setdefault(cid, asyncio.Lock())

    def _track_platform_cleanup(self, cid: str, task: asyncio.Task) -> None:
        pending = self._platform_cleanup.setdefault(cid, set())
        pending.add(task)

        def done(finished: asyncio.Task) -> None:
            pending.discard(finished)
            if not finished.cancelled():
                with suppress(Exception):
                    finished.exception()  # retrieve a late failure, never echo its details

        task.add_done_callback(done)

    def _current_escalation_source(self, cid: str, source: ChannelAdapter,
                                   revision: int, epoch: int) -> bool:
        if (self._platform_stopping or epoch != self._platform_epoch
                or self.channels.get(cid) is not source
                or self._platform_revisions.get(cid) != revision):
            return False
        paused = self._platform_paused.get(cid)
        return not ((paused is not None and paused[0] is source)
                    or self._platform_retired.get(cid) or self._platform_cleanup.get(cid))

    def _ready_escalation_destination(self, cid: str, destination: ChannelAdapter,
                                      revision: int, epoch: int) -> bool:
        if (not self._current_escalation_source(cid, destination, revision, epoch)
                or not getattr(destination, "_running", False)):
            return False
        try:
            return destination.health.state != "fatal"
        except Exception:
            return False

    @staticmethod
    def _confirmed_failure(source: ChannelAdapter, snapshot: dict) -> bool:
        if type(snapshot) is not dict:
            return False
        if snapshot.get("state") == "fatal":
            return True
        return (snapshot.get("state") == "retrying" and getattr(source, "_running", False)
                and type(snapshot.get("failures")) is int and snapshot["failures"] > 0)

    def _sample_escalation(self, epoch: int) -> None:
        current = {cid: (source, self._platform_revisions.get(cid, 0))
                   for cid, source in tuple(self.channels.items())}
        self._failure_escalation.prune(current)
        for cid, (source, revision) in current.items():
            if (self._platform_stopping or epoch != self._platform_epoch
                    or self.channels.get(cid) is not source
                    or self._platform_revisions.get(cid) != revision):
                continue
            if not self._current_escalation_source(cid, source, revision, epoch):
                self._failure_escalation.observe(cid, source, revision,
                                                 {"state": "unknown"}, False)
                continue
            try:
                raw = source.health_snapshot()
                snapshot = raw if type(raw) is dict else {"state": "unknown"}
            except Exception:
                snapshot = {"state": "unknown"}
            if not self._current_escalation_source(cid, source, revision, epoch):
                continue
            eligible = snapshot.get("state") == "fatal" or bool(getattr(source, "_running", False))
            if self._failure_escalation.observe(cid, source, revision, snapshot, eligible):
                self._queue_escalation_notice(cid, source, revision, epoch,
                                              fatal=snapshot.get("state") == "fatal")

    async def _monitor_escalation(self, epoch: int) -> None:
        while epoch == self._platform_epoch and not self._platform_stopping:
            await asyncio.sleep(escalation_policy.MONITOR_INTERVAL)
            if epoch != self._platform_epoch or self._platform_stopping:
                return
            self._sample_escalation(epoch)

    async def _replace_escalation_monitor(self, epoch: int) -> None:
        old, self._escalation_monitor = self._escalation_monitor, None
        if old is not None:
            old.cancel()
            await asyncio.gather(old, return_exceptions=True)
        if epoch == self._platform_epoch and not self._platform_stopping:
            self._escalation_monitor = asyncio.create_task(
                self._monitor_escalation(epoch), name="channel-failure-monitor")

    def _cancel_notice_tasks(self, cid: str | None = None) -> None:
        for task, owner in tuple(self._notice_owners.items()):
            if cid is None or owner[0] == cid:
                task.cancel()

    async def _stop_escalation(self) -> None:
        from agents.core.lifecycle_budget import TASK_CANCEL_BUDGET

        monitor, self._escalation_monitor = self._escalation_monitor, None
        if monitor is not None:
            monitor.cancel()
            await asyncio.wait({monitor}, timeout=TASK_CANCEL_BUDGET)
        self._cancel_notice_tasks()
        if self._notices:
            await asyncio.wait(set(self._notices), timeout=TASK_CANCEL_BUDGET)
        self._failure_escalation.reset()

    async def wait_platform_cleanup(self, cid: str) -> None:
        """Wait for already scheduled late cleanup (used by lifecycle tests)."""
        while pending := tuple(self._platform_cleanup.get(cid, ())):
            await asyncio.gather(*pending, return_exceptions=True)

    async def _drain_retired(self, cid: str) -> bool:
        """Close each replaced instance before its replacement may start."""
        for old in list(self._platform_retired.get(cid, ())):
            key = (cid, id(old))
            task = self._platform_retire_tasks.get(key)
            if task is None:
                task = asyncio.create_task(self._bounded_platform_stop(cid, old))
                self._platform_retire_tasks[key] = task
                self._track_platform_cleanup(cid, task)
            try:
                stopped = await asyncio.shield(task)
            except asyncio.CancelledError:
                raise
            except Exception:
                stopped = False
            self._platform_retire_tasks.pop(key, None)
            if not stopped:
                return False
            if old in self._platform_retired.get(cid, ()):
                self._platform_retired[cid].remove(old)
        return True

    async def _bounded_platform_stop(self, cid: str, ch: ChannelAdapter) -> bool:
        from agents.core.lifecycle_budget import CHANNEL_STOP_BUDGET

        task = asyncio.create_task(ch.stop())
        try:
            done, _ = await asyncio.wait({task}, timeout=CHANNEL_STOP_BUDGET)
        except asyncio.CancelledError:
            task.cancel()
            self._track_platform_cleanup(cid, task)
            raise
        if not done:
            task.cancel()
            self._track_platform_cleanup(cid, task)
            logger.warning("Channel %s stop did not finish within its budget", cid)
            return False
        if task.cancelled() or task.exception() is not None:
            logger.warning("Channel %s stop failed", cid)
            return False
        return not getattr(ch, "_running", False)

    async def _cleanup_late_start(self, cid: str, ch: ChannelAdapter,
                                  start_task: asyncio.Task) -> None:
        # A shielded SDK worker can finish after its caller timed out or shutdown
        # began. Once it does, close exactly that adapter, never its replacement.
        with suppress(BaseException):
            await start_task
        await self._stop_after_start(cid, ch)

    async def _stop_after_start(self, cid: str, ch: ChannelAdapter) -> None:
        """A failed cleanup is never silently treated as a safe next start."""
        stopped = await self._bounded_platform_stop(cid, ch)
        if not stopped and self.channels.get(cid) is ch:
            self._platform_paused[cid] = (ch, "stop_unconfirmed")

    async def _bounded_platform_start(self, cid: str, ch: ChannelAdapter,
                                      *, owner_resume: bool = False) -> str:
        from agents.core.lifecycle_budget import CHANNEL_START_BUDGET

        epoch = self._platform_epoch
        revision = self._platform_revisions.get(cid, 0)
        task = asyncio.create_task(ch.start())
        self._platform_starts[cid] = task
        try:
            done, _ = await asyncio.wait({task}, timeout=CHANNEL_START_BUDGET)
            if not done:
                task.cancel()
                cleanup = asyncio.create_task(self._cleanup_late_start(cid, ch, task))
                self._track_platform_cleanup(cid, cleanup)
                return "start_unconfirmed"
            if (self._platform_stopping or epoch != self._platform_epoch
                    or revision != self._platform_revisions.get(cid)
                    or self.channels.get(cid) is not ch):
                await self._stop_after_start(cid, ch)
                return "owner_changed" if self.channels.get(cid) is not ch else "shutdown"
            if owner_resume and _safe_mode_active():
                await self._stop_after_start(cid, ch)
                return "safe_mode"
            if (task.cancelled() or task.exception() is not None
                    or not getattr(ch, "_running", False)):
                await self._stop_after_start(cid, ch)
                return "start_failed"
            return "resumed"
        except asyncio.CancelledError:
            task.cancel()
            cleanup = asyncio.create_task(self._cleanup_late_start(cid, ch, task))
            self._track_platform_cleanup(cid, cleanup)
            raise
        finally:
            if self._platform_starts.get(cid) is task:
                self._platform_starts.pop(cid, None)

    async def platform_snapshot(self) -> dict[str, dict]:
        """Bounded callers may render the registered channels and pause intent."""
        rows = {}
        for cid, ch in list(self.channels.items()):
            try:
                row = ch.health_snapshot()
                row = dict(row) if isinstance(row, dict) else {"state": "unknown"}
            except Exception:
                row = {"state": "unknown"}
            paused = self._platform_paused.get(cid)
            row["pause_state"] = ("cleanup_unconfirmed" if self._platform_retired.get(cid)
                                  else paused[1] if paused and paused[0] is ch else None)
            rows[cid] = row
        return rows

    async def pause_failed(self, cid: str) -> dict[str, str]:
        if self._platform_stopping:
            return {"status": "shutdown"}
        async with self._platform_lock(cid):
            ch = self.channels.get(cid)
            if ch is None:
                return {"status": "unknown"}
            paused = self._platform_paused.get(cid)
            if paused and paused[0] is ch:
                return {"status": "already_paused"}
            if self._platform_stopping:
                return {"status": "shutdown"}
            try:
                health = ch.health_snapshot()
            except Exception:
                return {"status": "not_failed"}
            if not isinstance(health, dict) or not (
                health.get("state") == "fatal" or
                (health.get("state") == "retrying"
                 and type(health.get("failures")) is int and health["failures"] > 0)
            ):
                return {"status": "not_failed"}
            epoch = self._platform_epoch
            revision = self._platform_revisions.get(cid)
            self._platform_paused[cid] = (ch, "stop_unconfirmed")
            stopped = await self._bounded_platform_stop(cid, ch)
            if (epoch != self._platform_epoch or revision != self._platform_revisions.get(cid)
                    or self.channels.get(cid) is not ch):
                return {"status": "owner_changed"}
            if stopped:
                self._platform_paused[cid] = (ch, "paused")
                return {"status": "paused"}
            return {"status": "stop_unconfirmed"}

    async def resume_paused(self, cid: str) -> dict[str, str]:
        if self._platform_stopping:
            return {"status": "shutdown"}
        async with self._platform_lock(cid):
            ch = self.channels.get(cid)
            if ch is None:
                return {"status": "unknown"}
            paused = self._platform_paused.get(cid)
            if paused is None or paused[0] is not ch:
                return {"status": "not_paused"}
            if self._platform_stopping:
                return {"status": "shutdown"}
            if _safe_mode_active():
                return {"status": "safe_mode"}
            if self._platform_cleanup.get(cid):
                return {"status": "start_unconfirmed"}
            epoch = self._platform_epoch
            revision = self._platform_revisions.get(cid)
            if not await self._drain_retired(cid):
                return {"status": "cleanup_unconfirmed"}
            if (self._platform_stopping or epoch != self._platform_epoch):
                return {"status": "shutdown"}
            if self.channels.get(cid) is not ch or revision != self._platform_revisions.get(cid):
                return {"status": "owner_changed"}
            if _safe_mode_active():
                return {"status": "safe_mode"}
            if paused[1] == "stop_unconfirmed":
                # _running may turn False before an SDK close finishes. Retry the
                # idempotent stop; a flag alone is never evidence of teardown.
                if not await self._bounded_platform_stop(cid, ch):
                    return {"status": "stop_unconfirmed"}
                if (self.channels.get(cid) is not ch
                        or revision != self._platform_revisions.get(cid)):
                    return {"status": "owner_changed"}
                if self._platform_stopping or epoch != self._platform_epoch:
                    return {"status": "shutdown"}
                if _safe_mode_active():
                    return {"status": "safe_mode"}
                self._platform_paused[cid] = (ch, "paused")
            result = await self._bounded_platform_start(cid, ch, owner_resume=True)
            if result == "resumed":
                self._platform_paused.pop(cid, None)
            return {"status": result}

    async def start_all(self) -> None:
        if self._platform_stop_calls:
            return
        # An explicit new lifecycle can reopen after stop_all; a pending old start
        # still carries its earlier epoch and must close its own adapter when done.
        self._platform_stopping = False
        self._platform_epoch += 1
        epoch = self._platform_epoch
        self._escalation_loop = asyncio.get_running_loop()
        await self._replace_escalation_monitor(epoch)
        if self._platform_stopping or epoch != self._platform_epoch:
            return
        # H081: close the ledger rows a previous process left open (never resent).
        store = delivery_ledger.store()
        if store is not None:
            try:
                store.recover()
            except Exception:
                logger.warning("Delivery ledger recovery failed", exc_info=True)
        for cid, ch in list(self.channels.items()):
            async with self._platform_lock(cid):
                if self._platform_stopping or epoch != self._platform_epoch:
                    return
                if self.channels.get(cid) is not ch:
                    continue
                if not await self._drain_retired(cid):
                    log_error(logger, E_CHANNEL_START_FAIL, name=cid, detail="old adapter cleanup unconfirmed")
                    continue
                if (self._platform_stopping or epoch != self._platform_epoch
                        or self.channels.get(cid) is not ch):
                    return
                if cid in self._platform_paused or self._platform_cleanup.get(cid):
                    continue
                if getattr(ch, "_running", False):
                    continue
                result = await self._bounded_platform_start(cid, ch)
                if result != "resumed":
                    log_error(logger, E_CHANNEL_START_FAIL, name=cid, detail=result)

    async def stop_all(self) -> None:
        """Stop every channel, each within CHANNEL_STOP_BUDGET (H677): one that hangs is
        named and left behind, never allowed to hold the rest of shutdown."""
        # Legacy in-process harnesses construct a manager with __new__ and only set
        # channels. Give that minimal object the same lifecycle bookkeeping.
        if not hasattr(self, "_platform_epoch"):
            self._platform_epoch = 0
            self._platform_starts = {}
            self._platform_cleanup = {}
            self._platform_retired = {}
            self._platform_retire_tasks = {}
            self._platform_stop_calls = 0
        if not hasattr(self, "_failure_escalation"):
            self._failure_escalation = escalation_policy.FailureEscalation()
            self._escalation_monitor = None
            self._escalation_loop = None
            self._notices = set()
            self._notice_owners = {}
        self._platform_stopping = True
        self._platform_stop_calls += 1
        self._platform_stop_in_progress = True
        self._platform_epoch += 1
        for task in tuple(self._platform_starts.values()):
            task.cancel()
        try:
            await self._stop_escalation()
            for cid, ch in list(self.channels.items()):
                # Do not wait for a start/resume lock: a shielded SDK worker may
                # still own it. Stop gets its own short budget, then late-start
                # cleanup closes that same adapter once the worker finally exits.
                await self._bounded_platform_stop(cid, ch)
            for cid in list(self._platform_retired):
                await self._drain_retired(cid)
        finally:
            self._platform_stop_calls -= 1
            self._platform_stop_in_progress = bool(self._platform_stop_calls)

    def _fatal_notice(self, channel_id: str, _reason: str,
                      source: ChannelAdapter | None = None, revision: int | None = None) -> None:
        """Admit a native fatal callback on the manager loop with exact source ownership."""
        source = self.channels.get(channel_id) if source is None else source
        revision = self._platform_revisions.get(channel_id) if revision is None else revision
        loop = self._escalation_loop
        if source is None or revision is None or loop is None or loop.is_closed():
            return
        epoch = self._platform_epoch
        try:
            if asyncio.get_running_loop() is loop:
                self._admit_fatal_notice(channel_id, source, revision, epoch)
                return
        except RuntimeError:
            pass
        # Closed loop: the future monitor can observe an unspent fatal state.
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(self._admit_fatal_notice, channel_id, source, revision, epoch)

    def _admit_fatal_notice(self, cid: str, source: ChannelAdapter,
                            revision: int, epoch: int) -> None:
        if not self._current_escalation_source(cid, source, revision, epoch):
            return
        if self._failure_escalation.fatal(cid, source, revision):
            self._queue_escalation_notice(cid, source, revision, epoch, fatal=True)

    def _queue_escalation_notice(self, cid: str, source: ChannelAdapter,
                                 revision: int, epoch: int, *, fatal: bool) -> None:
        """Spend the episode once; use only an existing governed direct-send route."""
        from .outbound import resolve_destination

        label = _NOTICE_LABELS.get(cid)
        subject = f"Nerva's {label} channel" if label else "A channel"
        text = (f"{subject} is unavailable. Check Channel Status."
                if fatal else f"{subject} has been unavailable for several minutes. Check Channel Status.")
        for other in ("ntfy", "telegram"):
            adapter = self.channels.get(other)
            dest_revision = self._platform_revisions.get(other)
            if (other == cid or adapter is None or dest_revision is None
                    or not self._ready_escalation_destination(
                        other, adapter, dest_revision, epoch)):
                continue
            try:
                kwargs, _why = resolve_destination(self, other)
            except Exception:
                logger.warning("Owner notice destination could not be resolved")
                continue
            if kwargs is None:
                continue
            task = asyncio.create_task(self._deliver_escalation_notice(
                cid, source, revision, epoch, other, adapter, dest_revision, text, kwargs))
            self._notices.add(task)
            self._notice_owners[task] = (cid, source, revision, epoch)

            def done(finished: asyncio.Task) -> None:
                self._notices.discard(finished)
                self._notice_owners.pop(finished, None)
                if not finished.cancelled():
                    with suppress(Exception):
                        finished.exception()

            task.add_done_callback(done)
            return
        logger.error("A channel is unavailable and no owner notice destination is ready")

    async def _deliver_escalation_notice(self, cid: str, source: ChannelAdapter,
                                          revision: int, epoch: int, other: str,
                                          destination: ChannelAdapter, dest_revision: int | None,
                                          text: str, kwargs: dict) -> None:
        if not self._current_escalation_source(cid, source, revision, epoch):
            return
        if (dest_revision is None or not self._ready_escalation_destination(
                other, destination, dest_revision, epoch)):
            return
        try:
            raw = source.health_snapshot()
            snapshot = raw if type(raw) is dict else {"state": "unknown"}
        except Exception:
            return
        if (not self._current_escalation_source(cid, source, revision, epoch)
                or not self._confirmed_failure(source, snapshot)
                or not self._ready_escalation_destination(
                    other, destination, dest_revision, epoch)):
            return
        await self.send(other, text, voice=False, plain=True, **kwargs)

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
        from .outbound_safety import is_silence

        # Even a no-op reply must not silently accept an invalid supplied key.
        if "delivery_key" in kwargs and not delivery_ledger.valid_delivery_key(kwargs["delivery_key"]):
            return False
        if is_silence(_delivery_text(response)):
            # H069: the agent's choice to send nothing — no message and no receipt.
            return True
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
                        delivery_key, send, *, require_ack: bool = False,
                        card_attempt: CardAttempt | None = None) -> bool:
        """H081 — one send with its ledger row: pending, attempting, then sent / failed /
        partial / unknown. A dead target or a duplicate ``delivery_key`` is not sent (a
        duplicate of a delivered send answers True). A keyed send needs a durable
        claim before transport; unkeyed sends retain best-effort receipts."""
        keyed = delivery_key is not None
        if not delivery_ledger.valid_delivery_key(delivery_key):
            return False
        try:
            store = delivery_ledger.store()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Delivery ledger unavailable", exc_info=True)
            store = None
        if keyed and store is None:
            return False
        target = _delivery_target(channel, adapter, kwargs)
        delivery = None
        if store is not None:
            try:
                delivery = store.open_delivery(channel, target, _delivery_text(response),
                                               key=delivery_key)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Delivery ledger claim unavailable", exc_info=True)
                if keyed:
                    return False
        if keyed and delivery is None:
            return False
        if delivery is not None and not delivery.send:
            if card_attempt is not None:
                card_attempt.disposition = "skipped"
            return delivery.already_sent
        outcome, token = delivery_ledger.begin_outcome()
        try:
            if delivery is not None:
                if keyed:
                    try:
                        if delivery.attempting_checked() is not True:
                            return False
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.warning("Delivery ledger attempt claim unavailable", exc_info=True)
                        return False
                else:
                    delivery.attempting()
            try:
                if card_attempt is not None:
                    # An exception inside the adapter may follow a completed POST.
                    # Keep the conservative state until the adapter returns.
                    card_attempt.disposition = "unknown"
                ok = bool(await send())
                if (require_ack and not ok and outcome.kind is None and not outcome.partial
                        and not outcome.ambiguous and not outcome.dead and not outcome.fatal):
                    # A card transport returned no usable native receipt. It may have
                    # reached the platform; retain an adapter's definite failure note.
                    outcome.kind = "missing_ack"
                    outcome.ambiguous = True
            except BaseException as exc:
                if card_attempt is not None:
                    card_attempt.disposition = "unknown"
                if delivery is not None:
                    delivery.raised(exc)
                raise
        finally:
            delivery_ledger.end_outcome(token)
        if card_attempt is not None:
            card_attempt.disposition = (
                "sent" if ok else "partial" if outcome.partial else
                "unknown" if outcome.ambiguous else "failed"
            )
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

    async def send_pending_card(self, channel: str, response, markup: dict, *,
                                attempt: CardAttempt | None = None, **kwargs) -> int | None:
        """Direct Telegram prompt delivery through the existing send contract.

        A verified Bot API message receipt is required to bind buttons. Workspace
        channels retain their governed reply path; this API cannot send to them.
        """
        # The ledger stores no native receipt. A keyed duplicate cannot return a
        # bindable message ID, so these prompt APIs refuse supplied keys outright.
        if attempt is not None and type(attempt) is not CardAttempt:
            return None
        if attempt is not None:
            attempt.disposition = "not_attempted"
        if "delivery_key" in kwargs:
            return None
        ch = self.channels.get(channel)
        send = getattr(ch, "send_pending_card", None)
        if (channel != "telegram" or not callable(send) or type(markup) is not dict
                or self._contract_denial(channel, response, {**kwargs, "reply_markup": markup})
                is not None):
            return None
        receipt = None

        async def transport():
            nonlocal receipt
            receipt = await send(response, reply_markup=markup, **kwargs)
            return type(receipt) is int and receipt > 0

        ok = await self._ledgered(channel, ch, response, kwargs, None, transport,
                                  require_ack=True, card_attempt=attempt)
        return receipt if ok else None

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
        if "delivery_key" in kwargs:
            return None
        adapter = self.channels.get(channel)
        send = getattr(adapter, "send_pending_card", None)
        if (channel not in {"slack", "discord"} or not callable(send) or not valid_markup(markup)
                or self._reply_contract_denial(channel, response, kwargs) is not None):
            return None
        receipt = None

        async def transport():
            nonlocal receipt
            receipt = await send(response, reply_markup=markup, **kwargs)
            return valid_receipt(receipt) and receipt["channel"] == channel

        ok = await self._ledgered(channel, adapter, response, kwargs, None, transport, require_ack=True)
        return receipt if ok else None

    async def send_channel_text_prompt(self, channel: str, response, *, current, **kwargs) -> bool:
        """Text-only prompt transport, consumed by the governed reply executor."""
        if "delivery_key" in kwargs:
            return False
        adapter = self.channels.get(channel)
        send = getattr(adapter, "send_reply", None)
        if (channel != "ntfy" or not callable(send) or not callable(current)
                or self._reply_contract_denial(channel, response, kwargs) is not None):
            return False
        async def transport():
            return await send(response, current=current, plain=True, **kwargs) is True

        return await self._ledgered(channel, adapter, response, kwargs, None, transport)

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
