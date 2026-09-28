"""H464d — a re-mint that raises stops the run; a dotted scope kind admits its children.

Item 2. The read-back re-mints the approved goal from its approval task on every
tick (``company_runtime._read_back``). It caught only ``GoalContractError``, but an
approval task edited so that ``Budget(...)`` no longer validates (``max_steps=0``)
raises ``WorkRunError``: every sweep then answered ``tick_failed`` and the run sat
``planning`` forever. The task WAS read, so the same failure comes back on every
sweep — anything that raises while re-minting or binding it is provably "not
bound", and the run stops with a public code on its record, never the exception's
text. A read that raises is still only a hold.

Item 7a. ``task_kind_in_scope`` admitted a task kind under a scope kind only by its
first dotted segment, so a ``file.write`` scope refused ``file.write.append``. A
kind is in scope when it equals a scope kind or starts with ``scope_kind + "."``.
The card, the planner clamp and the judge must agree on every kind: step kinds are
matched exactly in all three, task kinds by the dotted rule in both places that
check them (the judge sees only step kinds).

Hermetic, over the H464c fixtures: a real task queue and ledger under tmp_path on a
hand-driven clock, a spy for the governed intake.
"""

from __future__ import annotations

import sqlite3

import pytest

from agents.core.autonomy import goal_contract
from agents.core.autonomy.company_planner import ChecklistPlanner, PlanStep
from agents.core.autonomy.company_runtime import build_company_runtime
from agents.core.autonomy.goal_contract import GoalContractError, task_kind_in_scope
from agents.core.autonomy.work_judge import GoalTerms
from agents.core.autonomy.work_runs import WorkRunError
from tests.test_h464c_company_run_binding import (  # noqa: F401  (world is a fixture)
    _ROW,
    _draft,
    _finish,
    _goal_task,
    _open,
    _RealOrch,
    world,
)

pytestmark = pytest.mark.asyncio

_STOPPED = "plan not bound to its approval: "


def _approved_run(world, plan=(_ROW,)):
    tid = _goal_task(world.q, _draft(plan=list(plan)))
    run = _open(world, tid)
    _finish(world.q, tid)
    return tid, run


def _edit_budget(world, tid, **fields):
    payload = dict(world.q.get(tid).payload)
    payload["budget"] = {**payload["budget"], **fields}
    world.q.update_payload(tid, payload)       # the task is DONE; the queue API allows it


# ── item 2: a re-mint that raises stops the run ────────────────────────────────

@pytest.mark.parametrize("fields, code", [
    ({"max_steps": 0}, "invalid_max_steps"),
    ({"max_seconds": -1.0}, "invalid_max_seconds"),
    ({"max_interrupts": -1}, "invalid_max_interrupts"),
])
async def test_an_approval_task_whose_budget_no_longer_validates_stops_the_run(
    world, fields, code
):
    """``Budget(...)`` raises ``WorkRunError``, not ``GoalContractError``: the tick used
    to raise on every sweep (``tick_failed``) and the run stayed ``planning``."""
    tid, run = _approved_run(world)
    _edit_budget(world, tid, **fields)
    orch = _RealOrch(world)
    runtime = build_company_runtime(orch)
    result = await runtime.sweep()
    assert result["ok"] is True
    after = world.ledger.get(run.id)
    assert (after.status, after.stop_reason) == ("stopped", _STOPPED + code)
    assert orch.calls == []
    assert world.ledger.steps(run.id) == []
    # Settled once: the next sweep has nothing to tick.
    again = await runtime.sweep()
    assert run.id not in again.get("ticked", [])


@pytest.mark.parametrize("error", [
    RuntimeError("payload says <script>alert(1)</script>"),
    KeyError("secret-api-key-123"),
    # A ledger refusal whose reason is not a bare code is not trusted either.
    WorkRunError("max steps from payload: <b>9</b>"),
], ids=["runtime-error", "key-error", "work-run-error-with-text"])
async def test_any_error_while_re_minting_stops_with_a_public_code(world, monkeypatch, error):
    """Whatever raises while the approval task that was read is re-minted, the stop
    reason is a bounded public code — never text the exception carries."""
    tid, run = _approved_run(world)

    def _raise(task, **_):
        raise error

    monkeypatch.setattr(goal_contract, "approve_from_task", _raise)
    orch = _RealOrch(world)
    await build_company_runtime(orch).sweep()
    after = world.ledger.get(run.id)
    assert (after.status, after.stop_reason) == ("stopped", _STOPPED + "approval_task_unusable")
    assert orch.calls == []


async def test_a_pinned_fingerprint_that_cannot_be_computed_stops_the_run(world, monkeypatch):
    """Binding, too: a goal whose fingerprint raises cannot be proven to be the one the
    run pinned, and the same task raises the same way on every later sweep."""
    _, run = _approved_run(world)

    def _broken(self):
        raise TypeError("cannot fingerprint")

    monkeypatch.setattr(goal_contract.ApprovedGoal, "approved_fingerprint", property(_broken))
    await build_company_runtime(_RealOrch(world)).sweep()
    after = world.ledger.get(run.id)
    assert (after.status, after.stop_reason) == ("stopped", _STOPPED + "approval_task_unusable")


