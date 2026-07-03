"""
payments.py — H16.3 Governed agentic payments (mandate / cap / approval / audit).

The GOVERNANCE layer for agent-initiated spending — **not** a payment processor.
There is no rail integration (AP2/ACP/x402): nothing here can actually move
money. What it does is enforce, in one place, the controls that make agentic
payments safe:

* **Mandates with HARD caps.** The owner pre-authorizes a budget: a per-payment
  cap, a total cap, an allowed-payee allowlist, a currency, and an expiry.
* **Approval-gated, always.** Every payment is created ``pending``; only an
  explicit owner approval moves it toward settlement and only an approved
  payment can settle. There is no auto-approve at any amount.
* **Caps are absolute.** A request over the per-payment cap, to a payee outside
  the allowlist, in the wrong currency, against an expired mandate, or that
  would push cumulative spend over the total cap is **denied at creation** — it
  never becomes pending, so it can never settle.
* **Audited.** Each create/approve/reject/settle is recorded to an injected,
  hash-chained, signed log (the H17.4 IntentLog in production) for
  non-repudiation.

Denial is a normal return value (a controlled reason code), not an exception, so
nothing internal leaks to callers. File-backed, pure-Python, offline-testable.
"""

from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

from .persistence import JsonStore

DEFAULT_PATH = data_path("payments.json")

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
SETTLED = "settled"


