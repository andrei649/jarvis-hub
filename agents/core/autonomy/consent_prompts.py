"""Private, transport-bound registrations for reusable Telegram owner consent."""

from __future__ import annotations

import asyncio
import copy
import json
import math
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..approval_outcomes import ApprovalTurnContext, current_approval_turn
from ..channels.outbound import _owner_chat_id
from ..native_human_wait import native_human_wait_window
from ..owner_once_context import OwnerReplySource, current_owner_reply_source
from .consent_authority import make_telegram_consent_actor
from .consent_types import ConsentDecisionResult, ConsentOffer, ConsentWaitOutcome
from .decision_reasons import normalize_reason
from .inbox import build_consent_card, parse_consent_callback_data

_MAX_PENDING = 32
_REPLY_SECONDS = 120.0


@dataclass(eq=False)
class _Invocation:
    source: OwnerReplySource
    turn: ApprovalTurnContext
    invoking_task: asyncio.Task
    identity: tuple
    check: Callable[[], bool]


@dataclass(eq=False)
class _Prompt:
    offer: ConsentOffer
    identity: tuple
    channel: object
    generation: str
    chat_id: int
    owner_binding: tuple
    deadline: float
    check: Callable[[], bool]
    source: OwnerReplySource | None = None
    turn: ApprovalTurnContext | None = None
    request_task: asyncio.Task | None = None
    future: asyncio.Future | None = None
    delivery: asyncio.Future | None = None
    nonce: str = ""
    message_id: int | None = None
    delivered_at: float | None = None
    active: bool = True
    inflight: bool = False
    denial_task: asyncio.Task | None = None
    settled_result: ConsentDecisionResult | None = None
    retired_outcome: ConsentWaitOutcome | None = None


