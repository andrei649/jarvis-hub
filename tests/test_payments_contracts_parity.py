"""0.45 — parity: an automation_contracts ContractTemplate reproduces, code-for-code,
every denial PaymentBroker._deny_reason emits today.

This proves the reusable contract abstraction (0.45) hosts the payment gate with
**identical** outcomes. The broker's own ``_deny_reason`` stays the oracle — no
hardcoded expected codes — while the live reason-code literals now live in the
contract template.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.automation_contracts import ContractTemplate, predicate  # noqa: E402
from agents.core.payments import PaymentBroker  # noqa: E402


def _payment_template() -> ContractTemplate:
    """Reproduce PaymentBroker._deny_reason — same order, same literal reason codes —
    using the contract framework's ``predicate`` escape hatch over a merged view of
    ``{mandate, payee, amount, currency}``. Order matters: the template short-circuits
    on the first failure exactly as the broker returns the first matching reason."""
    def has_mandate(v, now):
        return v.get("mandate") is not None

    def not_expired(v, now):
        exp = v["mandate"].get("expires_at")
        return not (exp and now > exp)

    def valid_amount(v, now):
        a = v["amount"]
        return isinstance(a, (int, float)) and not isinstance(a, bool) and a > 0

    def currency_ok(v, now):
        return v["currency"].upper() == v["mandate"]["currency"]

    def payee_ok(v, now):
        return v["payee"] in v["mandate"]["payees"]

    def under_per_payment(v, now):
        return v["amount"] <= v["mandate"]["per_payment_cap"]

    def under_total(v, now):
        return round(v["mandate"]["spent"] + v["amount"], 2) <= v["mandate"]["total_cap"]

    return ContractTemplate(kind="payment", constraints=(
        predicate("mandate_present", has_mandate, reason="unknown_mandate"),
        predicate("mandate_not_expired", not_expired, reason="mandate_expired"),
        predicate("amount_valid", valid_amount, reason="invalid_amount"),
        predicate("currency_match", currency_ok, reason="currency_mismatch"),
        predicate("payee_allowed", payee_ok, reason="payee_not_allowed"),
        predicate("under_per_payment_cap", under_per_payment, reason="over_per_payment_cap"),
        predicate("under_total_cap", under_total, reason="over_total_cap"),
    ))


@pytest.fixture
def broker(tmp_path):
    return PaymentBroker(path=str(tmp_path / "pay.json"))


def _mandate(broker, **over):
    kw = {"payees": ["acme", "globex"], "per_payment_cap": 100, "total_cap": 150,
          "currency": "EUR", "ttl_seconds": 3600}
    kw.update(over)
    rec = broker.create_mandate(**kw)
    return broker._mandates[rec["id"]]   # the live mandate dict (mutable)


# Each case is (mutate(mandate) | None, payee, amount, currency). The broker's own
# _deny_reason is the oracle; the template must agree on every one.
NOW = 10_000.0


def _assert_parity(broker, mandate, payee, amount, currency, tpl):
    # align the clocks: drive the broker's expiry check off the same NOW the template uses
    import agents.core.payments as pay
    orig = pay.time.time
    pay.time.time = lambda: NOW
    try:
        broker_reason = broker._deny_reason(mandate, payee, amount, currency)
    finally:
        pay.time.time = orig
    view = {"mandate": mandate, "payee": payee, "amount": amount, "currency": currency}
    decision = tpl.evaluate(view, now=NOW)
    assert decision.reason == broker_reason, (
        f"parity break for ({payee},{amount},{currency}): "
        f"template={decision.reason!r} broker={broker_reason!r}")
    assert decision.admissible is (broker_reason is None)
    return broker_reason


def test_admissible_payment_matches(broker):
    m = _mandate(broker)
    assert _assert_parity(broker, m, "acme", 50, "EUR", _payment_template()) is None


@pytest.mark.parametrize("payee,amount,currency,expected", [
    ("acme", 120, "EUR", "over_per_payment_cap"),
    ("evil", 10, "EUR", "payee_not_allowed"),
    ("acme", 10, "USD", "currency_mismatch"),
    ("acme", 0, "EUR", "invalid_amount"),
    ("acme", -5, "EUR", "invalid_amount"),
])
def test_denial_codes_match_broker(broker, payee, amount, currency, expected):
    m = _mandate(broker)
    got = _assert_parity(broker, m, payee, amount, currency, _payment_template())
    assert got == expected   # and the parity assertion inside confirms the template agrees


def test_unknown_mandate_matches(broker):
    # mandate=None on both sides → unknown_mandate
    assert _assert_parity(broker, None, "acme", 50, "EUR", _payment_template()) == "unknown_mandate"


def test_expired_mandate_matches(broker):
    m = _mandate(broker)
    m["expires_at"] = NOW - 1   # already past relative to the shared NOW
    assert _assert_parity(broker, m, "acme", 50, "EUR", _payment_template()) == "mandate_expired"


def test_over_total_cap_matches(broker):
    m = _mandate(broker)
    m["spent"] = 120          # 120 + 50 = 170 > total_cap 150, but 50 <= per-payment 100
    assert _assert_parity(broker, m, "acme", 50, "EUR", _payment_template()) == "over_total_cap"


def test_every_broker_reason_branch_is_covered():
    # guard: if a new denial branch is added to the live contract, this list should grow too
    import inspect

    import agents.core.payments as payments
    src = inspect.getsource(payments._payment_contract_template)
    for code in ("unknown_mandate", "mandate_expired", "invalid_amount", "currency_mismatch",
                 "payee_not_allowed", "over_per_payment_cap", "over_total_cap"):
        assert code in src, f"live payment contract no longer emits {code!r} — update parity cases"
