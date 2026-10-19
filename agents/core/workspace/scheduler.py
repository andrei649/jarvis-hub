"""The in-process scheduler of Nerva Workspace: scheduled reports and housekeeping (spec §9).

One :meth:`WorkspaceScheduler.tick` every 30 s does, in order:

1. starts due scheduled reports (a compare-and-set on ``next_run_at`` claims each one,
   so overlapping ticks never start a report twice);
2. expires pending approvals older than 7 days, and fails ``executing`` approvals
   older than 10 minutes (``interrupted`` — the process died mid-effect);
3. fails report runs ``running`` for over 15 minutes or ``queued`` for over 30
   (``interrupted``), report deliveries left ``pending`` by a hub that stopped mid-send —
   stored over 15 minutes ago, or before this hub started (``delivery_interrupted``),
   assistant messages ``pending`` for over 10 minutes, and documents left ``processing``
   by an extraction that died — claimed over 10 minutes ago, or before this hub started
   (``interrupted``);
4. deletes what nobody needs any more: login attempts older than a day, invites
   expired a week ago, sessions revoked or expired a week ago, notifications read 90
   days ago.

Each step runs in its own short transactions and one failing step never stops the
others. The database work runs in a worker thread; only spawning the claimed runs
happens on the event loop. ``tick(now=…)`` takes an explicit clock, which is how the
tests drive it without sleeping. One hub per data root (the hub lock) means one
scheduler per database, so no cross-process coordination is needed beyond the
compare-and-set claims.

An audit key that is not the trail's (review OPS2-08). Steps 1–3 for reports and approvals
sign an audit row for every change they make, and no row may be signed with another key
than the trail's (``audit.AuditKeyMismatch``). Each tick therefore asks
:func:`audit.key_check` first: while it is not ``ok`` those steps pause — no run is claimed,
no approval expires or fails, nothing is half-written — and the steps that sign nothing
(pending messages, interrupted documents, housekeeping) go on. The pause is logged once, as
a WARNING, when it begins (and again only if the key's state changes), and its end once, as
an INFO line; the tick summary says ``paused`` and ``audit_key``. Due reports and expired
approvals are caught up by the first tick after the service's key is back. A step that
still meets the key error (a key swapped between the check and the step) pauses the rest
of that tick the same way, without a traceback.

The loop starts with the hub (``start_background``) unless ``NERVA_WORKSPACE_SCHEDULER``
is off, and each tick is a no-op while ``NERVA_WORKSPACE`` itself is off, so enabling the
workspace later needs no restart of the scheduler.

Event loops. A task belongs to the loop that created it, and only that loop may cancel and
await it. The hub runs one loop, but an app lifespan can run more than once in one process
on different loops (a nested ``TestClient``, an embedding host): the scheduler therefore
records the loop of each loop task it starts. ``start()`` on a loop that has no live task
starts one there, even while another loop's task runs; ``stop()`` stops only the task of
the running loop, and ``stop_background()`` with it cancels only that loop's report runs
(``reports.cancel_runs``). A nested lifespan's shutdown never cancels, or awaits, a task of
a foreign loop — which would raise there, or kill the outer lifespan's scheduler.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from agents.core.workspace import approvals, audit, config, db, documents, reports

logger = logging.getLogger("nerva.workspace.scheduler")

DEFAULT_INTERVAL_SECONDS = 30.0
PENDING_MESSAGE_SECONDS = 10 * 60
LOGIN_ATTEMPT_RETENTION_SECONDS = 86400
INVITE_RETENTION_SECONDS = 7 * 86400
SESSION_RETENTION_SECONDS = 7 * 86400
NOTIFICATION_RETENTION_SECONDS = 90 * 86400

#: The steps that sign audit rows: they pause while this process's audit key is not the
#: trail's (OPS2-08); every other step runs as usual.
AUDITED_STEPS = ("runs_started", "approvals_expired", "approvals_interrupted", "runs_interrupted",
                 "deliveries_interrupted")
KEY_OK = "ok"
_KEY_STATES = {
    "mismatch": "the audit key of this process is not the one the audit trail was written with",
    "missing": "this process has no audit key for the audit trail (JARVIS_AUDIT_KEY is unset "
               "and the key file does not exist)",
    "unreadable": "the audit key file of this process cannot be read",
}


def interrupt_pending_messages(conn: sqlite3.Connection, now: float) -> int:
    """Assistant answers still ``pending`` after 10 min (a crash mid-stream) → ``error``."""
    with db.tx(conn):
        cursor = conn.execute(
            "UPDATE messages SET status = 'error', error_code = 'interrupted' "
            "WHERE status = 'pending' AND created_at <= ?", (now - PENDING_MESSAGE_SECONDS,))
    return int(cursor.rowcount)


def housekeeping(conn: sqlite3.Connection, now: float) -> dict[str, int]:
    """Delete rows past their retention; returns how many of each went."""
    statements = {
        "login_attempts": ("DELETE FROM login_attempts WHERE ts <= ?",
                           (now - LOGIN_ATTEMPT_RETENTION_SECONDS,)),
        "invites": ("DELETE FROM invites WHERE expires_at <= ?", (now - INVITE_RETENTION_SECONDS,)),
        "sessions": ("DELETE FROM sessions WHERE (revoked_at IS NOT NULL AND revoked_at <= ?) "
                     "OR expires_at <= ? OR last_seen_at <= ?",
                     (now - SESSION_RETENTION_SECONDS, now - SESSION_RETENTION_SECONDS,
                      now - SESSION_RETENTION_SECONDS - config.session_idle_seconds())),
        "notifications": ("DELETE FROM notifications WHERE read_at IS NOT NULL AND read_at <= ?",
                          (now - NOTIFICATION_RETENTION_SECONDS,)),
    }
    deleted: dict[str, int] = {}
    with db.tx(conn):
        for name, (sql, params) in statements.items():
            deleted[name] = int(conn.execute(sql, params).rowcount)
    return deleted


class WorkspaceScheduler:
    """Runs :meth:`tick` every *interval_seconds* while started, once per event loop."""

    def __init__(self, interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
                 started_at: float | None = None) -> None:
        self.interval_seconds = interval_seconds
        #: When this hub process started (``db.now()``): a document claimed before it can
        #: have no extraction running any more, a delivery stored before it no sender.
        #: ``None``: only the age rules apply.
        self.started_at = started_at
        #: The loop task of each event loop this scheduler was started on (its owning loop).
        self._tasks: dict[asyncio.AbstractEventLoop, asyncio.Task] = {}
        #: :func:`audit.key_check`'s answer at the last tick: the pause is logged on a change.
        self._key_state = KEY_OK

    def _prune(self) -> None:
        """Forget finished tasks and the tasks of closed loops (nothing can stop those)."""
        for loop, task in list(self._tasks.items()):   # a snapshot: loops run in other threads
            if task.done() or loop.is_closed():
                self._tasks.pop(loop, None)

    def _running_loop_task(self) -> asyncio.Task | None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        task = self._tasks.get(loop)
        return task if task is not None and not task.done() else None

    @property
    def running(self) -> bool:
        """Whether a loop task is live — on the running loop when called from one."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return any(not task.done() for task in self._tasks.values())
        return self._running_loop_task() is not None

    @property
    def loops(self) -> list[asyncio.AbstractEventLoop]:
        """The event loops with a live loop task (diagnostics and tests)."""
        return [loop for loop, task in self._tasks.items()
                if not task.done() and not loop.is_closed()]

    async def tick(self, now: float | None = None) -> dict:
        """One pass (the testable unit); returns what each step did.

        Runs claimed by step 1 are spawned on the current event loop.
        """
        if not config.enabled():
            return {"skipped": "workspace_disabled"}
        moment = db.now() if now is None else float(now)
        summary = await asyncio.to_thread(self._sweep, moment)
        for run_id in summary.get("runs_started", []):
            reports.spawn_run(run_id)
        return summary

    def _sweep(self, now: float) -> dict:
        conn = db.connect()
        try:
            summary: dict[str, Any] = {"now": now, "errors": [], "paused": []}
            key_state = self._key_gate(conn)
            summary["audit_key"] = key_state
            steps: list[tuple[str, Callable[[sqlite3.Connection, float], Any]]] = [
                ("runs_started", reports.claim_due_reports),
                ("approvals_expired", approvals.expire_due),
                ("approvals_interrupted", approvals.fail_stale_executing),
                ("runs_interrupted", reports.fail_stuck_runs),
                ("deliveries_interrupted", self._fail_interrupted_deliveries),
                ("messages_interrupted", interrupt_pending_messages),
                ("documents_interrupted", self._fail_interrupted_documents),
                ("deleted", housekeeping),
            ]
            for name, step in steps:
                if name in AUDITED_STEPS and key_state != KEY_OK:
                    summary["paused"].append(name)
                    continue
                try:
                    summary[name] = step(conn, now)
                except audit.AuditKeyError as exc:  # the key changed since the check
                    key_state = self._key_changed(exc.code)
                    summary["audit_key"] = key_state
                    summary["paused"].append(name)
                except Exception:  # one broken step must not stop the others
                    logger.exception("workspace scheduler step %s failed", name)
                    summary["errors"].append(name)
            return summary
        finally:
            conn.close()

    def _key_gate(self, conn: sqlite3.Connection) -> str:
        """:func:`audit.key_check` for this tick, logging the pause when its state changes."""
        try:
            state = audit.key_check(conn)
        except sqlite3.Error:   # an unreadable trail: let the steps meet (and log) it
            state = KEY_OK
        return self._key_changed(state)

    def _key_changed(self, state: str) -> str:
        """Record *state* (``ok`` or not); one log line when it differs from the last tick's."""
        state = {"audit_key_mismatch": "mismatch", "audit_key_missing": "missing"}.get(state, state)
        previous, self._key_state = self._key_state, state
        if state == previous:
            return state
        if state == KEY_OK:
            logger.info("workspace scheduler resumed: the audit key matches the audit trail "
                        "again; scheduled reports and approval expiry catch up from this tick")
        else:
            logger.warning(
                "workspace scheduler paused: %s, so scheduled reports, approval expiry and the "
                "failing of stuck runs and approvals wait — nothing is changed or written for "
                "them until the service's %s / %s are back; check with: %s",
                _KEY_STATES.get(state, f"the audit key is {state}"), audit.ENV_AUDIT_KEY,
                audit.ENV_KEY_DIR, audit.CHECK_COMMAND)
        return state

    def _fail_interrupted_documents(self, conn: sqlite3.Connection, now: float) -> int:
        return documents.fail_interrupted(conn, now, claimed_before=self.started_at)

    def _fail_interrupted_deliveries(self, conn: sqlite3.Connection, now: float) -> int:
        return reports.fail_stuck_deliveries(conn, now, stored_before=self.started_at)

    def start(self) -> None:
        """Start the loop on the running event loop (idempotent per loop).

        A live task of another loop is left alone: that loop owns it and stops it.
        """
        self._prune()
        if self._running_loop_task() is not None:
            return
        loop = asyncio.get_running_loop()
        self._tasks[loop] = loop.create_task(self._loop(), name="workspace-scheduler")

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # the loop outlives any single bad tick
                logger.exception("workspace scheduler tick failed")
            await asyncio.sleep(self.interval_seconds)

    async def stop(self) -> None:
        """Stop the running loop's task and wait for it to end (idempotent).

        Only the running loop's task: cancelling or awaiting a task of another loop is not
        this loop's to do (it would raise, or stop another lifespan's scheduler).
        """
        task = self._tasks.pop(asyncio.get_running_loop(), None)
        self._prune()
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


_scheduler: WorkspaceScheduler | None = None


def start_background() -> None:
    """Start the process-wide scheduler on the running loop (the hub lifespan's startup)."""
    global _scheduler
    if not config.scheduler_enabled():
        logger.info("workspace scheduler disabled (%s is off)", config.ENV_SCHEDULER)
        return
    if _scheduler is None:
        _scheduler = WorkspaceScheduler(started_at=db.now())
    _scheduler.start()


async def stop_background() -> None:
    """Stop the running loop's scheduler and interrupt its report runs (hub shutdown).

    A scheduler still running on another loop (an outer lifespan) keeps running, and the
    process-wide instance is kept for it; it is released once no loop runs it any more.
    """
    global _scheduler
    scheduler = _scheduler
    if scheduler is not None:
        await scheduler.stop()
        if not scheduler.loops and _scheduler is scheduler:
            _scheduler = None
    await reports.cancel_runs()
