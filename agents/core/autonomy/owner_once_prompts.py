"""Transport-bound owner replies; no model or persisted field creates a grant."""

from __future__ import annotations

import asyncio
import copy
import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime

from ..approval_outcomes import ApprovalTurnContext, current_approval_turn
from ..native_human_wait import native_human_wait_window
from ..owner_once_context import OwnerReplySource, current_owner_reply_source
from .inbox import build_owner_once_card, parse_owner_once_callback_data
from .owner_once import OwnerOnceClaim, OwnerOnceOffer, OwnerOnceOwner


@dataclass(eq=False)
class _Prompt:
    offer: OwnerOnceOffer
    source: OwnerReplySource
    turn: ApprovalTurnContext
    check: Callable[[], bool]
    future: asyncio.Future
    request_task: asyncio.Task
    message_id: int | None = None
    active: bool = True


@dataclass(eq=False)
class _Invocation:
    source: OwnerReplySource
    turn: ApprovalTurnContext
    identity: tuple
    check: Callable[[], bool]


class OwnerOncePrompts:
    """One coordinator's bounded, process-local live reply registrations.

    Queue CAS owns durable authority. Registry locks only protect references;
    never hold one while entering the queue or making a transport call.
    """

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.worker = coordinator._orch.autonomy
        self.queue = self.worker.queue
        self._pending: dict[str, _Prompt] = {}
        self._claims: dict[int, tuple[OwnerOnceClaim, _Prompt]] = {}
        self._origins: dict[int, _Invocation] = {}
        self._lock = threading.RLock()
        # Stable registration identities, including across copied contexts.
        self._pending_hook = self.pending
        self._callback_hook = self.callback
        self._stop_hook = self.stop

    def install(self, channel) -> None:
        channel.owner_once_pending = self._pending_hook
        channel.on_owner_once_callback = self._callback_hook
        channel.on_owner_once_stop = self._stop_hook

    def _source_live(self, source, turn) -> bool:
        try:
            channel = source.channel
            orch = self.coordinator._orch
            return (source.live() and turn.live()
                    and orch.autonomy is self.worker and self.worker.queue is self.queue
                    and orch.channels.get('telegram') is channel
                    and channel.owner_once_pending is self._pending_hook
                    and channel.on_owner_once_callback is self._callback_hook
                    and channel.on_owner_once_stop is self._stop_hook
                    and self.coordinator._callback_is_owner(source.chat_id, source.user_id) is True
                    and turn.principal_key == json.dumps(
                        ['telegram', str(source.user_id), str(source.chat_id)], separators=(',', ':')))
        except Exception:
            return False

    def can_reply(self) -> bool:
        source, turn = current_owner_reply_source(), current_approval_turn()
        if source is None or turn is None or not self._source_live(source, turn):
            return False
        with self._lock:
            return len(self._pending) + len(self._claims) < 32

    @staticmethod
    def _identity(task) -> tuple:
        return tuple(copy.deepcopy(getattr(task, name)) for name in (
            'created_at', 'agent', 'kind', 'title', 'payload', 'risk_tier',
            'autonomy_level', 'origin', 'kernel_intake_id',
        ))

    def _origin_live(self, origin: _Invocation) -> bool:
        try:
            return self._source_live(origin.source, origin.turn) and origin.check() is True
        except Exception:
            return False

    def register_invocation(self, task_id: int, *, check) -> bool:
        """Remember a live reply origin before the context-free judge is scheduled.

        This only prevents premature unattended closure. It grants no approval,
        offer, worker claim or dispatch authority.
        """
        if not self.can_reply() or not callable(check):
            return False
        task = self.queue.get(task_id)
        if task is None or task.kind != 'toolrpc.terminal_run':
            return False
        origin = _Invocation(current_owner_reply_source(), current_approval_turn(),
                             self._identity(task), check)
        if not self._origin_live(origin):
            return False
        with self._lock:
            for registered_id, previous in tuple(self._origins.items()):
                if not self._origin_live(previous):
                    self._origins.pop(registered_id, None)
            if len(self._origins) >= 32 or task_id in self._origins:
                return False
            self._origins[task_id] = origin
        return True

    def reply_available(self, task_id: int) -> bool:
        """Check the captured transport even from the judge's fresh Context."""
        with self._lock:
            origin = self._origins.get(task_id)
        if origin is None or not self._origin_live(origin):
            return False
        task = self.queue.get(task_id)
        return task is not None and self._identity(task) == origin.identity

    def release_invocation(self, task_id: int) -> None:
        with self._lock:
            self._origins.pop(task_id, None)

    def _live(self, prompt: _Prompt) -> bool:
        try:
            return (self._source_live(prompt.source, prompt.turn)
                    and datetime.now(UTC) < datetime.fromisoformat(prompt.offer.deadline_at)
                    and prompt.check() is True)
        except Exception:
            return False

    def _request_live(self, prompt: _Prompt) -> bool:
        task, loop = prompt.request_task, prompt.future.get_loop()
        with self._lock:
            registered = prompt.active and self._pending.get(prompt.offer.nonce) is prompt
        return (registered and not task.done() and not task.cancelling()
                and loop.is_running() and not loop.is_closed())

    def _wake(self, prompt: _Prompt, result) -> Future:
        delivered = Future()

        def resolve():
            ok = not prompt.future.done() and self._request_live(prompt)
            if ok:
                prompt.future.set_result(result)
            if not delivered.done():
                delivered.set_result(ok)

        loop = prompt.future.get_loop()
        try:
            if loop.is_closed() or not loop.is_running():
                delivered.set_result(False)
                return delivered
            loop.call_soon_threadsafe(resolve)
        except RuntimeError:
            delivered.set_result(False)
        return delivered

    async def _send(self, prompt: _Prompt, card: dict):
        source = prompt.source
        loop = source.originating_task.get_loop()
        if loop is asyncio.get_running_loop():
            return await source.channel.send_owner_once_card(source.chat_id, card)
        sent = asyncio.run_coroutine_threadsafe(
            source.channel.send_owner_once_card(source.chat_id, card), loop,
        )
        return await asyncio.wrap_future(sent)

    async def request(self, task_id: int, snapshot_sha256: str, *, check,
                      timeout: float = 120) -> OwnerOnceClaim | None:
        """Wait for one exact committed reply, revoking on any interrupted wait."""
        if not self.can_reply():
            return None
        source, turn = current_owner_reply_source(), current_approval_turn()

        def current():
            return self._source_live(source, turn) and check() is True

        offer = self.queue.offer_owner_once(task_id, snapshot_sha256, turn=turn,
                                            live_check=current, timeout=timeout)
        if offer is None:
            return None
        prompt = _Prompt(offer, source, turn, check, asyncio.get_running_loop().create_future(),
                         asyncio.current_task())
        transferred = False
        with self._lock:
            self._pending[offer.nonce] = prompt
        try:
            card = build_owner_once_card(self.queue.get(task_id), offer.nonce)
            remaining = (datetime.fromisoformat(offer.deadline_at) - datetime.now(UTC)).total_seconds()
            if remaining <= 0 or not self._live(prompt):
                return None
            message_id = await asyncio.wait_for(self._send(prompt, card), remaining)
            if (type(message_id) is not int or message_id <= 0 or not self._live(prompt)
                    or not self.queue.mark_owner_once_delivered(
                        offer, chat_id=source.chat_id, user_id=source.user_id,
                        message_id=message_id, generation=source.generation,
                        live_check=lambda: self._live(prompt))):
                return None
            with self._lock:
                prompt.message_id = message_id
            remaining = (datetime.fromisoformat(offer.deadline_at) - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                return None
            # Only the delivered, exact native owner wait pauses execution clocks.
            with native_human_wait_window(
                deadline=time.monotonic() + remaining,
                current=lambda: self._live(prompt) and self._request_live(prompt),
            ):
                result = await asyncio.wait_for(prompt.future, remaining)
            if type(result) is OwnerOnceClaim and self._live(prompt):
                with self._lock:
                    self._claims[task_id] = (result, prompt)
                transferred = True
                return result
            return None
        except asyncio.CancelledError:
            raise
        except Exception:
            # Failed delivery, unavailable store and expiry grant no authority.
            return None
        finally:
            with self._lock:
                prompt.active = False
                if self._pending.get(offer.nonce) is prompt:
                    self._pending.pop(offer.nonce)
            if not transferred:
                self.queue.revoke_owner_once(offer, reason='owner-reply-unavailable')

    def _matched(self, nonce, *, chat_id, user_id, message_id) -> _Prompt | None:
        with self._lock:
            prompt = self._pending.get(nonce) if type(nonce) is str else None
        if (prompt is None or prompt.future.done() or type(chat_id) is not int
                or type(user_id) is not int or type(message_id) is not int
                or chat_id != prompt.source.chat_id or user_id != prompt.source.user_id
                or message_id != prompt.message_id or not self._live(prompt)
                or not self._request_live(prompt)):
            return None
        return prompt

    def pending(self, callback: dict) -> bool:
        try:
            parsed = parse_owner_once_callback_data(callback.get('data'))
            message = callback.get('message') or {}
            return (parsed is not None and self._matched(
                parsed[0], chat_id=(message.get('chat') or {}).get('id'),
                user_id=(callback.get('from') or {}).get('id'),
                message_id=message.get('message_id')) is not None)
        except Exception:
            return False

    async def callback(self, nonce, choice, *, chat_id, user_id, message_id) -> str | None:
        prompt = self._matched(nonce, chat_id=chat_id, user_id=user_id, message_id=message_id)
        if prompt is None or choice not in {'once', 'deny'}:
            return None
        owner = OwnerOnceOwner(prompt.turn.principal_key, 'telegram', chat_id, user_id,
                               message_id, prompt.source.generation)
        def current():
            return self._request_live(prompt) and self._live(prompt)

        try:
            if choice == 'deny':
                if not self.queue.reject_owner_once(prompt.offer, nonce, authenticated_owner=owner,
                                                     live_check=current):
                    return None
                result = None
            else:
                result = self.queue.decide_owner_once(
                    prompt.offer, nonce, choice, authenticated_owner=owner, live_check=current,
                )
                if type(result) is not OwnerOnceClaim:
                    return None
            if (not self._request_live(prompt) or not await asyncio.wait_for(
                    asyncio.wrap_future(self._wake(prompt, result)), timeout=1)):
                self.queue.revoke_owner_once(prompt.offer, reason='owner-waiter-unavailable')
                self._wake(prompt, None)
                return None
            return 'accepted' if choice == 'once' else 'rejected'
        except BaseException:
            self.queue.revoke_owner_once(prompt.offer, reason='owner-reply-interrupted')
            self._wake(prompt, None)
            raise

    def claim_current(self, claim: OwnerOnceClaim) -> bool:
        with self._lock:
            bound = self._claims.get(claim.task_id) if type(claim) is OwnerOnceClaim else None
        return bound is not None and bound[0] is claim and self._live(bound[1])

    def release_claim(self, claim: OwnerOnceClaim, *, completed: bool = False) -> None:
        with self._lock:
            bound = self._claims.get(claim.task_id)
            if bound is not None and bound[0] is claim:
                self._claims.pop(claim.task_id)
            else:
                bound = None
        if bound is not None and not completed:
            self.queue.revoke_owner_once(bound[1].offer, reason='owner-execution-withdrawn')

    def stop(self, generation: str) -> None:
        with self._lock:
            for task_id, origin in tuple(self._origins.items()):
                if origin.source.generation == generation:
                    self._origins.pop(task_id)
            prompts = tuple(self._pending.values()) + tuple(p for _, p in self._claims.values())
            for task_id, (_claim, prompt) in tuple(self._claims.items()):
                if prompt.source.generation == generation:
                    self._claims.pop(task_id)
        for prompt in prompts:
            if prompt.source.generation == generation:
                self.queue.revoke_owner_once(prompt.offer, reason='owner-channel-stopped')
                self._wake(prompt, None)
