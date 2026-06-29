"""0.45 — reusable high-risk-automation contract templates.

Covers the pure decision layer in ``agents/core/automation_contracts.py``:
the constraint factories, ``ContractTemplate.evaluate`` (declared-order
short-circuit, ``requires_approval``, the audit hook, fail-closed on a
crashing constraint), and ``ContractRegistry`` (register/get/kinds, duplicate
guard, unknown-kind fail-closed). A "payment" template reproduces the
``payments.py`` mandate policy end-to-end to prove the abstraction generalizes
the existing hand-rolled gate.
"""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.automation_contracts import (  # noqa: E402
    Constraint,
    ContractDecision,
    ContractRegistry,
    ContractTemplate,
    at_least,
    at_most,
    cumulative_at_most,
    equals,
    field_present,
    not_expired,
    one_of,
    positive,
    predicate,
)

# ── individual constraint factories ──────────────────────────────────────────

def _run(c: Constraint, view, now=0.0):
    return c.evaluate(view, now)


def test_field_present():
    c = field_present("a", "b")
    assert _run(c, {"a": 1, "b": 2}) is None
    assert _run(c, {"a": 1}) == "missing_field:b"
    assert _run(c, {"a": 1, "b": ""}) == "missing_field:b"
    assert _run(c, {"a": 1, "b": None}) == "missing_field:b"


def test_positive_rejects_bool_nan_and_non_positive():
    c = positive("amount")
    assert _run(c, {"amount": 5}) is None
    assert _run(c, {"amount": 0}) == "non_positive:amount"
    assert _run(c, {"amount": -1}) == "non_positive:amount"
    assert _run(c, {"amount": True}) == "invalid_number:amount"   # bool is not a number here
    assert _run(c, {"amount": "5"}) == "invalid_number:amount"
    assert _run(c, {"amount": float("nan")}) == "non_positive:amount"


def test_at_most_constant_and_callable_limit():
    assert _run(at_most("amount", 100), {"amount": 100}) is None
    assert _run(at_most("amount", 100), {"amount": 101}) == "over_max:amount"
    # callable limit reads a runtime value from the merged view
    cap = at_most("amount", lambda v: v["cap"])
    assert _run(cap, {"amount": 50, "cap": 50}) is None
    assert _run(cap, {"amount": 51, "cap": 50}) == "over_max:amount"
    assert _run(at_most("amount", 1), {"amount": "x"}) == "invalid_number:amount"


def test_at_least():
    assert _run(at_least("n", 3), {"n": 3}) is None
    assert _run(at_least("n", 3), {"n": 2}) == "under_min:n"


def test_one_of_constant_and_callable():
    assert _run(one_of("payee", {"acme", "globex"}), {"payee": "acme"}) is None
    assert _run(one_of("payee", {"acme"}), {"payee": "evil"}) == "value_not_allowed:payee"
    pool = one_of("payee", lambda v: v["payees"])
    assert _run(pool, {"payee": "x", "payees": ["x", "y"]}) is None
    assert _run(pool, {"payee": "z", "payees": ["x", "y"]}) == "value_not_allowed:payee"


def test_one_of_unhashable_value_denies_safely():
    # a value that can't be membership-tested must deny, not raise
    assert _run(one_of("v", {"a"}), {"v": ["unhashable"]}) == "value_not_allowed:v"


def test_equals_constant_and_callable():
    assert _run(equals("cur", "EUR"), {"cur": "EUR"}) is None
    assert _run(equals("cur", "EUR"), {"cur": "USD"}) == "mismatch:cur"
    same = equals("cur", lambda v: v["mandate_cur"])
    assert _run(same, {"cur": "EUR", "mandate_cur": "EUR"}) is None
    assert _run(same, {"cur": "USD", "mandate_cur": "EUR"}) == "mismatch:cur"


