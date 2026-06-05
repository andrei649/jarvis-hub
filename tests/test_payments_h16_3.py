"""H16.3: governed agentic payments — mandate / cap / approval / audit.

No real rails move money; this enforces hard caps, approval-gating (nothing
settles without approval), an absolute cumulative total cap, and audits every
action. Denial is a normal return value with a controlled reason code.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.payments import PaymentBroker, PENDING, APPROVED, SETTLED  # noqa: E402
import agents.web as web  # noqa: E402


class _Audit:
    def __init__(self):
        self.actions = []

    def record(self, **kw):
        self.actions.append(kw.get("action"))


@pytest.fixture
def broker(tmp_path):
    return PaymentBroker(path=str(tmp_path / "p.json"), audit=_Audit())


def _mandate(broker, **kw):
    kw.setdefault("payees", ["acme"])
    kw.setdefault("per_payment_cap", 100)
    kw.setdefault("total_cap", 150)
    return broker.create_mandate(**kw)


# ── mandates ──────────────────────────────────────────────────────

def test_create_mandate_validation(broker):
    with pytest.raises(ValueError):
        broker.create_mandate(payees=[], per_payment_cap=10, total_cap=10)
    with pytest.raises(ValueError):
        broker.create_mandate(payees=["x"], per_payment_cap=0, total_cap=10)


# ── the hard-cap gate (denials are controlled reason codes) ───────

@pytest.mark.parametrize("kwargs,reason", [
    (dict(payee="acme", amount=120), "over_per_payment_cap"),
    (dict(payee="evil", amount=10), "payee_not_allowed"),
    (dict(payee="acme", amount=10, currency="USD"), "currency_mismatch"),
    (dict(payee="acme", amount=0), "invalid_amount"),
])
def test_request_denials(broker, kwargs, reason):
    m = _mandate(broker)
    res = broker.request_payment(m["id"], **kwargs)
    assert res == {"ok": False, "reason": reason}


def test_unknown_mandate_denied(broker):
    assert broker.request_payment("nope", "acme", 10)["reason"] == "unknown_mandate"


def test_expired_mandate_denied(broker):
    m = _mandate(broker, ttl_seconds=3600)
    broker._mandates[m["id"]]["expires_at"] = 1.0   # force into the past
    assert broker.request_payment(m["id"], "acme", 10)["reason"] == "mandate_expired"


# ── lifecycle + cumulative cap ────────────────────────────────────

def test_happy_path_request_approve_settle(broker):
    m = _mandate(broker)
    pay = broker.request_payment(m["id"], "acme", 90)
    assert pay["ok"] and pay["payment"]["status"] == PENDING
    pid = pay["payment"]["id"]
    assert broker.approve(pid)["status"] == APPROVED
    assert broker.settle(pid)["status"] == SETTLED
    assert broker.list_mandates()[0]["spent"] == 90.0
    assert broker.list_mandates()[0]["remaining"] == 60.0


def test_nothing_settles_without_approval(broker):
    m = _mandate(broker)
    pid = broker.request_payment(m["id"], "acme", 10)["payment"]["id"]
    with pytest.raises(ValueError):
        broker.settle(pid)                          # still pending


def test_cumulative_total_cap_is_absolute(broker):
    m = _mandate(broker)                            # total 150
    p1 = broker.request_payment(m["id"], "acme", 90)["payment"]["id"]
    broker.approve(p1); broker.settle(p1)           # spent 90
    # a second 90 would make 180 > 150 → denied at request, never pending
    assert broker.request_payment(m["id"], "acme", 90)["reason"] == "over_total_cap"
    # but a 60 fits exactly
    p2 = broker.request_payment(m["id"], "acme", 60)
    assert p2["ok"]


def test_reject_and_double_decide(broker):
    m = _mandate(broker)
    pid = broker.request_payment(m["id"], "acme", 10)["payment"]["id"]
    assert broker.reject(pid)["status"] == "rejected"
    with pytest.raises(ValueError):
        broker.approve(pid)                         # already rejected


def test_audit_records_every_action(broker):
    m = _mandate(broker)
    pid = broker.request_payment(m["id"], "acme", 10)["payment"]["id"]
    broker.approve(pid); broker.settle(pid)
    assert {"create_mandate", "request_payment", "approve_payment", "settle_payment"} <= set(broker._audit.actions)


# ── endpoints ─────────────────────────────────────────────────────

def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "_payment_broker", PaymentBroker(path=str(tmp_path / "p.json"), audit=_Audit()))
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm")
    return TestClient(web.app), {"X-Admin-Token": "adm"}


def test_endpoints_full_flow(monkeypatch, tmp_path):
    client, hdr = _client(monkeypatch, tmp_path)
    assert client.get("/api/payments/mandates").status_code == 401     # admin-guarded
    m = client.post("/api/payments/mandates",
                    json={"payees": ["acme"], "per_payment_cap": 100, "total_cap": 150}, headers=hdr).json()
    # over-cap request → 400 + reason
    denied = client.post("/api/payments/request",
                         json={"mandate_id": m["id"], "payee": "acme", "amount": 999}, headers=hdr)
    assert denied.status_code == 400 and denied.json()["reason"] == "over_per_payment_cap"
    # admissible → pending → approve → settle
    pid = client.post("/api/payments/request",
                      json={"mandate_id": m["id"], "payee": "acme", "amount": 50}, headers=hdr).json()["id"]
    assert client.post(f"/api/payments/{pid}/approve", headers=hdr).json()["status"] == "approved"
    assert client.post(f"/api/payments/{pid}/settle", headers=hdr).json()["status"] == "settled"
    assert client.get("/api/payments/mandates", headers=hdr).json()["mandates"][0]["spent"] == 50.0
