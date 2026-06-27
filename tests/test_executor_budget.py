"""ORIZONT-24 K3 — per-task wall-time budget at the autonomy TaskExecutor.

A task that overruns its wall-time budget is cancelled at the worker's dispatch point and
returns a clean failed result (OWASP unbounded-consumption). Default-off: with no budget
the path is byte-identical to before.
"""
import asyncio

from agents.core.autonomy.executor import TaskExecutor


class _Task:
    def __init__(self, kind="x", payload=None, title=""):
        self.kind, self.payload, self.title = kind, payload or {}, title


def test_no_budget_runs_normally():
    ex = TaskExecutor()                 # max_wall_seconds defaults to None → unbounded

    async def h(_t):
        return {"status": "ok", "did": "work"}
    ex.register("x", h)
    assert asyncio.run(ex.execute(_Task("x"))) == {"status": "ok", "did": "work"}


def test_fast_task_within_budget_completes():
    ex = TaskExecutor(max_wall_seconds=1.0)

    async def h(_t):
        await asyncio.sleep(0.01)
        return {"status": "ok"}
    ex.register("x", h)
    assert asyncio.run(ex.execute(_Task("x"))) == {"status": "ok"}


def test_overrun_task_is_cancelled_and_reported():
    ex = TaskExecutor(max_wall_seconds=0.05)
    ran = {"finished": False}

    async def h(_t):
        await asyncio.sleep(1.0)        # far exceeds the 0.05s budget
        ran["finished"] = True         # must NOT be reached — the task is cancelled
        return {"status": "ok"}
    ex.register("x", h)
    out = asyncio.run(ex.execute(_Task("x")))
    assert out == {"status": "failed", "reason": "wall_time_budget_exceeded", "budget_seconds": 0.05}
    assert ran["finished"] is False    # handler was cancelled at the budget, not completed


def test_non_dict_result_still_wrapped_under_budget():
    ex = TaskExecutor(max_wall_seconds=1.0)

    async def h(_t):
        return "plain-output"
    ex.register("x", h)
    assert asyncio.run(ex.execute(_Task("x"))) == {"status": "ok", "output": "plain-output"}


def test_coordinator_parses_env_budget(monkeypatch):
    """The coordinator turns JARVIS_TASK_MAX_SECONDS into the executor's budget; a blank or
    non-positive value means unbounded (mirrors the parsing in autonomy_coordinator)."""
    import os

    def parse():
        raw = os.environ.get("JARVIS_TASK_MAX_SECONDS", "").strip()
        try:
            v = float(raw) if raw else None
        except ValueError:
            v = None
        return v if (v is None or v > 0) else None

    monkeypatch.delenv("JARVIS_TASK_MAX_SECONDS", raising=False)
    assert parse() is None
    monkeypatch.setenv("JARVIS_TASK_MAX_SECONDS", "30")
    assert parse() == 30.0
    monkeypatch.setenv("JARVIS_TASK_MAX_SECONDS", "0")
    assert parse() is None
    monkeypatch.setenv("JARVIS_TASK_MAX_SECONDS", "nonsense")
    assert parse() is None