class PaymentBroker(JsonStore):
    """Mandates + payments with hard-cap, approval and audit enforcement.

    *audit* is any object exposing ``record(actor, action, why, cause="",
    metadata=None)`` (e.g. core.security.anchor.IntentLog); when None, audit is
    skipped (unit tests inject a fake to assert it's called)."""

    # ORIZONT-24 action kind (for the action-auth registry). The payment micro-wave
    # routes an *admissible* request through kernel.authorize (default-off behind
    # JARVIS_ACTION_KERNEL); classified KERNEL in agents/core/kernel/registry.py.
    KIND = "payment"

    def __init__(self, path: str | Path = DEFAULT_PATH, audit=None,
                 *, kernel=None, agent: str = "jarvis", ledger=None) -> None:
        self._audit = audit
        self._kernel = kernel   # ORIZONT-24 K1: bound kernel.authorize (default-off)
        self._agent = agent
        self._ledger = ledger
        super().__init__(path)

    def _serialize(self):
        return {"mandates": self._mandates, "payments": self._payments}

    def _deserialize(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._mandates = raw.get("mandates", {})
        self._payments = raw.get("payments", [])

    def _record(self, action: str, why: str, **meta) -> None:
        if self._audit is not None:
            try:
                self._audit.record(actor="payments", action=action, why=why, metadata=meta)
            except Exception:
                # Audit is best-effort; never let a logging hiccup block the gate.
                pass

    def _sync_mandate_dimension(self, mandate: Optional[dict]) -> None:
        if self._ledger is None or mandate is None:
            return
        setter = getattr(self._ledger, "set_dimension_usage", None)
        if setter is None:
            return
        setter(
            "money.total",
            float(mandate.get("spent") or 0.0),
            limit=float(mandate.get("total_cap") or 0.0),
            unit=str(mandate.get("currency") or ""),
            enforced=False,
            metadata={
                "mandate_id": mandate.get("id"),
                "payees": list(mandate.get("payees") or []),
                "per_payment_cap": mandate.get("per_payment_cap"),
            },
        )

    # ── mandates ─────────────────────────────────────────────────────────────

    def create_mandate(self, payees, per_payment_cap: float, total_cap: float,
                       currency: str = "EUR", ttl_seconds: Optional[float] = None) -> dict:
        allowlist = sorted({str(p).strip() for p in (payees or []) if str(p).strip()})
        if not allowlist:
            raise ValueError("at least one payee is required")
        if per_payment_cap <= 0 or total_cap <= 0:
            raise ValueError("caps must be positive")
        mandate_id = secrets.token_urlsafe(8)
        rec = {
            "id": mandate_id,
            "payees": allowlist,
            "per_payment_cap": float(per_payment_cap),
            "total_cap": float(total_cap),
            "currency": currency.upper(),
            "spent": 0.0,
            "created_at": time.time(),
            "expires_at": (time.time() + ttl_seconds) if ttl_seconds else None,
        }
        self._mandates[mandate_id] = rec
        with self._lock:
            self._save()
        self._sync_mandate_dimension(rec)
        self._record("create_mandate", f"budget {total_cap} {rec['currency']} for {len(allowlist)} payee(s)",
                     mandate_id=mandate_id)
        return dict(rec)

    def list_mandates(self) -> list[dict]:
        out = []
        for m in self._mandates.values():
            d = dict(m)
            d["remaining"] = round(m["total_cap"] - m["spent"], 2)
            out.append(d)
        return out

    def _mandate_expired(self, m: dict) -> bool:
        return bool(m.get("expires_at")) and time.time() > m["expires_at"]

    # ── the gate ─────────────────────────────────────────────────────────────

    def _deny_reason(self, mandate: Optional[dict], payee: str, amount: float, currency: str) -> Optional[str]:
        """Return a controlled denial code, or None if the request is admissible."""
        if mandate is None:
            return "unknown_mandate"
        if self._mandate_expired(mandate):
            return "mandate_expired"
        if not isinstance(amount, (int, float)) or amount <= 0:
            return "invalid_amount"
        if currency.upper() != mandate["currency"]:
            return "currency_mismatch"
        if payee not in mandate["payees"]:
            return "payee_not_allowed"
        if amount > mandate["per_payment_cap"]:
            return "over_per_payment_cap"
        if round(mandate["spent"] + amount, 2) > mandate["total_cap"]:
            return "over_total_cap"
        return None

    def request_payment(self, mandate_id: str, payee: str, amount: float,
                        currency: str = "EUR", memo: str = "") -> dict:
        """Validate against the mandate's HARD caps and, if admissible, create a
        ``pending`` payment. Returns ``{"ok": False, "reason": <code>}`` on denial
        or ``{"ok": True, "payment": {...}}`` — denial is never pending."""
        mandate = self._mandates.get(mandate_id)
        self._sync_mandate_dimension(mandate)
        payee = str(payee).strip()
        reason = self._deny_reason(mandate, payee, amount, currency)
        if reason:
            self._record("deny_payment", reason, mandate_id=mandate_id, payee=payee, amount=amount)
            return {"ok": False, "reason": reason}
        # ORIZONT-24 K1 (payment micro-wave): mediate the *admissible* request through
        # the Action Kernel when enabled (default-off → this block is skipped and the
        # path below is byte-identical to before). A DENY (kill-switch engaged /
        # over-budget / runaway loop) refuses the request before it can become pending;
        # GRANT/QUEUE fall through to the existing approval-gated pending flow — payments
        # never auto-settle, so the kernel only adds a hard *deny* capability, it can't
        # relax the always-approval rule.
        if self._kernel is not None:
            from agents.core.kernel import Action, Verdict, kernel_enabled
            if kernel_enabled():
                decision = self._kernel(Action(
                    kind=self.KIND, agent=self._agent,
                    title=f"Pay {payee} {amount} {currency}",
                    payload={"mandate_id": mandate_id, "payee": payee,
                             "amount": float(amount), "currency": currency.upper(),
                             "memo": str(memo)[:280]},
                    origin="generated"))
                if decision.verdict is Verdict.DENY:
                    self._record("deny_payment", f"kernel:{decision.reason}",
                                 mandate_id=mandate_id, payee=payee, amount=amount)
                    return {"ok": False, "reason": "kernel_denied", "detail": decision.reason}
        payment = {
            "id": secrets.token_urlsafe(8),
            "mandate_id": mandate_id,
            "payee": payee,
            "amount": float(amount),
            "currency": currency.upper(),
            "memo": str(memo)[:280],
            "status": PENDING,
            "created_at": time.time(),
        }
        self._payments.append(payment)
        with self._lock:
            self._save()
        self._sync_mandate_dimension(mandate)
        self._record("request_payment", "within mandate; awaiting approval",
                     payment_id=payment["id"], payee=payee, amount=amount)
        return {"ok": True, "payment": dict(payment)}

    def _find(self, payment_id: str) -> Optional[dict]:
        for p in self._payments:
            if p["id"] == payment_id:
                return p
        return None

    def approve(self, payment_id: str) -> dict:
        p = self._find(payment_id)
        if p is None:
            raise ValueError("payment not found")
        if p["status"] != PENDING:
            raise ValueError("payment is not pending")
        # Re-check caps at approval time (the mandate may have changed/expired).
        mandate = self._mandates.get(p["mandate_id"])
        reason = self._deny_reason(mandate, p["payee"], p["amount"], p["currency"])
        if reason:
            p["status"] = REJECTED
            p["reason"] = reason
            with self._lock:
                self._save()
            self._record("auto_reject_on_approve", reason, payment_id=payment_id)
            raise ValueError("payment no longer admissible")
        p["status"] = APPROVED
        p["approved_at"] = time.time()
        with self._lock:
            self._save()
        self._sync_mandate_dimension(mandate)
        self._record("approve_payment", "owner approved", payment_id=payment_id, amount=p["amount"])
        return dict(p)

    def reject(self, payment_id: str) -> dict:
        p = self._find(payment_id)
        if p is None:
            raise ValueError("payment not found")
        if p["status"] not in (PENDING, APPROVED):
            raise ValueError("payment cannot be rejected")
        p["status"] = REJECTED
        p["decided_at"] = time.time()
        with self._lock:
            self._save()
        self._record("reject_payment", "owner rejected", payment_id=payment_id)
        return dict(p)

    def settle(self, payment_id: str) -> dict:
        """Settle an APPROVED payment: increment the mandate's spend (enforcing the
        total cap again) and mark it settled. Rail-agnostic — no money actually
        moves here; a real rail adapter would plug in at this seam."""
        p = self._find(payment_id)
        if p is None:
            raise ValueError("payment not found")
        if p["status"] != APPROVED:
            raise ValueError("only an approved payment can settle")
        mandate = self._mandates.get(p["mandate_id"])
        if mandate is None:
            raise ValueError("mandate gone")
        # Final, authoritative cap check before "spending".
        if round(mandate["spent"] + p["amount"], 2) > mandate["total_cap"]:
            p["status"] = REJECTED
            p["reason"] = "over_total_cap"
            with self._lock:
                self._save()
            self._record("auto_reject_on_settle", "over_total_cap", payment_id=payment_id)
            raise ValueError("would exceed total cap")
        mandate["spent"] = round(mandate["spent"] + p["amount"], 2)
        p["status"] = SETTLED
        p["settled_at"] = time.time()
        with self._lock:
            self._save()
        self._sync_mandate_dimension(mandate)
        self._record("settle_payment", "settled (no real rail)", payment_id=payment_id,
                     amount=p["amount"], mandate_spent=mandate["spent"])
        return dict(p)

    def list_payments(self, status: Optional[str] = None) -> list[dict]:
        return [dict(p) for p in self._payments if status is None or p["status"] == status][::-1]
