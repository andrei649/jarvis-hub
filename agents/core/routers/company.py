"""Company-mode routes — read the work runs, stop one, propose a goal.

Five user-guarded routes from before H462, three of them read-only:

* ``GET /api/company/runs`` — the brief: every run, its honest headline, what is
  waiting on the owner and which runs took unauthorised steps.
* ``GET /api/company/runs/{run_id}`` — one run in full: steps, budget, verdicts.
* ``GET /api/company/waiting`` — every outstanding ask, and how long it has been
  outstanding. Read-only on purpose: this route says what is waiting, it never
  answers it. Deciding happens in the decision inbox, where every other
  privileged act is decided, and reconciling happens on the scheduler's sweep.
* ``POST /api/company/runs/{run_id}/stop`` — stop a run. **Narrowing only.**
* ``POST /api/company/runs/{run_id}/barrier/clear`` — let a parked run go (H464).
  It grants nothing: the run returns to the cadence it was already approved for,
  still inside its budget, and the clear is on the run's event log as the owner's.

Two more write routes (H462), and neither one opens a run:

* ``POST /api/company/goals`` — **propose** a goal (admin-guarded). The text goes
  through ``goal_intake.propose_goal``, the same front door as ``/goal`` and
  ``nerva goal propose``: the ``goal.approve`` card crosses the Action Kernel and
  lands in the decision inbox as an ask. Nothing is opened here.
* ``POST /api/company/runs/{run_id}/subgoals`` — add an acceptance criterion to a
  running goal (``/subgoal``). **Narrowing only**, like stop: it can make the run
  harder to pass, never easier, and it resets nothing.

There is still no route that *starts* a run, and that omission is the point.
Opening a run requires an owner-approved goal, and approval happens in the
decision inbox — the same place every other privileged act is decided. A "start a
run" button here would be a second, weaker approval path for the most powerful
thing in the product; proposing is asking, and the inbox still decides. Stopping
needs no approval, exactly like revoking a permission.

Reads are honest about the flag: with ``JARVIS_COMPANY_MODE`` off the routes still
answer (so the HUD can say *why* it is empty) but report ``enabled: false`` and
never construct a supervisor.
"""

from __future__ import annotations

import asyncio
import threading

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.app_state import get_orch
from agents.core.autonomy.company_report import build_company_brief
from agents.core.autonomy.goal_contract import GoalContractError
from agents.core.autonomy.goal_intake import MAX_TEXT, propose_goal, refusal_text
from agents.core.autonomy.run_barriers import RunBarriers, describe
from agents.core.autonomy.work_runs import FLAG, MAX_SUBGOAL_CHARS, WorkRunError, WorkRunLedger
from agents.core.routers._deps import admin_guard, user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["company"])

_MAX_RUN_ID = 64


class GoalProposalBody(BaseModel):
    """The goal, as ``/goal`` takes it: a headline and optional field lines."""

    text: str = Field(..., min_length=1, max_length=MAX_TEXT)


class SubgoalBody(BaseModel):
    """One acceptance criterion to add to a running goal."""

    text: str = Field(..., min_length=1, max_length=MAX_SUBGOAL_CHARS)

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
        # The ledger's clock, read once: "parked" only while a barrier is in force
        # by the same clock that stamped it (H464 review F2/F7).
        now = ledger.now()
        snapshots = []
        for run in runs:
            try:
                snapshots.append(ledger.snapshot(run.id, step_limit=25))
            except WorkRunError:
                # A run that vanished between the list and the read is not an
                # error worth failing the whole brief for.
                continue
        return build_company_brief(snapshots, company_mode_enabled=_enabled(), now=now)

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


