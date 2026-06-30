"""H23.1 — make_budget_ledger factory + opt-in BudgetLedger enforcement in CallBroker.

The ledger primitives (token/wall-time/recursion limits) are covered by
tests/test_kernel_budget.py. This covers the factory (config/env → ledger | None)
and the CallBroker wiring: default (no ledger) is byte-identical; an attached
ledger denies a call that breaches any dimension and accrues usage + restores
depth on a clean call.
"""

import sys
import time
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy.call_broker import CallBroker  # noqa: E402
from agents.core.kernel.binding import make_budget_ledger  # noqa: E402
from agents.core.kernel.budget import BudgetLedger, BudgetLimits  # noqa: E402


class _Task:
    def __init__(self, **payload):
        self.payload = payload


def _task(message="hello"):
    return _Task(provider="twilio", to="+15551234567", message=message)


# ── make_budget_ledger factory ────────────────────────────────────────────────

def test_factory_returns_none_when_unconfigured():
    assert make_budget_ledger(env={}) is None
    assert make_budget_ledger({}, env={}) is None


def test_factory_reads_config_then_env():
    led = make_budget_ledger({"max_tokens": 100, "max_depth": 3}, env={})
    assert led is not None
    assert led.limits.max_tokens == 100 and led.limits.max_depth == 3
    assert led.limits.max_wall_seconds is None

    led2 = make_budget_ledger(env={"JARVIS_BUDGET_MAX_WALL_SECONDS": "2.5"})
    assert led2.limits.max_wall_seconds == 2.5

    # config wins over env
    led3 = make_budget_ledger({"max_tokens": 7}, env={"JARVIS_BUDGET_MAX_TOKENS": "999"})
    assert led3.limits.max_tokens == 7


def test_factory_ignores_unparseable_values():
    # only a bad value present → all dimensions None → factory returns None
    assert make_budget_ledger({"max_tokens": "not-an-int"}, env={}) is None


# ── CallBroker: default path is byte-identical (no ledger) ─────────────────────

@pytest.mark.asyncio
async def test_default_no_ledger_executes_normally():
    out = await CallBroker().execute(_task())
    assert out["status"] == "ok" and out["provider"] == "twilio"


# ── CallBroker: opt-in enforcement ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_token_budget_denies_and_restores_depth():
    led = BudgetLedger(limits=BudgetLimits(max_tokens=10), tokens_used=50)
    out = await CallBroker(ledger=led).execute(_task())
    assert out["status"] == "failed" and out["reason"] == "budget_exceeded"
    assert "token" in out["detail"]
    assert led.depth == 0   # entered then left, even on the deny path


@pytest.mark.asyncio
async def test_recursion_depth_budget_denies():
    led = BudgetLedger(limits=BudgetLimits(max_depth=2), depth=2)
    out = await CallBroker(ledger=led).execute(_task())
    assert out["status"] == "failed" and "recursion depth" in out["detail"]
    assert led.depth == 2   # restored to its pre-call value


@pytest.mark.asyncio
async def test_wall_time_budget_denies():
    led = BudgetLedger(limits=BudgetLimits(max_wall_seconds=1.0), started_at=time.time() - 100)
    out = await CallBroker(ledger=led).execute(_task())
    assert out["status"] == "failed" and "wall-time" in out["detail"]


@pytest.mark.asyncio
async def test_admissible_call_accrues_tokens_and_restores_depth():
    led = BudgetLedger(limits=BudgetLimits(max_tokens=1000))
    out = await CallBroker(ledger=led).execute(_task("hello"))
    assert out["status"] == "ok"
    assert led.tokens_used == len("hello")   # add_tokens(len(message)) on completion
    assert led.depth == 0                    # leave() restored the depth
