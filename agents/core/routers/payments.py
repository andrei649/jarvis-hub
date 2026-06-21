"""Governed agentic payments (H16.3) — extracted from web.py (CLN-3).

Covers the admin-guarded `/api/payments*` surface: mandate create/list, payment
request, list, and the approve/reject/settle lifecycle. Rail-agnostic — no real
rail moves money; the broker enforces caps/payee-allowlist/expiry and writes a
signed audit (IntentLog).

The `_payment_broker` singleton + its `_get_payment_broker()` accessor stay in
web.py (CLN-3 pattern, same as data_spaces): `tests/test_payments_h16_3.py` does
`monkeypatch.setattr(web, "_payment_broker", ...)`. Handlers resolve it at REQUEST
time via `_broker()`, which looks `web._get_payment_broker()` up through
`sys.modules` — so the monkeypatch is still observed and there is no static import
edge back into `agents.web`.
"""

import sys
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["payments"])


def _broker():
    web = sys.modules.get("agents.web")
    return web._get_payment_broker()  # web owns the singleton; test patches web._payment_broker


class CreateMandateBody(BaseModel):
    payees: list[str] = Field(default_factory=list)
    per_payment_cap: float = Field(..., gt=0)
    total_cap: float = Field(..., gt=0)
    currency: str = Field("EUR", max_length=8)
    ttl_seconds: Optional[float] = Field(None, gt=0)


class RequestPaymentBody(BaseModel):
    mandate_id: str = Field(..., max_length=64)
    payee: str = Field(..., max_length=128)
    amount: float = Field(..., gt=0)
    currency: str = Field("EUR", max_length=8)
    memo: str = Field("", max_length=280)


@router.post("/api/payments/mandates", dependencies=[Depends(admin_guard)])
async def create_payment_mandate(body: CreateMandateBody):
    """Pre-authorize a spending budget with hard caps + a payee allowlist."""
    try:
        return nocache_json(_broker().create_mandate(
            body.payees, body.per_payment_cap, body.total_cap, body.currency, body.ttl_seconds))
    except ValueError:
        return nocache_json({"error": "invalid mandate (need ≥1 payee and positive caps)"}, status_code=400)


@router.get("/api/payments/mandates", dependencies=[Depends(admin_guard)])
async def list_payment_mandates():
    return nocache_json({"mandates": _broker().list_mandates()})


@router.post("/api/payments/request", dependencies=[Depends(admin_guard)])
async def request_payment(body: RequestPaymentBody):
    """Request a payment against a mandate. Denied (over cap / bad payee / etc.)
    returns 400 with a reason code; admissible returns a pending payment."""
    result = _broker().request_payment(
        body.mandate_id, body.payee, body.amount, body.currency, body.memo)
    if not result.get("ok"):
        return nocache_json({"error": "payment denied", "reason": result.get("reason")}, status_code=400)
    return nocache_json(result["payment"])


@router.get("/api/payments", dependencies=[Depends(admin_guard)])
async def list_payments(status: Optional[str] = None):
    return nocache_json({"payments": _broker().list_payments(status)})


@router.post("/api/payments/{payment_id}/approve", dependencies=[Depends(admin_guard)])
async def approve_payment(payment_id: str):
    try:
        return nocache_json(_broker().approve(payment_id))
    except ValueError:
        return nocache_json({"error": "payment not found or not pending/admissible"}, status_code=400)


@router.post("/api/payments/{payment_id}/reject", dependencies=[Depends(admin_guard)])
async def reject_payment(payment_id: str):
    try:
        return nocache_json(_broker().reject(payment_id))
    except ValueError:
        return nocache_json({"error": "payment not found or cannot be rejected"}, status_code=400)


@router.post("/api/payments/{payment_id}/settle", dependencies=[Depends(admin_guard)])
async def settle_payment(payment_id: str):
    """Settle an approved payment (no real rail moves money here)."""
    try:
        return nocache_json(_broker().settle(payment_id))
    except ValueError:
        return nocache_json({"error": "payment not approved, not found, or over cap"}, status_code=400)