def test_not_expired():
    c = not_expired("expires_at")
    assert _run(c, {"expires_at": None}) is None      # open-ended: passes
    assert _run(c, {}) is None                         # absent: passes
    assert _run(c, {"expires_at": 100}, now=50) is None
    assert _run(c, {"expires_at": 100}, now=150) == "expired"
    assert _run(c, {"expires_at": "soon"}) == "invalid_expiry:expires_at"


def test_cumulative_at_most():
    c = cumulative_at_most("amount", 150, spent_field="spent")
    assert _run(c, {"amount": 50, "spent": 100}) is None        # 150 == cap ok
    assert _run(c, {"amount": 51, "spent": 100}) == "over_total"
    assert _run(c, {"amount": 50}) is None                       # missing spent → 0
    # callable total reads a runtime cap
    c2 = cumulative_at_most("amount", lambda v: v["total_cap"], spent_field="spent")
    assert _run(c2, {"amount": 10, "spent": 5, "total_cap": 20}) is None
    assert _run(c2, {"amount": 16, "spent": 5, "total_cap": 20}) == "over_total"


def test_predicate_escape_hatch():
    c = predicate("even", lambda v, now: v["n"] % 2 == 0, reason="odd")
    assert _run(c, {"n": 4}) is None
    assert _run(c, {"n": 3}) == "odd"


def test_constraint_is_fail_closed_on_crash():
    boom = Constraint(name="boom", check=lambda v, now: 1 / 0)
    assert _run(boom, {}) == "constraint_error:boom"


# ── ContractTemplate.evaluate ─────────────────────────────────────────────────

def test_template_admissible_records_checked_constraints():
    tpl = ContractTemplate(kind="t", constraints=(positive("amount"), at_most("amount", 10)))
    d = tpl.evaluate({"amount": 5})
    assert isinstance(d, ContractDecision)
    assert d.admissible is True
    assert d.reason is None
    assert d.requires_approval is True        # high-risk default
    assert d.checked == ("positive(amount)", "at_most(amount)")


def test_template_short_circuits_on_first_violation_in_order():
    tpl = ContractTemplate(kind="t", constraints=(positive("amount"), at_most("amount", 10)))
    d = tpl.evaluate({"amount": -3})
    assert d.admissible is False
    assert d.reason == "non_positive:amount"
    # short-circuit: the second constraint is never evaluated
    assert d.checked == ("positive(amount)",)


def test_template_requires_approval_override():
    tpl = ContractTemplate(kind="t", constraints=(), requires_approval=False)
    d = tpl.evaluate({})
    assert d.admissible is True
    assert d.requires_approval is False


def test_template_payload_wins_over_context():
    tpl = ContractTemplate(kind="t", constraints=(equals("env", "prod"),))
    # context says staging, payload overrides to prod → admissible
    assert tpl.evaluate({"env": "prod"}, context={"env": "staging"}).admissible is True
    # context-only value is visible to constraints
    assert tpl.evaluate({}, context={"env": "prod"}).admissible is True


def test_template_now_is_injectable_and_deterministic():
    tpl = ContractTemplate(kind="t", constraints=(not_expired("expires_at"),))
    assert tpl.evaluate({"expires_at": 100}, now=50).admissible is True
    assert tpl.evaluate({"expires_at": 100}, now=150).admissible is False


def test_template_audit_hook_called_and_best_effort():
    events = []
    tpl = ContractTemplate(kind="pay", constraints=(positive("amount"),))
    tpl.evaluate({"amount": 5}, audit=lambda ev, detail: events.append((ev, detail)))
    assert events and events[0][0] == "contract.evaluate"
    assert events[0][1]["admissible"] is True and events[0][1]["kind"] == "pay"

    # a crashing audit sink must never break evaluation
    def _bad(ev, detail):
        raise RuntimeError("sink down")

    d = tpl.evaluate({"amount": 5}, audit=_bad)
    assert d.admissible is True


def test_decision_as_dict_round_trips():
    d = ContractDecision(kind="k", admissible=False, requires_approval=True,
                         reason="r", checked=("a", "b"))
    assert d.as_dict() == {
        "kind": "k", "admissible": False, "requires_approval": True,
        "reason": "r", "checked": ["a", "b"],
    }


