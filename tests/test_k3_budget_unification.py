"""M1.1 / K3 budget unification.

The kernel BudgetLedger is the one place that can now report named budget
dimensions while keeping legacy public APIs intact.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy.executor import TaskExecutor  # noqa: E402
from agents.core.autonomy.missions import MissionStore  # noqa: E402
from agents.core.autonomy.policy import ACT  # noqa: E402
from agents.core.autonomy.worker import InterruptBudget  # noqa: E402
from agents.core.kernel import Action, BudgetLedger, Verdict, authorize  # noqa: E402
from agents.core.kernel.binding import make_action_kernel  # noqa: E402
from agents.core.payments import PaymentBroker  # noqa: E402


class _GrantPolicy:
    def decide(self, action):
        return SimpleNamespace(tier=0, outcome=ACT, reason="ok")


def test_named_dimension_over_budget_denies_at_kernel():
    ledger = BudgetLedger()
    ledger.register_dimension("interrupts/day", limit=2)
    ledger.add_dimension_usage("interrupts/day", 3)

    decision = authorize(Action(kind="notify.push"), policy=_GrantPolicy(), budget_ledger=ledger)

    assert decision.verdict is Verdict.DENY
    assert "interrupts/day" in decision.reason


def test_interrupt_budget_is_ledger_view_with_same_public_api():
    ledger = BudgetLedger()
    budget = InterruptBudget(per_day=2, ledger=ledger)

    assert budget.remaining() == 2
    assert budget.consume()
    assert budget.consume()
    assert not budget.consume()
    assert budget.remaining() == 0

    status = ledger.dimension_status("interrupts/day")
    assert status["used"] == 2
    assert status["limit"] == 2
    assert status["remaining"] == 0

    # The old rollover behavior still resets the daily count.
    import datetime
    budget._day = datetime.date(2000, 1, 1)
    assert budget.remaining() == 2
    assert ledger.dimension_status("interrupts/day")["used"] == 0


def test_payment_caps_are_observed_without_replacing_payment_denials(tmp_path):
    ledger = BudgetLedger()
    broker = PaymentBroker(path=str(tmp_path / "payments.json"), ledger=ledger)
    mandate = broker.create_mandate(["acme"], per_payment_cap=50, total_cap=100, currency="EUR")

    denied = broker.request_payment(mandate["id"], "acme", 75)
    assert denied == {"ok": False, "reason": "over_per_payment_cap"}

    ok = broker.request_payment(mandate["id"], "acme", 10)
    assert ok["ok"] is True
    status = ledger.dimension_status("money.total")
    assert status["used"] == 0
    assert status["limit"] == 100
    assert status["remaining"] == 100

    broker.approve(ok["payment"]["id"])
    broker.settle(ok["payment"]["id"])
    status = ledger.dimension_status("money.total")
    assert status["used"] == 10
    assert status["remaining"] == 90


def test_mission_step_budget_is_observed_dimension(tmp_path):
    ledger = BudgetLedger()
    store = MissionStore(
        db_path=str(tmp_path / "missions.db"),
        artifact_root=str(tmp_path / "artifacts"),
        ledger=ledger,
    ).initialize()
    try:
        mission = store.create("Ship it", plan=["one", "two"], max_steps=5)
        store.start(mission.id)
        store.finish_step(mission.id, 0)

        status = ledger.dimension_status("mission.steps")
        assert status["used"] == 1
        assert status["limit"] == 5
        assert status["remaining"] == 4
        assert status["metadata"]["mission_id"] == mission.id
    finally:
        store.close()


def test_task_executor_reports_handler_tokens_used_to_ledger():
    ledger = BudgetLedger()

    async def handler(_task):
        return {"status": "ok", "tokens_used": 17}

    executor = TaskExecutor(fallback=handler, budget_ledger=ledger)
    out = asyncio.run(executor.execute(SimpleNamespace(kind="x")))

    assert out == {"status": "ok", "tokens_used": 17}
    assert ledger.tokens_used == 17


def test_action_kernel_binding_can_carry_budget_ledger():
    ledger = BudgetLedger()
    ledger.register_dimension("mission.steps", limit=1)
    ledger.add_dimension_usage("mission.steps", 2)

    class _Orch:
        autonomy_policy = _GrantPolicy()
        kill_switch = None
        capabilities = None
        intent_log = None

    kernel = make_action_kernel(_Orch(), budget_ledger=ledger)
    decision = kernel(Action(kind="mission.step"))

    assert decision.verdict is Verdict.DENY
    assert "mission.steps" in decision.reason
