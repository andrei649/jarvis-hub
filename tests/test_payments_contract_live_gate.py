"""0.45 — live payment gate uses the automation contract template.

The earlier parity test proved a ContractTemplate can reproduce the bespoke
PaymentBroker mandate gate. These tests pin the next step: the live request and
approval paths must actually consult the contract decision, so the reusable
abstraction is no longer inert scaffolding.
"""

from pathlib import Path

import pytest

from agents.core.automation_contracts import ContractDecision
from agents.core.payments import PaymentBroker


class _FakePaymentContract:
    def __init__(self, reason: str | None) -> None:
        self.reason = reason
        self.calls = []

    def evaluate(self, payload=None, **kwargs):
        self.calls.append((payload or {}, kwargs))
        return ContractDecision(
            kind="payment",
            admissible=self.reason is None,
            requires_approval=True,
            reason=self.reason,
            checked=("fake",),
        )


def _broker(tmp_path: Path) -> PaymentBroker:
    return PaymentBroker(path=str(tmp_path / "pay.json"))


def _mandate(broker: PaymentBroker) -> dict:
    return broker.create_mandate(["acme"], per_payment_cap=100, total_cap=150, currency="EUR")


def test_request_payment_obeys_live_contract_decision(tmp_path, monkeypatch):
    import agents.core.payments as payments

    contract = _FakePaymentContract("payee_not_allowed")
    monkeypatch.setattr(payments, "PAYMENT_CONTRACT", contract)

    broker = _broker(tmp_path)
    mandate = _mandate(broker)
    out = broker.request_payment(mandate["id"], "acme", 10, "EUR")

    assert out == {"ok": False, "reason": "payee_not_allowed"}
    assert broker.list_payments() == []
    assert contract.calls
    payload, kwargs = contract.calls[-1]
    assert payload == {
        "mandate": broker._mandates[mandate["id"]],
        "payee": "acme",
        "amount": 10,
        "currency": "EUR",
    }
    assert "now" in kwargs


def test_approve_rechecks_pending_payment_through_live_contract(tmp_path, monkeypatch):
    import agents.core.payments as payments

    broker = _broker(tmp_path)
    mandate = _mandate(broker)
    payment_id = broker.request_payment(mandate["id"], "acme", 10, "EUR")["payment"]["id"]

    contract = _FakePaymentContract("over_total_cap")
    monkeypatch.setattr(payments, "PAYMENT_CONTRACT", contract)

    with pytest.raises(ValueError, match="payment no longer admissible"):
        broker.approve(payment_id)

    rejected = broker.list_payments()[0]
    assert rejected["status"] == "rejected"
    assert rejected["reason"] == "over_total_cap"
    assert contract.calls[-1][0]["amount"] == 10.0
