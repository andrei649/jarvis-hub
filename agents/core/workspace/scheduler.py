"""The in-process scheduler of Nerva Workspace: scheduled reports and housekeeping (spec §9).

One :meth:`WorkspaceScheduler.tick` every 30 s does, in order:

1. starts due scheduled reports (a compare-and-set on ``next_run_at`` claims each one,
   so overlapping ticks never start a report twice);
2. expires pending approvals older than 7 days, and fails ``executing`` approvals
   older than 10 minutes (``interrupted`` — the process died mid-effect);
3. fails report runs ``running`` for over 15 minutes or ``queued`` for over 30
   (``interrupted``), and assistant messages ``pending`` for over 10 minutes;
4. deletes what nobody needs any more: login attempts older than a day, invites
   expired a week ago, sessions revoked or expired a week ago, notifications read 90
   days ago.

Each step runs in its own short transactions and one failing step never stops the
others. The database work runs in a worker thread; only spawning the claimed runs
happens on the event loop. ``tick(now=…)`` takes an explicit clock, which is how the
tests drive it without sleeping. One hub per data root (the hub lock) means one
scheduler per database, so no cross-process coordination is needed beyond the
compare-and-set claims.

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

from agents.core.workspace import approvals, config, db, reports

logger = logging.getLogger("nerva.workspace.scheduler")

DEFAULT_INTERVAL_SECONDS = 30.0
PENDING_MESSAGE_SECONDS = 10 * 60
LOGIN_ATTEMPT_RETENTION_SECONDS = 86400
INVITE_RETENTION_SECONDS = 7 * 86400
SESSION_RETENTION_SECONDS = 7 * 86400
NOTIFICATION_RETENTION_SECONDS = 90 * 86400


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

    def __init__(self, interval_seconds: float = DEFAULT_INTERVAL_SECONDS) -> None:
        self.interval_seconds = interval_seconds
        #: The loop task of each event loop this scheduler was started on (its owning loop).
        self._tasks: dict[asyncio.AbstractEventLoop, asyncio.Task] = {}

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
            summary: dict[str, Any] = {"now": now, "errors": []}
            steps: list[tuple[str, Callable[[sqlite3.Connection, float], Any]]] = [
                ("runs_started", reports.claim_due_reports),
                ("approvals_expired", approvals.expire_due),
                ("approvals_interrupted", approvals.fail_stale_executing),
                ("runs_interrupted", reports.fail_stuck_runs),
                ("messages_interrupted", interrupt_pending_messages),
                ("deleted", housekeeping),
            ]
            for name, step in steps:
                try:
                    summary[name] = step(conn, now)
                except Exception:  # one broken step must not stop the others
                    logger.exception("workspace scheduler step %s failed", name)
                    summary["errors"].append(name)
            return summary
        finally:
            conn.close()

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
        _scheduler = WorkspaceScheduler()
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
