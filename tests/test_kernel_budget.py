"""K3 — kernel scheduler: per-task token/time/depth ledger + loop circuit breaker.

The OWASP unbounded-consumption guards (folds H23.1). Pure, deterministic (time is
injected). Also checks the kernel front door denies a runaway / over-budget action and
stays inert when no scheduler is supplied (K1 behavior preserved).
"""

from types import SimpleNamespace

from agents.core import kernel
from agents.core.autonomy.policy import ACT
from agents.core.kernel import Action, BudgetLedger, BudgetLimits, LoopDetector, Verdict


class _GrantPolicy:
    def decide(self, action):
        return SimpleNamespace(tier=0, outcome=ACT, reason="ok")


# ── BudgetLedger ────────────────────────────────────────────────────────────
def test_ledger_token_budget():
    led = BudgetLedger(limits=BudgetLimits(max_tokens=100))
    led.add_tokens(60)
    assert led.exceeded() is None
    led.add_tokens(60)
    assert "token budget exceeded" in led.exceeded()


def test_ledger_recursion_depth():
    led = BudgetLedger(limits=BudgetLimits(max_depth=2))
    led.enter()
    led.enter()
    assert led.exceeded() is None
    led.enter()
    assert "recursion depth exceeded" in led.exceeded()
    led.leave()
    assert led.exceeded() is None


def test_ledger_wall_time_injected_clock():
    led = BudgetLedger(limits=BudgetLimits(max_wall_seconds=10))
    led.start(now=100.0)
    assert led.exceeded(now=105.0) is None
    assert "wall-time budget exceeded" in led.exceeded(now=120.0)


def test_ledger_unlimited_by_default():
    led = BudgetLedger()
    led.add_tokens(10_000)
    led.enter()
    assert led.exceeded() is None


# ── LoopDetector ──────────────────────────────────────────────────────────────
def test_loop_breaker_trips_then_resets():
    det = LoopDetector(max_repeats=2, window_seconds=1000)
    assert det.record("x", now=1.0)
    assert det.record("x", now=2.0)
    assert not det.record("x", now=3.0)   # 3rd > max_repeats → trip
    assert det.tripped
    assert not det.record("y", now=4.0)   # open for everything once tripped
    det.reset()
    assert det.record("y", now=5.0) and not det.tripped


def test_loop_window_evicts_old_events():
    det = LoopDetector(max_repeats=2, window_seconds=10)
    assert det.record("x", now=0.0)
    assert det.record("x", now=1.0)
    assert det.record("x", now=100.0)     # old two outside window → no trip
    assert not det.tripped


# ── kernel front door ───────────────────────────────────────────────────────
def test_authorize_grants_under_budget():
    led = BudgetLedger(limits=BudgetLimits(max_tokens=100))
    led.add_tokens(50)
    d = kernel.authorize(Action(kind="x"), policy=_GrantPolicy(), budget_ledger=led)
    assert d.verdict is Verdict.GRANT


def test_authorize_denies_over_budget():
    led = BudgetLedger(limits=BudgetLimits(max_tokens=100))
    led.add_tokens(250)
    d = kernel.authorize(Action(kind="x"), policy=_GrantPolicy(), budget_ledger=led)
    assert d.verdict is Verdict.DENY and "token budget" in d.reason


def test_authorize_denies_when_loop_tripped():
    det = LoopDetector(max_repeats=2, window_seconds=1000)
    for _ in range(3):
        det.record("x", now=1.0)          # pre-trip
    d = kernel.authorize(Action(kind="x"), policy=_GrantPolicy(), loop_detector=det)
    assert d.verdict is Verdict.DENY and "loop" in d.reason.lower()


def test_authorize_inert_without_scheduler():
    # K1 brokers pass neither ledger nor detector → unchanged grant path.
    d = kernel.authorize(Action(kind="x"), policy=_GrantPolicy())
    assert d.verdict is Verdict.GRANT