async def test_a_read_that_raises_is_still_only_a_hold(world):
    """The contrast: when the task could not be READ, nothing is known yet — the run
    holds (no step, no stop) and the next sweep reads again."""
    tid, run = _approved_run(world)
    broken = {"on": True}

    def read(task_id):
        if broken["on"] and int(task_id) == tid:
            raise sqlite3.OperationalError("database is locked")
        return world.q.get(task_id)

    orch = _RealOrch(world, read=read)
    await build_company_runtime(orch).sweep()
    held = world.ledger.get(run.id)
    assert (held.status, held.stop_reason) == ("planning", "")
    assert orch.calls == []
    broken["on"] = False
    await build_company_runtime(orch).sweep()       # a fresh scheduler: due at once
    assert len(orch.calls) == 1


# ── item 7a: a dotted scope kind admits its children ───────────────────────────

@pytest.mark.parametrize("task_kind, scope, inside", [
    ("file.write.append", {"file.write"}, True),
    ("file.write", {"file.write"}, True),
    ("file.write.append.v2", {"file.write"}, True),
    ("file.writer", {"file.write"}, False),
    ("file.write_append", {"file.write"}, False),
    ("file", {"file.write"}, False),               # a parent is not inside its child
    ("file.read", {"file.write"}, False),
    ("file.write.append", {"file"}, True),
    ("research.collect", {"research"}, True),
    ("researcher", {"research"}, False),
    ("research", {"research.collect"}, False),
    ("write.brief", {"research", "write"}, True),
    (5, {"file.write"}, False),
    ("anything.at.all", set(), True),               # the explicitly unrestricted goal
])
async def test_a_task_kind_is_in_scope_when_it_is_a_scope_kind_or_under_one(
    task_kind, scope, inside
):
    assert task_kind_in_scope(task_kind, scope) is inside


def _card(row_kind, task_kind, scope):
    """``GoalDraft``'s verdict on one row: "" when the card is accepted."""
    try:
        _draft(plan=[{"kind": row_kind, "summary": "do it",
                      "task": {"agent": "jarvis", "kind": task_kind, "title": "t"}}],
               scope=scope)
    except GoalContractError as exc:
        return exc.reason
    return ""


async def _clamp(row_kind, task_kind, scope):
    """The checklist clamp's verdict on the same row: "" when it is proposed."""
    planner = ChecklistPlanner(
        [PlanStep(kind=row_kind, summary="do it",
                  task={"agent": "jarvis", "kind": task_kind, "title": "t"})],
        scope_kinds=frozenset(scope),
    )
    decision = await planner.decide({"run": {}, "budget": {"steps_left": 5}})
    return "" if decision.action is not None else decision.refusal


async def test_a_dotted_scope_kind_admits_its_children_on_the_card_and_in_the_clamp(world):
    """``file.write`` approved: a row that queues ``file.write.append`` is accepted on
    the card, proposed by the checklist, and queued through the governed intake."""
    assert _card("file.write", "file.write.append", ("file.write",)) == ""
    assert await _clamp("file.write", "file.write.append", ("file.write",)) == ""
    assert _card("file.write", "file.writer", ("file.write",)) == "plan_task_out_of_scope"
    assert await _clamp("file.write", "file.writer", ("file.write",)) == "out_of_scope"

    row = {"kind": "file.write", "summary": "append the notes",
           "task": {"agent": "jarvis", "kind": "file.write.append", "title": "Append",
                    "payload": {}}}
    tid = _goal_task(world.q, _draft(plan=[row], scope=("file.write",)))
    run = _open(world, tid)
    _finish(world.q, tid)
    orch = _RealOrch(world)
    await build_company_runtime(orch).sweep()
    assert [c["kind"] for c in orch.calls] == ["file.write.append"]
    assert world.ledger.get(run.id).status == "blocked"


_SCOPE = ("file.write", "research")
_ROW_KINDS = ("file.write", "file.write.append", "file", "research", "research.collect")
_TASK_KINDS = ("file.write", "file.write.append", "file.writer", "file", "research",
               "research.collect", "write.brief")


async def test_the_card_the_clamp_and_the_judge_agree_on_every_kind():
    """One rule wherever a run can be refused or marked down: a row the card accepts
    is one the clamp proposes and the judge counts in scope, and a row the card
    refuses the clamp refuses too. Step kinds match exactly in all three; task kinds
    by the dotted rule on the card and in the clamp."""
    terms = GoalTerms(goal_id="g", title="t", scope_kinds=frozenset(_SCOPE))
    disagreements = []
    for row_kind in _ROW_KINDS:
        for task_kind in _TASK_KINDS:
            card = _card(row_kind, task_kind, _SCOPE)
            clamp = await _clamp(row_kind, task_kind, _SCOPE)
            step_in = card != "plan_step_out_of_scope"
            if (card == "") != (clamp == ""):
                disagreements.append(f"{row_kind}/{task_kind}: card {card!r}, clamp {clamp!r}")
            if terms.covers(row_kind) != step_in:
                disagreements.append(f"{row_kind}: card step {step_in}, judge {not step_in}")
            if card == "" and task_kind_in_scope(task_kind, _SCOPE) is not True:
                disagreements.append(f"{row_kind}/{task_kind}: accepted out of scope")
    assert not disagreements, "\n".join(disagreements)
    # The dotted rule reached both: a file.write child is accepted end to end.
    assert _card("file.write", "file.write.append", _SCOPE) == ""