class ConsentPrompts:
    """One coordinator's bounded native-delivery registrations.

    Queue transactions own durable authority. The registry lock protects only
    in-memory references and never encloses queue or transport calls.
    """

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.worker = coordinator._orch.autonomy
        self.queue = self.worker.queue
        self._pending: dict[str, _Prompt] = {}
        self._origins: dict[int, _Invocation] = {}
        self._lock = threading.RLock()
        self._pending_hook = self.pending
        self._callback_hook = self.callback
        self._denial_pending_hook = self.denial_pending
        self._denial_hook = self.denial_reply
        self._stop_hook = self.stop

    def install(self, channel) -> None:
        channel.consent_pending = self._pending_hook
        channel.on_consent_callback = self._callback_hook
        channel.consent_denial_pending = self._denial_pending_hook
        channel.on_consent_denial_reply = self._denial_hook
        channel.on_consent_stop = self._stop_hook

    @staticmethod
    def _identity(task) -> tuple:
        return tuple(copy.deepcopy(getattr(task, name)) for name in (
            "created_at", "agent", "kind", "title", "payload", "risk_tier",
            "autonomy_level", "origin", "kernel_intake_id", "approval_deadline_at",
        ))

    def _owner_binding(self, channel) -> tuple | None:
        try:
            settings = self.coordinator._owner_settings()
            if type(settings) is not dict:
                return None
            chat = _owner_chat_id(
                self.coordinator._orch,
                configured_owner=settings.get("autonomy.owner_chat_id"),
            )
            return (chat, copy.deepcopy(settings.get("autonomy.owner_user_ids")),
                    copy.deepcopy(getattr(channel, "allowed_users", None)))
        except Exception:
            return None

    def _runtime_live(self, channel, generation, chat_id, binding) -> bool:
        try:
            orch = self.coordinator._orch
            return (
                orch.autonomy is self.worker and self.worker.queue is self.queue
                and orch.channels.get("telegram") is channel
                and channel.consent_pending is self._pending_hook
                and channel.on_consent_callback is self._callback_hook
                and channel.consent_denial_pending is self._denial_pending_hook
                and channel.on_consent_denial_reply is self._denial_hook
                and channel.on_consent_stop is self._stop_hook
                and channel._owner_once_live(generation)
                and type(chat_id) is int and str(chat_id) == binding[0]
                and self._owner_binding(channel) == binding
            )
        except Exception:
            return False

    def _source_live(self, source, turn) -> bool:
        try:
            return (
                type(source) is OwnerReplySource and type(turn) is ApprovalTurnContext
                and source.live() and turn.live()
                and self._runtime_live(source.channel, source.generation, source.chat_id,
                                       self._owner_binding(source.channel))
                and self.coordinator._callback_is_owner(source.chat_id, source.user_id) is True
                and turn.principal_key == json.dumps(
                    ["telegram", str(source.user_id), str(source.chat_id)],
                    separators=(",", ":"),
                )
            )
        except Exception:
            return False

    def _origin_live(self, origin) -> bool:
        try:
            return (self._source_live(origin.source, origin.turn)
                    and not origin.invoking_task.done()
                    and not origin.invoking_task.cancelling()
                    and origin.check() is True)
        except Exception:
            return False

    def register_invocation(self, task_id: int, *, check) -> bool:
        source, turn = current_owner_reply_source(), current_approval_turn()
        invoking_task = asyncio.current_task()
        if (source is None or turn is None or not callable(check)
                or not isinstance(invoking_task, asyncio.Task)
                or invoking_task.done() or invoking_task.cancelling()
                or invoking_task.get_loop() is not source.originating_task.get_loop()
                or not self._source_live(source, turn)):
            return False
        task = self.queue.get(task_id)
        if task is None or task.kind != "toolrpc.terminal_run":
            return False
        origin = _Invocation(source, turn, invoking_task, self._identity(task), check)
        if not self._origin_live(origin):
            return False
        with self._lock:
            previous = tuple(self._origins.items())
        stale = tuple(key for key, value in previous if not self._origin_live(value))
        with self._lock:
            for key in stale:
                if self._origins.get(key) is dict(previous).get(key):
                    self._origins.pop(key, None)
            if task_id in self._origins or len(self._origins) >= _MAX_PENDING:
                return False
            self._origins[task_id] = origin
        return True

    def reply_available(self, task_id: int) -> bool:
        with self._lock:
            origin = self._origins.get(task_id)
        if (origin is None or asyncio.current_task() is not origin.invoking_task
                or not self._origin_live(origin)):
            return False
        task = self.queue.get(task_id)
        return task is not None and self._identity(task) == origin.identity

    def release_invocation(self, task_id: int) -> None:
        with self._lock:
            self._origins.pop(task_id, None)

    def _deadline(self, task) -> float | None:
        try:
            remaining = _REPLY_SECONDS
            if task.approval_deadline_at is not None:
                remaining = min(remaining, (
                    datetime.fromisoformat(task.approval_deadline_at) - datetime.now(UTC)
                ).total_seconds())
            return time.monotonic() + remaining if remaining > 0 else None
        except Exception:
            return None

    def _transport_live(self, prompt: _Prompt) -> bool:
        try:
            if (not prompt.active or time.monotonic() >= prompt.deadline
                    or not self._runtime_live(prompt.channel, prompt.generation,
                                              prompt.chat_id, prompt.owner_binding)
                    or prompt.check() is not True):
                return False
            if prompt.source is not None:
                return self._source_live(prompt.source, prompt.turn)
            return True
        except Exception:
            return False

    def _request_live(self, prompt: _Prompt) -> bool:
        task, future = prompt.request_task, prompt.future
        if task is None:
            return True
        return (future is not None and not future.done() and not task.done()
                and not task.cancelling() and future.get_loop().is_running()
                and not future.get_loop().is_closed())

    def _offer_current(self, prompt: _Prompt) -> bool:
        # Do not call this from the actor predicate: queue invokes that predicate
        # inside its own write transaction and rechecks the offer there.
        task = self.queue.get(prompt.offer.task_id)
        offer = self.queue.pending_consent_offer(prompt.offer.task_id)
        return (task is not None and self._identity(task) == prompt.identity
                and offer == prompt.offer)

    def decision_committed(self, task_id: int, revision: str,
                           result: ConsentDecisionResult) -> None:
        """Report a committed cross-surface choice to its exact live native wait.

        This is an observation, never an execution capability. The worker calls
        it only after queue CAS; the invoking tool still verifies durable state
        and its own private physical-dispatch proof.
        """
        if (type(task_id) is not int or type(revision) is not str
                or type(result) is not ConsentDecisionResult):
            return
        tasks = {task.id: task for task in result.tasks}
        if task_id not in tasks or len(tasks) != len(result.tasks):
            return
        with self._lock:
            prompts = tuple(self._pending.values())
        for prompt in prompts:
            if (prompt.offer.revision != revision or task_id not in prompt.offer.member_ids
                    or set(tasks) != set(prompt.offer.member_ids)
                    or type(prompt.message_id) is not int or prompt.message_id <= 0
                    or not self._transport_live(prompt) or not self._request_live(prompt)):
                continue
            settled = tasks.get(prompt.offer.task_id)
            durable = self.queue.get(prompt.offer.task_id)
            if (settled is None or durable is None
                    or self._identity(settled) != prompt.identity
                    or self._identity(durable) != prompt.identity
                    or durable.status not in {'approved', 'rejected'}
                    or durable.status != settled.status
                    or type(durable.human_decision) is not dict
                    or durable.human_decision != settled.human_decision
                    or durable.human_decision.get('action') not in {'session', 'always', 'deny'}):
                continue
            self._retire(prompt, result)

    def _retire(self, prompt: _Prompt, result=None) -> None:
        with self._lock:
            if result is not None:
                # Publish the receipt before deactivation, even when the future
                # must be woken on a different event loop.
                prompt.settled_result = result
            elif prompt.settled_result is None and prompt.retired_outcome is None:
                # A concurrent notification may prune an expired inline prompt
                # before its waiter resumes. Record the first no-result exit now:
                # an earlier withdrawal must not become a timeout merely because
                # its wake callback ran after the deadline.
                state = 'timeout' if time.monotonic() >= prompt.deadline else 'withdrawn'
                prompt.retired_outcome = ConsentWaitOutcome(state, prompt.offer.revision)
            prompt.active = False
            if self._pending.get(prompt.nonce) is prompt:
                self._pending.pop(prompt.nonce, None)
        future = prompt.future
        if future is not None:
            loop = future.get_loop()

            def wake():
                if not future.done():
                    future.set_result(result)

            try:
                if loop.is_running() and not loop.is_closed():
                    loop.call_soon_threadsafe(wake)
            except RuntimeError:
                pass
        delivery = prompt.delivery
        if delivery is not None and not delivery.done():
            loop = delivery.get_loop()
            try:
                if loop.is_running() and not loop.is_closed():
                    loop.call_soon_threadsafe(
                        lambda: not delivery.done() and delivery.set_result(False),
                    )
            except RuntimeError:
                pass

    def _committed_reply(self, prompt: _Prompt) -> ConsentDecisionResult | None:
        with self._lock:
            if prompt.settled_result is not None:
                return prompt.settled_result
        if not self._transport_live(prompt) or not self._request_live(prompt):
            return None
        tasks = tuple(self.queue.get(task_id) for task_id in prompt.offer.member_ids)
        primary = next((task for task in tasks if task is not None
                        and task.id == prompt.offer.task_id), None)
        if primary is None or self._identity(primary) != prompt.identity:
            return None
        human = getattr(primary, 'human_decision', None)
        choice = human.get('action') if type(human) is dict else None
        if choice not in {'session', 'always', 'deny'}:
            return None
        for task in tasks:
            human = task.human_decision if task is not None else None
            if (type(human) is not dict or human.get('offer_revision') != prompt.offer.revision
                    or human.get('action') != choice or task.decision != f'consent-{choice}'
                    or task.status not in ({'rejected'} if choice == 'deny'
                                           else {'approved', 'running', 'done', 'failed'})):
                return None
        # A delayed/lost observer notification must not erase a queue-CAS choice
        # on the same displayed revision. Execution still needs its private proof.
        return ConsentDecisionResult(tasks)

    def _prune_dead(self) -> None:
        with self._lock:
            prompts = tuple(self._pending.values())
        for prompt in prompts:
            if not self._transport_live(prompt) or not self._request_live(prompt):
                self._retire(prompt)

    def _place(self, prompt: _Prompt, *, same_chat: bool) -> bool:
        self._prune_dead()
        with self._lock:
            existing = tuple(p for p in self._pending.values()
                             if p.offer.task_id == prompt.offer.task_id)
            if not same_chat and any(p.source is not None and p.active
                                     and p.offer == prompt.offer for p in existing):
                return False
            for old in existing:
                old.active = False
                self._pending.pop(old.nonce, None)
            if len(self._pending) >= _MAX_PENDING:
                return False
            self._pending[prompt.nonce] = prompt
        for old in existing:
            self._retire(old)
        return True

    def _place_notification(self, prompt: _Prompt) -> _Prompt | None:
        """Share one in-flight native receipt for duplicate notifier dispatches."""
        self._prune_dead()
        with self._lock:
            existing = tuple(p for p in self._pending.values()
                             if p.offer.task_id == prompt.offer.task_id)
            for old in existing:
                if (old.active and old.offer == prompt.offer
                        and old.channel is prompt.channel and old.chat_id == prompt.chat_id
                        and old.generation == prompt.generation
                        and old.owner_binding == prompt.owner_binding
                        and old.deadline > time.monotonic()):
                    return old
            for old in existing:
                old.active = False
                self._pending.pop(old.nonce, None)
            if len(self._pending) >= _MAX_PENDING:
                return None
            self._pending[prompt.nonce] = prompt
        for old in existing:
            self._retire(old)
        return prompt

    def _make_prompt(self, task, offer, channel, chat_id, check, *, source=None,
                     turn=None, request_task=None, future=None) -> _Prompt | None:
        generation = channel._owner_once_generation
        binding = self._owner_binding(channel)
        deadline = self._deadline(task)
        if (binding is None or deadline is None
                or not self._runtime_live(channel, generation, chat_id, binding)):
            return None
        return _Prompt(
            offer, self._identity(task), channel, generation, chat_id,
            binding, deadline, check, source=source, turn=turn,
            request_task=request_task, future=future,
            delivery=asyncio.get_running_loop().create_future(),
            nonce=secrets.token_hex(16),
        )

    async def _send(self, prompt: _Prompt) -> int | None:
        card = build_consent_card(self.queue.get(prompt.offer.task_id),
                                  prompt.offer, prompt.nonce)
        source = prompt.source
        if source is not None and source.originating_task.get_loop() is not asyncio.get_running_loop():
            sent = asyncio.run_coroutine_threadsafe(
                prompt.channel.send_consent_card(prompt.chat_id, card),
                source.originating_task.get_loop(),
            )
            return await asyncio.wrap_future(sent)
        return await prompt.channel.send_consent_card(prompt.chat_id, card)

    async def request(self, task_id: int, *, check
                      ) -> ConsentDecisionResult | ConsentWaitOutcome | None:
        source, turn = current_owner_reply_source(), current_approval_turn()
        with self._lock:
            origin = self._origins.get(task_id)
        if (origin is None or source is not origin.source or turn is not origin.turn
                or asyncio.current_task() is not origin.invoking_task
                or not callable(check) or not self.reply_available(task_id)):
            return None
        task = self.queue.get(task_id)
        offer = self.queue.pending_consent_offer(task_id)
        if task is None or offer is None or self._identity(task) != origin.identity:
            return None
        prompt = self._make_prompt(
            task, offer, source.channel, source.chat_id,
            lambda: origin.check() is True and check() is True,
            source=source, turn=turn, request_task=asyncio.current_task(),
            future=asyncio.get_running_loop().create_future(),
        )
        if prompt is None or not self._place(prompt, same_chat=True):
            return None
        delivered = False
        try:
            if not self._transport_live(prompt) or not self._offer_current(prompt):
                return None
            remaining = prompt.deadline - time.monotonic()
            message_id = await asyncio.wait_for(self._send(prompt), remaining)
            if (type(message_id) is not int or message_id <= 0
                    or not self._transport_live(prompt) or not self._offer_current(prompt)):
                return None
            with self._lock:
                if not prompt.active:
                    return None
                prompt.delivered_at = time.monotonic()
                prompt.message_id = message_id
                prompt.delivery.set_result(True)
                delivered = True
            remaining = prompt.deadline - time.monotonic()
            if remaining <= 0:
                return ConsentWaitOutcome('timeout', prompt.offer.revision)
            # Verified delivery, exact request registration and current offer own
            # this wait. Sending a card and arbitrary handler residency earn no credit.
            with native_human_wait_window(
                deadline=prompt.deadline,
                current=lambda: self._transport_live(prompt) and self._origin_live(origin)
                and self._offer_current(prompt),
            ):
                while not prompt.future.done():
                    committed = self._committed_reply(prompt)
                    if committed is not None:
                        return committed
                    with self._lock:
                        retired = prompt.retired_outcome
                    if retired is not None:
                        return retired
                    remaining = prompt.deadline - time.monotonic()
                    if remaining <= 0:
                        return ConsentWaitOutcome('timeout', prompt.offer.revision)
                    if (not self._transport_live(prompt) or not self._request_live(prompt)
                            or not self._offer_current(prompt)):
                        return ConsentWaitOutcome('withdrawn', prompt.offer.revision)
                    # Source/transport withdrawal must settle without waiting
                    # for the original hard deadline. Polling earns no authority.
                    await asyncio.wait({prompt.future}, timeout=min(0.05, remaining))
                return (self._committed_reply(prompt) or prompt.future.result()
                        or prompt.retired_outcome
                        or ConsentWaitOutcome('withdrawn', prompt.offer.revision))
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return ConsentWaitOutcome('timeout', prompt.offer.revision) if delivered else None
        except Exception:
            return None
        finally:
            self._retire(prompt)

    async def notify(self, task, channel, chat_id: int) -> bool:
        """Send one unsolicited current offer to the configured owner chat."""
        if type(chat_id) is not int or type(getattr(task, "id", None)) is not int:
            return False
        current_task = self.queue.get(task.id)
        offer = self.queue.pending_consent_offer(task.id)
        if (current_task is None or offer is None
                or self._identity(current_task) != self._identity(task)):
            return False
        prompt = self._make_prompt(current_task, offer, channel, chat_id, lambda: True)
        if prompt is None:
            return False
        placed = self._place_notification(prompt)
        if placed is None:
            return False
        if placed is not prompt:
            try:
                remaining = placed.deadline - time.monotonic()
                if remaining <= 0 or placed.delivery is None:
                    return False
                delivered = await asyncio.wait_for(asyncio.shield(placed.delivery), remaining)
                return (delivered is True and type(placed.message_id) is int
                        and placed.message_id > 0 and self._transport_live(placed)
                        and self._offer_current(placed))
            except Exception:
                return False
        try:
            if not self._transport_live(prompt) or not self._offer_current(prompt):
                return False
            remaining = prompt.deadline - time.monotonic()
            message_id = await asyncio.wait_for(self._send(prompt), remaining)
            if (type(message_id) is not int or message_id <= 0
                    or not self._transport_live(prompt) or not self._offer_current(prompt)):
                return False
            with self._lock:
                if not prompt.active:
                    return False
                prompt.delivered_at = time.monotonic()
                prompt.message_id = message_id
                prompt.delivery.set_result(True)
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            return False
        finally:
            if prompt.message_id is None:
                self._retire(prompt)

    def _matched(self, nonce, *, chat_id, user_id, message_id) -> _Prompt | None:
        with self._lock:
            prompt = self._pending.get(nonce) if type(nonce) is str else None
        if (prompt is None or prompt.inflight or type(chat_id) is not int
                or type(user_id) is not int or type(message_id) is not int
                or chat_id != prompt.chat_id or message_id != prompt.message_id
                or prompt.source is not None and user_id != prompt.source.user_id
                or not self._transport_live(prompt) or not self._request_live(prompt)
                or self.coordinator._callback_is_owner(chat_id, user_id) is not True
                or not self._offer_current(prompt)):
            return None
        return prompt

    def pending(self, callback: dict) -> bool:
        try:
            parsed = parse_consent_callback_data(callback.get("data"))
            message = callback.get("message") or {}
            return (parsed is not None and self._matched(
                parsed[0], chat_id=(message.get("chat") or {}).get("id"),
                user_id=(callback.get("from") or {}).get("id"),
                message_id=message.get("message_id")) is not None)
        except Exception:
            return False

    def denial_pending(self, *, chat_id, user_id, reply_to_message_id) -> bool:
        """Select one current delivered card without mutating its offer."""
        if (type(chat_id) is not int or type(user_id) is not int
                or type(reply_to_message_id) is not int or reply_to_message_id <= 0):
            return False
        with self._lock:
            matches = tuple(prompt for prompt in self._pending.values()
                            if prompt.chat_id == chat_id
                            and prompt.message_id == reply_to_message_id
                            and prompt.delivered_at is not None)
        return (len(matches) == 1 and self._matched(
            matches[0].nonce, chat_id=chat_id, user_id=user_id,
            message_id=reply_to_message_id,
        ) is matches[0])

    async def callback(self, nonce, choice, *, chat_id, user_id, message_id) -> str | None:
        if choice not in {"session", "always", "deny"}:
            return None
        prompt = self._matched(nonce, chat_id=chat_id, user_id=user_id,
                               message_id=message_id)
        if prompt is None:
            return None
        dispatch_task = asyncio.current_task()
        with self._lock:
            if self._pending.get(nonce) is not prompt or prompt.inflight:
                return None
            prompt.inflight = True

        def current() -> bool:
            # Queue calls this while holding its write transaction. Never read
            # the queue here; its own CAS revalidates revision and each member.
            return (
                self._pending.get(nonce) is prompt and prompt.inflight
                and asyncio.current_task() is dispatch_task
                and prompt.channel._consent_fast.get(nonce) is dispatch_task
                and self._transport_live(prompt) and self._request_live(prompt)
                and self.coordinator._callback_is_owner(chat_id, user_id) is True
                and chat_id == prompt.chat_id and message_id == prompt.message_id
                and (prompt.source is None or user_id == prompt.source.user_id)
            )

        result = None
        try:
            actor = make_telegram_consent_actor(
                user_id=user_id, chat_id=chat_id, current=current,
            )
            if actor is None or not current():
                return None
            result = await self.worker.apply_consent_decision(
                prompt.offer.task_id, prompt.offer.revision, choice=choice, actor=actor,
            )
            return "accepted" if result is not None else None
        finally:
            self._retire(prompt, result)

    async def denial_reply(
        self, reason: str | None, *, chat_id, user_id, message_id,
        reply_to_message_id, received_at,
    ) -> str | None:
        """Reject only the exact delivered card reached through native Telegram dispatch.

        The update text carries metadata, never a task selector or grant. The private
        fast-task registration proves this call came from the channel's original
        message path; queue CAS still owns the durable decision.
        """
        dispatch_task = asyncio.current_task()
        channel = self.coordinator._orch.channels.get("telegram")
        if (type(chat_id) is not int or type(user_id) is not int
                or type(message_id) is not int or message_id <= 0
                or type(reply_to_message_id) is not int or reply_to_message_id <= 0
                or type(received_at) not in (int, float)
                or not math.isfinite(received_at)
                or channel is None
                or channel._consent_denial_fast.get((chat_id, message_id)) is not dispatch_task):
            return None
        try:
            normalize_reason(reason)
        except ValueError:
            return "invalid_reason"
        with self._lock:
            matches = tuple(prompt for prompt in self._pending.values()
                            if prompt.channel is channel and prompt.chat_id == chat_id
                            and prompt.message_id == reply_to_message_id
                            and prompt.delivered_at is not None)
        if len(matches) != 1:
            return None
        prompt = matches[0]
        if (received_at < prompt.delivered_at or received_at >= prompt.deadline
                or self._matched(prompt.nonce, chat_id=chat_id, user_id=user_id,
                                 message_id=reply_to_message_id) is not prompt):
            return None
        with self._lock:
            if self._pending.get(prompt.nonce) is not prompt or prompt.inflight:
                return None
            prompt.inflight = True
            prompt.denial_task = dispatch_task

        def current() -> bool:
            # Called inside queue's write transaction: do not read queue here.
            return (
                self._pending.get(prompt.nonce) is prompt and prompt.inflight
                and prompt.denial_task is dispatch_task
                and asyncio.current_task() is dispatch_task
                and channel._consent_denial_fast.get((chat_id, message_id)) is dispatch_task
                and channel.on_consent_denial_reply is self._denial_hook
                and self._transport_live(prompt) and self._request_live(prompt)
                and self.coordinator._callback_is_owner(chat_id, user_id) is True
                and chat_id == prompt.chat_id
                and reply_to_message_id == prompt.message_id
                and (prompt.source is None or user_id == prompt.source.user_id)
            )

        result = None
        try:
            actor = make_telegram_consent_actor(
                user_id=user_id, chat_id=chat_id, current=current,
            )
            if actor is None or not current():
                return None
            result = await self.worker.apply_consent_decision(
                prompt.offer.task_id, prompt.offer.revision,
                choice="deny", actor=actor, reason=reason,
            )
            return "accepted" if result is not None else None
        finally:
            self._retire(prompt, result)

    def stop(self, generation: str) -> None:
        with self._lock:
            for task_id, origin in tuple(self._origins.items()):
                if origin.source.generation == generation:
                    self._origins.pop(task_id, None)
            prompts = tuple(prompt for prompt in self._pending.values()
                            if prompt.generation == generation)
        for prompt in prompts:
            self._retire(prompt)
