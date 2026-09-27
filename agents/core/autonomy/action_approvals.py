"""
action_approvals.py — H10.18 Action-Level Approval (sub-task granularity).

A live queue of pending **tool-call** approvals: an agent can register an action
before executing it, then `await_decision` until a human approves or rejects it
from the HUD — finer-grained than the task-level decision inbox (H6.2). Each item
carries a dry-run preview (H12.5) so the reviewer sees what the call would do.

H277: an optional approval judge (``approval_judge.ApprovalJudge``, attached by the
orchestrator; off unless ``JARVIS_ROLE_APPROVAL_JUDGE_MODEL`` is set) scores a queued item
*after* ``request`` returned — the card is shown at once and annotated with
``item["judge"]`` when the judge answers. The annotation is advisory: ``decide``,
``await_decision`` and every gate ignore it, a failed or late judgement leaves the item
(and the file) exactly as it was, and the first answer is the only one. With an intent log
attached, each judgement and each decision is one signed audit row that names the judge.
At most :data:`JUDGE_MAX_CONCURRENT` judge calls run at once and at most
:data:`JUDGE_MAX_PENDING` are in flight or waiting; past that an item is not judged (no
annotation; ``judge_status_public()["skipped_busy"]`` counts it). An action queued with a
taint mark (on itself, its metadata, a nested argument, or an untrusted turn origin) is
stored with ``tainted: True``; a non-local judge never sees it.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import threading
import time
import uuid
import weakref
from pathlib import Path
from typing import Optional

from ..persistence import JsonStore

logger = logging.getLogger("jarvis.autonomy.action_approvals")

JUDGE_MAX_CONCURRENT = 2     # judge calls generating at once (per event loop)
JUDGE_MAX_PENDING = 32       # judgements in flight + waiting; past this an item is skipped


class ActionApprovalQueue(JsonStore):
    """Pending tool-call approvals. Persists items when given a *path* (A7);
    in-memory (path=None) otherwise. asyncio.Events are runtime-only and are
    re-created lazily for items reloaded from disk."""

    _items: dict[str, dict]
    _events: dict[str, asyncio.Event]

    def __init__(self, path: "str | Path | None" = None) -> None:
        # H277 runtime state — never serialised, set before the load.
        self._judge = None
        self._loop: "asyncio.AbstractEventLoop | None" = None
        self._judge_tasks: set = set()
        self._judging: set[str] = set()
        self._judge_lock = threading.Lock()
        self._judge_slots: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
        self._skipped_busy = 0
        self._audit = None
        super().__init__(path)

    def _serialize(self):
        return self._items

    def _deserialize(self, raw) -> None:
        self._items = raw if isinstance(raw, dict) else {}
        self._events = {}                 # events are not persisted

    # ── request ──────────────────────────────────────────────────────────────

    def request(self, action: dict) -> dict:
        """Register a pending tool-call approval and return the queue item."""
        action = action or {}
        action_id = uuid.uuid4().hex[:12]
        tool = action.get("tool", "")
        args = action.get("args") or {}
        from .approval_judge import action_is_tainted

        tainted = action_is_tainted(action)
        try:
            from .dry_run import preview_task
            preview = preview_task({"kind": tool, "title": action.get("summary", tool),
                                    "payload": args, "risk_tier": action.get("risk_tier", 2)})
        except Exception:
            preview = {}
        item = {
            "id": action_id,
            "tool": tool,
            "args": args,
            "agent": action.get("agent", ""),
            "task_id": action.get("task_id"),
            "summary": action.get("summary") or preview.get("summary", tool),
            "preview": preview,
            "status": "pending",
            "decided_by": None,
            "created_at": time.time(),
            "decided_at": None,
        }
        if tainted:
            item["tainted"] = True      # H277 review F4: a non-local judge never sees it
        with self._lock:
            self._items[action_id] = item
            self._events[action_id] = asyncio.Event()
            self._save()
        try:
            self._schedule_judge(item)
        except Exception:  # noqa: BLE001 — the judge is advisory: it never fails a request
            logger.debug("approval judge not scheduled for %s", action_id, exc_info=True)
        return dict(item)

    # ── decide ───────────────────────────────────────────────────────────────

    def decide(self, action_id: str, approved: bool, by: str = "user") -> Optional[dict]:
        changed = False
        with self._lock:
            item = self._items.get(action_id)
            if item is None:
                return None
            if item["status"] == "pending":
                item["status"] = "approved" if approved else "rejected"
                item["decided_by"] = by
                item["decided_at"] = time.time()
                self._save()
                changed = True
            event = self._events.get(action_id)
            decided = dict(item)
        if event is not None:
            event.set()
        if changed:
            self._audit_row(by, "action_approval.decided", "the owner's decision on a queued tool call",
                            action_id, {"tool": decided.get("tool", ""), "agent": decided.get("agent", ""),
                                        "approved": bool(approved), "by": by,
                                        "judge": (decided.get("judge") or {}).get("judge")})
        return decided

    async def await_decision(self, action_id: str, timeout: Optional[float] = None) -> str:
        """Block until the action is decided; return its final status ('approved'/
        'rejected'), or 'timeout' if it isn't decided in time."""
        with self._lock:
            item = self._items.get(action_id)
            if item is None:
                return "unknown"
            if item["status"] != "pending":
                return item["status"]
            # re-create the event lazily (e.g. for an item reloaded from disk).
            event = self._events.get(action_id)
            if event is None:
                event = self._events[action_id] = asyncio.Event()
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return "timeout"
        # B1: guard against a concurrent clear() between the await and the read.
        with self._lock:
            return self._items.get(action_id, {}).get("status", "unknown")

    # ── queries ──────────────────────────────────────────────────────────────

    def get(self, action_id: str) -> Optional[dict]:
        with self._lock:
            item = self._items.get(action_id)
            return dict(item) if item else None

    def list(self, status: Optional[str] = None) -> list[dict]:
        with self._lock:
            items = [dict(i) for i in self._items.values()]
        if status:
            items = [i for i in items if i["status"] == status]
        items.sort(key=lambda i: i["created_at"], reverse=True)
        return items

    def stats(self) -> dict:
        with self._lock:
            items = list(self._items.values())
        return {
            "total": len(items),
            "pending": sum(1 for i in items if i["status"] == "pending"),
            "approved": sum(1 for i in items if i["status"] == "approved"),
            "rejected": sum(1 for i in items if i["status"] == "rejected"),
        }

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._events.clear()
            self._save()

    # ── H277: the advisory approval judge ────────────────────────────────────

    def attach_judge(self, judge, *, loop: "asyncio.AbstractEventLoop | None" = None) -> None:
        """Attach an ``approval_judge.ApprovalJudge``; *loop* serves requests queued from a
        worker thread (a request on a running loop is judged on that loop)."""
        self._judge = judge
        self._loop = loop

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
        return {**status.public(), "judging": judging, "skipped_busy": skipped}

    def annotate(self, action_id: str, annotation: dict) -> Optional[dict]:
        """Store the first judgement on a still-pending item; ``None`` (and nothing written)
        when the item is gone, already decided, or already judged."""
        with self._lock:
            item = self._items.get(action_id)
            if item is None or item.get("status") != "pending" or "judge" in item:
                return None
            item["judge"] = dict(annotation)
            self._save()
            return dict(annotation)

    def _schedule_judge(self, item: dict) -> None:
        judge = self._judge
        if judge is None:
            return
        snapshot = json.loads(json.dumps(item, default=str))   # never the stored args
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
            if len(self._judging) >= JUDGE_MAX_PENDING:
                self._skipped_busy += 1
                logger.debug("approval judge busy: %s is not judged", action_id)
                return False
            self._judging.add(action_id)
            return True

    def _slots_for(self, loop) -> asyncio.Semaphore:
        with self._judge_lock:
            slots = self._judge_slots.get(loop)
            if slots is None:
                slots = self._judge_slots[loop] = asyncio.Semaphore(JUDGE_MAX_CONCURRENT)
            return slots

    def _unmark_judging(self, action_id: str) -> None:
        with self._judge_lock:
            self._judging.discard(action_id)

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
        from .approval_judge import rationale_sha256

        action_id = snapshot["id"]
        try:
            # the timeout bounds one judge call, not the wait for a slot
            async with self._slots_for(asyncio.get_running_loop()):
                annotation = await asyncio.wait_for(self._judge.score(snapshot, status),
                                                    timeout=status.timeout)
        except Exception:  # noqa: BLE001 — timeout, backend down, refusal: nothing persisted
            logger.debug("approval judge gave no verdict for %s", action_id, exc_info=True)
            return
        finally:
            self._unmark_judging(action_id)
        if not annotation:
            return
        stored = self.annotate(action_id, annotation)
        if stored is None:
            logger.debug("approval judge verdict for %s dropped (decided, cleared or judged)", action_id)
            return
        self._audit_row("approval_judge", "action_approval.judged", "", action_id, {
            "tool": snapshot.get("tool", ""), "agent": snapshot.get("agent", ""),
            "score": stored.get("score"), "flags": list(stored.get("flags") or []),
            "truncated": bool(stored.get("truncated")),
            "judge": stored.get("judge"), "rationale_sha256": rationale_sha256(stored)})

    def _audit_row(self, actor: str, action: str, why: str, action_id: str, metadata: dict) -> None:
        audit = self._audit
        if audit is None:
            return
        if action == "action_approval.judged":
            from .approval_judge import ADVISORY_WHY

            why = ADVISORY_WHY
        try:
            audit.record(actor=str(actor or "user"), action=action, why=why,
                         cause=f"action_approval:{action_id}", metadata=metadata)
        except Exception:  # noqa: BLE001 — the audit is best effort; a decision never fails on it
            logger.warning("action approval audit row failed for %s", action_id, exc_info=True)
