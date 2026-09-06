"""Company-mode routes — read the work runs, stop one.

Four user-guarded routes, three of them read-only:

* ``GET /api/company/runs`` — the brief: every run, its honest headline, what is
  waiting on the owner and which runs took unauthorised steps.
* ``GET /api/company/runs/{run_id}`` — one run in full: steps, budget, verdicts.
* ``GET /api/company/waiting`` — every outstanding ask, and how long it has been
  outstanding. Read-only on purpose: this route says what is waiting, it never
  answers it. Deciding happens in the decision inbox, where every other
  privileged act is decided, and reconciling happens on the scheduler's sweep.
* ``POST /api/company/runs/{run_id}/stop`` — stop a run. **Narrowing only.**

There is no route that *starts* a run, and that omission is the point. Opening a
run requires an owner-approved `GoalSpec`, and approval happens in the decision
inbox — the same place every other privileged act is decided. A "start a run"
button here would be a second, weaker approval path for the most powerful thing
in the product. Stopping needs no approval, exactly like revoking a permission.

Reads are honest about the flag: with ``JARVIS_COMPANY_MODE`` off the routes still
answer (so the HUD can say *why* it is empty) but report ``enabled: false`` and
never construct a supervisor.
"""

from __future__ import annotations

import asyncio
import threading

from fastapi import APIRouter, Depends

from agents.core.app_state import get_orch
from agents.core.autonomy.company_report import build_company_brief
from agents.core.autonomy.work_runs import FLAG, WorkRunError, WorkRunLedger
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["company"])

_MAX_RUN_ID = 64

_default: WorkRunLedger | None = None
_build_lock = threading.Lock()


def _enabled() -> bool:
    from agents.core.env_config import env_flag

    return env_flag(FLAG)


def _build_default() -> WorkRunLedger:
    global _default
    with _build_lock:
        if _default is None:
            _default = WorkRunLedger()
        return _default


async def _get_ledger() -> WorkRunLedger:
    """The orchestrator-bound ledger when one is attached, else a process-wide
    default at ``data_path('work_runs.db')`` (built off the loop, once)."""
    orch = get_orch()
    bound = getattr(orch, "work_runs", None) if orch is not None else None
    if isinstance(bound, WorkRunLedger):
        return bound
    if _default is not None:
        return _default
    return await asyncio.to_thread(_build_default)


def _valid(run_id: str) -> bool:
    return bool(run_id) and len(run_id) <= _MAX_RUN_ID


@router.get("/api/company/runs", dependencies=[Depends(user_guard)])
async def company_runs(active_only: bool = False, limit: int = 50):
    """Every run, projected through the brief builder — no task payloads."""
    ledger = await _get_ledger()

    def _read() -> dict:
        runs = ledger.list_runs(active_only=active_only, limit=limit)
        snapshots = []
        for run in runs:
            try:
                snapshots.append(ledger.snapshot(run.id, step_limit=25))
            except WorkRunError:
                # A run that vanished between the list and the read is not an
                # error worth failing the whole brief for.
                continue
        return build_company_brief(snapshots, company_mode_enabled=_enabled())

    return nocache_json(await asyncio.to_thread(_read))


@router.get("/api/company/runs/{run_id}", dependencies=[Depends(user_guard)])
async def company_run(run_id: str):
    """One run in full: its steps, budget and verdicts."""
    if not _valid(run_id):
        return nocache_json({"ok": False, "reason": "invalid_run_id"}, status_code=400)
    ledger = await _get_ledger()
    try:
        snapshot = await asyncio.to_thread(ledger.snapshot, run_id)
    except WorkRunError as exc:
        status = 404 if exc.reason == "unknown_run" else 409
        return nocache_json({"ok": False, "reason": exc.reason}, status_code=status)
    return nocache_json({"ok": True, "enabled": _enabled(), **snapshot})


@router.get("/api/company/waiting", dependencies=[Depends(user_guard)])
async def company_waiting(limit: int = 50):
    """What every open run is waiting on, and for how long.

    Ledger-only: the durable task ids are reported so the HUD can link to the
    decision cards, but nothing here reads or changes a task. A read route that
    quietly resolved asks would be a second approval path for the most powerful
    thing in the product — the same reason there is no route that starts a run.
    """
    ledger = await _get_ledger()

    def _read() -> dict:
        import time as _time

        now = _time.time()
        waiting = []
        for run in ledger.list_runs(active_only=True, limit=limit):
            for step in ledger.outstanding_asks(run.id):
                waiting.append(
                    {
                        "run_id": run.id,
                        "goal_id": run.goal_id,
                        "title": run.title,
                        "step_seq": step.seq,
                        "kind": step.kind,
                        "summary": step.summary,
                        "task_id": step.task_id,
                        "asked_at": step.at,
                        "waiting_seconds": max(0.0, now - float(step.at or now)),
                        # A queued step with no durable task can never be answered
                        # by a decision; flagging it here is how it stops being
                        # invisible until the sweep records it as lost.
                        "answerable": bool(step.task_id),
                    }
                )
        waiting.sort(key=lambda item: item["waiting_seconds"], reverse=True)
        return {
            "ok": True,
            "enabled": _enabled(),
            "waiting": waiting,
            "count": len(waiting),
            "oldest_seconds": waiting[0]["waiting_seconds"] if waiting else 0.0,
        }

    return nocache_json(await asyncio.to_thread(_read))


@router.post("/api/company/runs/{run_id}/stop", dependencies=[Depends(user_guard)])
async def company_run_stop(run_id: str):
    """Stop a run. Narrowing only, so it needs no approval — the same shape as
    revoking a permission. A run that is already stopping settles to stopped."""
    if not _valid(run_id):
        return nocache_json({"ok": False, "reason": "invalid_run_id"}, status_code=400)
    ledger = await _get_ledger()
    try:
        run = await asyncio.to_thread(ledger.request_stop, run_id, reason="owner")
    except WorkRunError as exc:
        status = 404 if exc.reason == "unknown_run" else 409
        return nocache_json({"ok": False, "reason": exc.reason}, status_code=status)
    return nocache_json({"ok": True, "run": run.as_dict()})
