"""report.py — the shareable day report + Proof-of-Action receipts (user tier).

  GET  /api/report/today                 the redacted, allow-listed report (``?format=html`` → card)
  POST /api/report/today/export          write it under <data_root>/reports/ (kernel kind ``report.export``)
  GET  /api/report/receipt/{audit_id}    one intent-log entry as a verified receipt card

All three are ``user_guard``ed reads of the owner's own stores; the export is
the only effect and it crosses the Action Kernel through the injected
authorizer bound from the live orchestrator (``kernel.binding.make_action_kernel``)
— the same shape the desktop route uses. Everything free-text in a response has
passed the secret + PII scanners in ``agents.core.day_report``; task payloads and
results are absent by construction, so this router carries no admin variant.

The north-star meter runs several full TaskQueue scans, so the build is
offloaded with ``asyncio.to_thread`` exactly like ``/api/metrics/north-star``.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from agents.core.app_state import get_orch
from agents.core.day_report import (
    EXPORT_FORMATS,
    DayReportExporter,
    build_day_report,
    build_receipt,
    render_report_html,
)
from agents.core.routers._component import require_component
from agents.core.routers._deps import user_guard
from agents.core.web_helpers import nocache_json

router = APIRouter(tags=["report"])

_NO_STORE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


def _night_window(orch) -> tuple[int, int]:
    """Mirror the worker's local-time night window (autonomy.night_start/end)."""
    get_setting = getattr(orch, "get_setting", None)
    if not callable(get_setting):
        return (23, 6)
    try:
        return (
            int(get_setting("autonomy.night_start", 23) or 23),
            int(get_setting("autonomy.night_end", 6) or 6),
        )
    except (TypeError, ValueError):
        return (23, 6)


def _model_block(orch) -> dict:
    """Model name + backend as the router reports them (names only, never keys)."""
    llm = getattr(orch, "llm_router", None)
    if llm is None:
        return {"name": None, "backend": None}
    try:
        name = getattr(llm, "active_model", None)
        backend = getattr(llm, "name", None)
    except Exception:
        name, backend = None, None
    return {"name": str(name) if name else None, "backend": str(backend) if backend else None}


def _north_star(orch, queue, night_window: tuple[int, int]) -> dict | None:
    """One-day north-star payload, or None when the meter cannot run."""
    if queue is None:
        return None
    from agents.core.observability.north_star import compute_north_star

    try:
        return compute_north_star(
            queue,
            getattr(orch, "run_history", None),
            getattr(orch, "tracer", None),
            budget=getattr(getattr(orch, "autonomy", None), "budget", None),
            attention_ledger=getattr(orch, "attention_ledger", None),
            days=1,
            night_window=night_window,
        )
    except Exception:
        return None


def _build(orch) -> dict:
    """Blocking: north-star scans + queue scan → the report. Runs in a worker thread."""
    queue = getattr(orch, "autonomy_queue", None)
    night_window = _night_window(orch)
    return build_day_report(
        _north_star(orch, queue, night_window),
        queue,
        model=_model_block(orch),
        night_window=night_window,
    )


def _exporter(orch, authorizer=None) -> DayReportExporter:
    if authorizer is None:
        from agents.core.kernel.binding import make_action_kernel

        authorizer = make_action_kernel(orch)
    return DayReportExporter(authorizer=authorizer)


@router.get("/api/report/today", dependencies=[Depends(user_guard)])
async def report_today(format: str = Query("json", pattern="^(json|html)$")):
    """The redacted "what Nerva did today" report. ``format=html`` returns the
    self-contained card (no script, no external asset) for sharing."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    report = await asyncio.to_thread(_build, orch)
    if format == "html":
        return HTMLResponse(render_report_html(report), headers=_NO_STORE)
    return nocache_json(report)


@router.post("/api/report/today/export", dependencies=[Depends(user_guard)])
async def report_today_export(req: Request):
    """Write today's report under the local reports directory. Body:
    ``{"format": "json"|"html"}``. Refusals name their reason: a contract
    violation is 400, a kernel DENY / QUEUE is 403 (``kernel_denied:…`` /
    ``approval_required``), a failed write 500."""
    orch = get_orch()
    if not orch:
        return nocache_json({"error": "not initialized"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    fmt = str((body or {}).get("format") or "json").lower()
    if fmt not in EXPORT_FORMATS:
        return nocache_json({"ok": False, "reason": "invalid_format"}, status_code=400)
    report = await asyncio.to_thread(_build, orch)
    exporter = _exporter(orch)
    result = await asyncio.to_thread(exporter.export, report, fmt)
    if result.get("ok"):
        return nocache_json({**result, "fingerprint": report["fingerprint"], "date": report["date"]})
    reason = str(result.get("reason") or "refused")
    if reason.startswith("kernel_denied") or reason in ("approval_required", "kernel_error"):
        status = 403
    elif reason == "write_failed":
        status = 500
    else:
        status = 400
    return nocache_json({"ok": False, "reason": reason}, status_code=status)


@router.get("/api/report/receipt/{audit_id}", dependencies=[Depends(user_guard)])
async def report_receipt(audit_id: str):
    """One intent-log entry (``seq``) as a Proof-of-Action receipt: the card's
    free text is scanner-redacted, the chain is verified, and ``verified`` is
    False — visibly, not silently — when the link or the chain does not hold."""
    _, log, err = require_component("intent_log", "intent log not available")
    if err is not None:
        return err
    out = await asyncio.to_thread(build_receipt, log, audit_id)
    if out["ok"]:
        return nocache_json(out["receipt"])
    reason = out["reason"]
    status = 400 if reason == "bad_audit_id" else 404 if reason == "not_found" else 503
    return nocache_json({"error": reason}, status_code=status)
