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
    """JARVIS_TASK_MAX_SECONDS overrides the executor's budget; a blank, zero or
    non-numeric value falls back to the finite default (H288: never unbounded)."""
    from agents.core.autonomy.executor import DEFAULT_TASK_MAX_SECONDS, resolve_task_budget

    def parse():
        return resolve_task_budget(None)

    monkeypatch.delenv("JARVIS_TASK_MAX_SECONDS", raising=False)
    assert parse() == float(DEFAULT_TASK_MAX_SECONDS)
    monkeypatch.setenv("JARVIS_TASK_MAX_SECONDS", "30")
    assert parse() == 30.0
    monkeypatch.setenv("JARVIS_TASK_MAX_SECONDS", "0")
    assert parse() == float(DEFAULT_TASK_MAX_SECONDS)
    monkeypatch.setenv("JARVIS_TASK_MAX_SECONDS", "nonsense")
    assert parse() == float(DEFAULT_TASK_MAX_SECONDS)


def test_coordinator_task_budget_uses_shared_env_float():
    import inspect

    import agents.core.autonomy.executor as executor
    import agents.core.autonomy_coordinator as coordinator

    assert "resolve_task_budget(" in inspect.getsource(coordinator.AutonomyCoordinator.build_executor)
    src = inspect.getsource(executor.resolve_task_budget)
    assert 'env_float("JARVIS_TASK_MAX_SECONDS"' in src
    assert 'os.environ.get("JARVIS_TASK_MAX_SECONDS"' not in src


def test_coordinator_call_config_uses_shared_env_json_object():
    import inspect

    import agents.core.autonomy_coordinator as coordinator

    src = inspect.getsource(coordinator.AutonomyCoordinator.build_executor)
    assert 'env_json_object("JARVIS_CALL_CONFIG"' in src
    assert 'os.environ.get("JARVIS_CALL_CONFIG"' not in src
    assert ".loads(" not in src
