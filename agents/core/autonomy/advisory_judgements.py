"""Bounded, optional advisory work shared by action cards and task decisions.

Storage adapters own pending-state checks and compare-and-store. This runner
delegates storage and promotion effects; only the task adapter's explicit smart
terminal path may apply a sealed one-operation approval. Action cards stay advisory.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
import weakref

logger = logging.getLogger("jarvis.autonomy.advisory_judgements")
JUDGE_MAX_CONCURRENT = 2
JUDGE_MAX_PENDING = 32


class JudgementCapacity:
    """One shared runtime capacity for all adapters bound to the same judge."""
    def __init__(self):
        self._lock = threading.Lock()
        self._work: set[tuple[object, str]] = set()
        self._slots = weakref.WeakKeyDictionary()

    def reserve(self, owner, key: str) -> bool:
        with self._lock:
            if len(self._work) >= JUDGE_MAX_PENDING:
                return False
            self._work.add((owner, key))
            return True

    def release(self, owner, key: str) -> None:
        with self._lock:
            self._work.discard((owner, key))

    def slots_for(self, loop):
        with self._lock:
            slots = self._slots.get(loop)
            if slots is None:
                slots = self._slots[loop] = asyncio.Semaphore(JUDGE_MAX_CONCURRENT)
            return slots


class AdvisoryJudgements:
    """Storage-independent runner; initialize before a persistent adapter loads."""
    def _init_judgements(self):
        self._judge = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._judge_tasks: set = set()
        self._judging: set[str] = set()
        self._judge_pending: set[str] = set()
        self._judge_lock = threading.Lock()
        self._judge_capacity = JudgementCapacity()
        self._skipped_busy = 0
        self._skipped_revoked = 0
        self._audit = None

    def attach_judge(self, judge, *, loop: asyncio.AbstractEventLoop | None = None,
                     capacity: JudgementCapacity | None = None) -> None:
        """Attach an ``approval_judge.ApprovalJudge``; *loop* serves requests queued from a
        worker thread (a request on a running loop is judged on that loop)."""
        self._judge = judge
        self._loop = loop
        if capacity is not None:
            self._judge_capacity = capacity

    def attach_audit(self, intent_log) -> None:
        """Attach the signed intent log the judged / decided rows go to."""
        self._audit = intent_log

    def judge_status_public(self) -> dict:
        """The judge's state for the HUD: never a key, a base URL only when local."""
        with self._judge_lock:
            judging = sorted(self._judging)
        judge = self._judge
        if judge is None:
            from .approval_judge import JudgeStatus

            status = JudgeStatus(False, "judge_unset")
        else:
            try:
                status = judge.status()
            except Exception:  # noqa: BLE001 — a broken status reads as off, never as a 500
                from .approval_judge import JudgeStatus

                status = JudgeStatus(False, "judge_status_error")
        with self._judge_lock:
            skipped = self._skipped_busy
            revoked = self._skipped_revoked
        return {**status.public(), "judging": judging, "skipped_busy": skipped,
                "skipped_revoked": revoked}

    def _schedule_judge(self, item: dict) -> None:
        judge = self._judge
        if judge is None:
            return
        from .approval_judge import normalise_snapshot

        snapshot = normalise_snapshot(item)   # real text and JSON types, never stored args
        status = judge.status()
        if not judge.wants(snapshot, status):
            return
        # A fresh context: no H681 job selection, no request overrides, no turn variables.
        fresh = contextvars.Context()
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        action_id = snapshot["id"]
        loop = self._loop
        hub_up = loop is not None and not loop.is_closed() and loop.is_running()
        if running is not None and (running is loop or not hub_up):
            if self._mark_judging(action_id):
                self._spawn(running, snapshot, status, fresh)
            return
        if not hub_up:
            return   # an offline CLI / a cold sync caller: no judge, the item stays as it is
        # A worker thread (asyncio.to_thread) or a short-lived loop of its own: the judgement
        # runs on the hub's loop, which outlives the caller.
        if not self._mark_judging(action_id):
            return
        try:
            loop.call_soon_threadsafe(self._spawn, loop, snapshot, status, fresh,
                                      context=contextvars.Context())
        except RuntimeError:   # the loop closed in between
            self._unmark_judging(action_id)

    def _mark_judging(self, action_id: str) -> bool:
        """Claim a judging slot; ``False`` (and the item counted as skipped) when
        :data:`JUDGE_MAX_PENDING` judgements are already in flight or waiting."""
        with self._judge_lock:
            if action_id in self._judging:
                return False
            if not self._judge_capacity.reserve(self, action_id):
                self._skipped_busy += 1
                logger.debug("approval judge busy: %s is not judged", action_id)
                return False
            self._judging.add(action_id)
            self._judge_pending.add(action_id)
            return True

    def _slots_for(self, loop) -> asyncio.Semaphore:
        return self._judge_capacity.slots_for(loop)

    def _unmark_judging(self, action_id: str) -> None:
        with self._judge_lock:
            self._judging.discard(action_id)
            self._judge_capacity.release(self, action_id)
            self._judge_pending.discard(action_id)

    def _spawn(self, loop, snapshot: dict, status, ctx: contextvars.Context) -> None:
        action_id = snapshot["id"]
        try:
            task = loop.create_task(self._judge_one(snapshot, status), context=ctx)
        except Exception:  # noqa: BLE001
            self._unmark_judging(action_id)
            logger.debug("approval judge task not started for %s", action_id, exc_info=True)
            return
        self._judge_tasks.add(task)

        def _done(t, _id=action_id):
            self._judge_tasks.discard(t)
            self._unmark_judging(_id)
        task.add_done_callback(_done)

    async def _judge_one(self, snapshot: dict, status) -> None:
        from .smart_observers import decided_after_store, judgement_scope

        action_id = snapshot["id"]

        async def dispatch():
            # wait_for enters this coroutine in its own task. Re-check here so there is
            # no scheduling yield between the final policy check and score/generate.
            live = self._pending_snapshot(action_id)
            judge = self._judge
            current = judge.status() if judge is not None else None
            if (live is None or current is None or not current.configured
                    or not judge.wants(live, current) or not judge.wants(snapshot, current)):
                with self._judge_lock:
                    self._skipped_revoked += 1
                return None
            from .approval_judge import judgement_request_scope

            def still_current():
                pending = self._pending_snapshot(action_id)
                latest = judge.status()
                return (self._judge is judge and pending is not None and latest.configured
                        and judge.wants(pending, latest) and judge.wants(snapshot, latest))

            with judgement_request_scope(still_current):
                return await judge.score(snapshot, current)

        with judgement_scope(snapshot) as observation:
            try:
                # The timeout bounds the dispatch and one judge call, not the slot wait.
                async with self._slots_for(asyncio.get_running_loop()):
                    annotation = await asyncio.wait_for(dispatch(), timeout=status.timeout)
                if not annotation:
                    return
                stored = self._store_judgement(snapshot, annotation)
                if stored is None:
                    logger.debug("approval judge verdict for %s dropped (decided, cleared or judged)", action_id)
                    return
                decided_after_store(observation, self, snapshot, annotation, stored)
                self._record_judgement(snapshot, stored)
                await self._after_judgement(snapshot, stored)
            except Exception:  # noqa: BLE001 — timeout, backend down, refusal: nothing persisted
                logger.debug("approval judge gave no verdict for %s", action_id, exc_info=True)
            finally:
                self._unmark_judging(action_id)

    def _store_judgement(self, snapshot: dict, annotation: dict):
        return self.annotate(snapshot["id"], annotation)

    def _record_judgement(self, snapshot: dict, annotation: dict) -> None:
        raise NotImplementedError

    async def _after_judgement(self, snapshot: dict, annotation: dict) -> None:
        """Optional adapter effects after its durable compare-and-store succeeds."""