# ── ContractRegistry ──────────────────────────────────────────────────────────

def test_registry_register_get_kinds():
    reg = ContractRegistry()
    reg.register(ContractTemplate(kind="a")).register(ContractTemplate(kind="b"))
    assert reg.kinds() == ["a", "b"]
    assert reg.get("a").kind == "a"
    assert reg.get("missing") is None


def test_registry_duplicate_guard_and_replace():
    reg = ContractRegistry()
    reg.register(ContractTemplate(kind="a", description="v1"))
    with pytest.raises(ValueError):
        reg.register(ContractTemplate(kind="a", description="v2"))
    reg.register(ContractTemplate(kind="a", description="v2"), replace=True)
    assert reg.get("a").description == "v2"


def test_registry_rejects_empty_kind():
    reg = ContractRegistry()
    with pytest.raises(ValueError):
        reg.register(ContractTemplate(kind=""))


def test_registry_unknown_kind_fails_closed():
    reg = ContractRegistry()
    d = reg.evaluate("nope", {"x": 1})
    assert d.admissible is False
    assert d.reason == "unknown_contract"
    assert d.requires_approval is True          # fail-closed → still needs a human


def test_registry_evaluate_delegates_to_template():
    reg = ContractRegistry()
    reg.register(ContractTemplate(kind="t", constraints=(at_most("n", 5),)))
    assert reg.evaluate("t", {"n": 5}).admissible is True
    assert reg.evaluate("t", {"n": 6}).reason == "over_max:n"


# ── the payment policy, expressed as a reusable template (the whole point) ─────

def _payment_template() -> ContractTemplate:
    """Reproduce payments.py's mandate gate purely as declared constraints."""
    return ContractTemplate(
        kind="payment",
        constraints=(
            field_present("payee", "amount", "currency"),
            positive("amount"),
            equals("currency", lambda v: v["mandate_currency"]),
            one_of("payee", lambda v: v["payees"]),
            not_expired("expires_at"),
            at_most("amount", lambda v: v["per_payment_cap"]),
            cumulative_at_most("amount", lambda v: v["total_cap"], spent_field="spent"),
        ),
    )


def _mandate_ctx(**over):
    ctx = {
        "mandate_currency": "EUR",
        "payees": ["acme", "globex"],
        "expires_at": 1_000,
        "per_payment_cap": 100,
        "total_cap": 150,
        "spent": 0,
    }
    ctx.update(over)
    return ctx


@pytest.mark.parametrize("payload,reason", [
    ({"payee": "acme", "amount": 120, "currency": "EUR"}, "over_max:amount"),
    ({"payee": "evil", "amount": 10, "currency": "EUR"}, "value_not_allowed:payee"),
    ({"payee": "acme", "amount": 10, "currency": "USD"}, "mismatch:currency"),
    ({"payee": "acme", "amount": 0, "currency": "EUR"}, "non_positive:amount"),
    ({"payee": "acme", "currency": "EUR"}, "missing_field:amount"),
])
def test_payment_template_denials(payload, reason):
    tpl = _payment_template()
    d = tpl.evaluate(payload, context=_mandate_ctx(), now=500)
    assert d.admissible is False
    assert d.reason == reason


def test_payment_template_expiry_and_total_cap():
    tpl = _payment_template()
    base = {"payee": "acme", "amount": 50, "currency": "EUR"}
    # expired mandate
    assert tpl.evaluate(base, context=_mandate_ctx(), now=2_000).reason == "expired"
    # cumulative over the total cap (spent 120 + 50 > 150)
    assert tpl.evaluate(base, context=_mandate_ctx(spent=120), now=500).reason == "over_total"


def test_payment_template_happy_path_admissible_but_needs_approval():
    tpl = _payment_template()
    d = tpl.evaluate({"payee": "acme", "amount": 50, "currency": "EUR"},
                     context=_mandate_ctx(), now=500)
    assert d.admissible is True
    assert d.requires_approval is True        # never auto-acts; routes to approval
    assert d.reason is None