@router.post("/api/company/runs/{run_id}/barrier/clear", dependencies=[Depends(user_guard)])
async def company_run_barrier_clear(run_id: str):
    """Stop waiting: clear a parked run's barrier (H464). Idempotent — with no
    barrier it answers ``cleared: false`` rather than an error. Same guard as stop:
    clearing restores an already-approved, budget-bounded cadence and grants nothing.

    ``cleared`` is what this call did. When it cleared nothing because a newer
    barrier was set in the meantime, ``waiting_on`` says what the run waits on now,
    so a surface never reports "was not waiting on anything" over a parked run. An
    owner's clear also sticks: neither the planner nor the judge may park the run on
    that same wait again."""
    if not _valid(run_id):
        return nocache_json({"ok": False, "reason": "invalid_run_id"}, status_code=400)
    ledger = await _get_ledger()
    try:
        cleared, run = await asyncio.to_thread(RunBarriers(ledger).clear, run_id, by="owner")
    except WorkRunError as exc:
        status = 404 if exc.reason == "unknown_run" else 409
        return nocache_json({"ok": False, "reason": exc.reason}, status_code=status)
    barrier = run.barrier if run.status in {"planning", "working"} else None
    return nocache_json({
        "ok": True, "cleared": bool(cleared), "run": run.as_dict(),
        "waiting_on": describe(barrier) if barrier else None,
    })


def _proposal_status(reason: str) -> int:
    if reason == "company_mode_off":
        return 409
    if reason == "intake_unavailable":
        return 503
    if reason.startswith("kernel_denied:"):
        return 403
    return 400


@router.post("/api/company/goals", dependencies=[Depends(admin_guard)])
async def company_goal_propose(body: GoalProposalBody):
    """Propose a goal for the owner's approval (H462). Opens nothing.

    The card crosses the Action Kernel and waits in the decision inbox; the run
    opens only when the owner accepts it there. Answers the card as the owner will
    read it and the durable task id — never the task payload."""
    orch = get_orch()
    if orch is None:
        return nocache_json({"ok": False, "reason": "orchestrator_unavailable"}, status_code=503)
    try:
        # The card is an interrupt: the intake runs off the loop, and pushes the
        # card on it (captured here, before to_thread).
        result = await asyncio.to_thread(propose_goal, orch, body.text, requested_by="owner:api",
                                         push_loop=asyncio.get_running_loop())
    except GoalContractError as exc:
        return nocache_json(
            {"ok": False, "reason": exc.reason, "detail": refusal_text(exc.reason)},
            status_code=_proposal_status(exc.reason),
        )
    except Exception as exc:
        return nocache_json(
            {"ok": False, "reason": "intake_refused",
             "detail": f"the decision inbox refused the goal card ({exc.__class__.__name__})"},
            status_code=503,
        )
    return nocache_json({
        "ok": True, "task_id": result["task_id"], "title": result["title"],
        "card": result["card"],
    })


@router.post("/api/company/runs/{run_id}/subgoals", dependencies=[Depends(user_guard)])
async def company_run_subgoal(run_id: str, body: SubgoalBody):
    """Add an acceptance criterion to a running goal (H462 ``/subgoal``).

    Narrowing only, so it needs no approval: the run is not reset (its status,
    budget, steps and fingerprint are untouched), and the verifier will not pass it
    until this criterion holds too. Refused once a verdict is written on the run;
    one that arrives while the verifier is still probing is graded too (the ledger
    refuses a pass that misses it, and the verifier grades again)."""
    if not _valid(run_id):
        return nocache_json({"ok": False, "reason": "invalid_run_id"}, status_code=400)
    ledger = await _get_ledger()
    try:
        record = await asyncio.to_thread(ledger.add_subgoal, run_id, body.text, by="owner")
    except WorkRunError as exc:
        status = {"unknown_run": 404, "missing_subgoal": 400,
                  "subgoal_too_long": 400}.get(exc.reason, 409)
        return nocache_json({"ok": False, "reason": exc.reason}, status_code=status)
    subgoals = await asyncio.to_thread(ledger.subgoals, run_id)
    return nocache_json({"ok": True, "subgoal": record, "subgoals": subgoals})
