"""north_star.py — the one place that computes the MOONSHOT §6 metric set.

MOONSHOT §6 defines the north-star as **weekly autonomous actions *accepted* per
active user**, guarded by four counter-metrics: interrupt rate (urgent push/day,
budget ≤4), reject rate, % tasks served locally vs cloud, and p95 per-turn
non-LLM latency. Those primitives already live in separate stores — the autonomy
TaskQueue (accepted=`done`, `rejected`, `pushed`), RunHistory.locality(), the
Tracer's per-turn `total_ms`. This module is the *aggregator* that folds them into
one dashboard dict so the meter reads from a single, testable function instead of
five scattered call-sites.

Design notes / honesty constraints (the review's whole point):
  * **n=1 today.** The system is single-user, so "per active user" can't be
    fabricated into a fleet. `active_users` is 1 only when there is real activity
    in the window, else 0; `accepted_per_active_user` collapses to the raw accepted
    count. The signature carries `now`/`days` so the same function serves a real
    multi-user split later without a rewrite.
  * **No new storage.** Everything is derived from existing rows — no schema
    migration, no behaviour change. Pure function over injected stores → unit-
    testable offline with no LLM, network, or real hardware.
  * Windowing uses each task's `updated_at` (when it reached its terminal/decision
    state) as the best available proxy for "decided in the last N days"; the
    queue has no separate decision-time column and we add none here.
"""

from __future__ import annotations

import math
import time
from datetime import datetime

# Mirrors agents/core/autonomy/worker.py INTERRUPT_BUDGET_PER_DAY; imported lazily
# in the budget branch so this module has no autonomy import at load time.
_DAY_SECONDS = 86_400


def _iso_to_epoch(value: str) -> float | None:
    """Parse an ISO-8601 timestamp (TaskQueue `_now()` format) to epoch seconds."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return None


def _in_window_iso(value: str, cutoff: float) -> bool:
    """True if an ISO timestamp is at/after `cutoff`.

    Unparseable timestamps count as in-window so the meter never silently drops
    real rows; with well-formed data this is exact.
    """
    ep = _iso_to_epoch(value)
    return True if ep is None else ep >= cutoff


def _percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolation percentile (numpy 'linear' method). None if empty."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * (p / 100.0)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return float(s[int(k)])
    return float(s[f] + (s[c] - s[f]) * (k - f))


# ── Counter-metric guardrails (V4 / MOONSHOT §6) ──────────────────────────────
# The bounds the north-star must not be "gamed" past. These are the offline-computable
# guardrails (the north-star itself needs real usage and is tracked on the live board).
# A metric with no data yet (None) is **skipped, never failed** — we don't fabricate a
# breach. Surfaced in the payload so the HUD board flags it and a real-usage merge gate
# can act on it.
GUARDRAILS: dict[str, dict] = {
    "interrupt_rate_per_day": {"max": 4.0},    # MOONSHOT §5.4 — ≤4 proactive pushes/day
    "reject_rate": {"max": 0.5},               # >half rejected ⇒ autonomy is annoying
    "local_pct": {"min": 50.0},                # local-first floor (% of routed runs local)
    "p95_latency_ms": {"max": 2000.0},         # p95 per-turn non-LLM latency < 2s
}


def check_guardrails(counter_metrics: dict) -> list[dict]:
    """Return the list of breached guardrails (empty = healthy). None-valued metrics
    (no data) are skipped, not failed."""
    breaches = []
    for metric, rule in GUARDRAILS.items():
        val = counter_metrics.get(metric)
        if val is None:
            continue
        if "max" in rule and val > rule["max"]:
            breaches.append({"metric": metric, "value": val, "threshold": rule["max"], "direction": "max"})
        if "min" in rule and val < rule["min"]:
            breaches.append({"metric": metric, "value": val, "threshold": rule["min"], "direction": "min"})
    return breaches


def compute_north_star(
    queue,
    run_history=None,
    tracer=None,
    *,
    budget=None,
    days: int = 7,
    now: float | None = None,
    fetch_limit: int = 100_000,
) -> dict:
    """Compute the north-star + counter-metrics over the trailing `days` window.

    Parameters
    ----------
    queue:
        An autonomy ``TaskQueue`` (or None). Source of accepted (`done`),
        `rejected`, and interrupt (`pushed`) counts.
    run_history:
        A ``RunHistory`` exposing ``locality()`` (or None) for % local vs cloud.
    tracer:
        A ``Tracer`` exposing ``list(limit)`` with per-turn ``total_ms`` (or None)
        for p95 latency.
    budget:
        Optional ``InterruptBudget`` (``per_day`` / ``remaining()``).
    days, now:
        Trailing window length and reference epoch (injectable for deterministic
        tests). Defaults: 7 days, ``time.time()``.

    Returns a JSON-safe dict; every metric is ``None`` rather than a fabricated
    value when its source has no data.
    """
    days = max(1, int(days))
    now = time.time() if now is None else float(now)
    cutoff = now - days * _DAY_SECONDS

    # ── autonomy decisions in window ────────────────────────────────────────
    done = rejected = pushed = 0
    if queue is not None:
        done = sum(
            1 for t in queue.list(status="done", limit=fetch_limit)
            if _in_window_iso(t.updated_at, cutoff)
        )
        rejected = sum(
            1 for t in queue.list(status="rejected", limit=fetch_limit)
            if _in_window_iso(t.updated_at, cutoff)
        )
        pushed = sum(
            1 for t in queue.list(limit=fetch_limit)
            if getattr(t, "pushed", 0) and _in_window_iso(t.updated_at, cutoff)
        )

    decisions = done + rejected

    # ── latency traces in window ────────────────────────────────────────────
    latencies: list[float] = []
    if tracer is not None:
        for tr in tracer.list(500):
            ts = tr.get("ts")
            in_window = True if ts is None else float(ts) >= cutoff
            ms = tr.get("total_ms")
            if in_window and ms:
                latencies.append(float(ms))

    # ── active users (single-user honesty) ──────────────────────────────────
    active_users = 1 if (done or rejected or pushed or latencies) else 0
    accepted_per_active_user = (
        round(done / active_users, 3) if active_users else 0.0
    )

    # ── locality (already a counter-metric) ─────────────────────────────────
    local_pct = None
    if run_history is not None:
        try:
            local_pct = run_history.locality().get("local_pct")
        except Exception:
            local_pct = None

    # ── interrupt budget passthrough ────────────────────────────────────────
    budget_block = None
    if budget is not None:
        try:
            budget_block = {
                "per_day": getattr(budget, "per_day", None),
                "remaining": budget.remaining(),
            }
        except Exception:
            budget_block = None

    counter_metrics = {
        "interrupt_rate_per_day": round(pushed / days, 3),
        "reject_rate": round(rejected / decisions, 4) if decisions else None,
        "local_pct": local_pct,
        "p95_latency_ms": round(_percentile(latencies, 95), 1) if latencies else None,
    }
    breaches = check_guardrails(counter_metrics)

    return {
        "period": "weekly",
        "days": days,
        "north_star": {
            # weekly autonomous actions accepted per active user (MOONSHOT §6)
            "accepted_per_active_user": accepted_per_active_user,
            "total_accepted": done,
            "active_users": active_users,
        },
        "counter_metrics": counter_metrics,
        # V4 — MOONSHOT §6 guardrails: which counter-metrics are out of bounds (empty when
        # healthy or when a metric has no data yet). `guardrails_ok` is the merge-gate bit.
        "guardrail_breaches": breaches,
        "guardrails_ok": not breaches,
        "interrupt_budget": budget_block,
        "raw": {
            "accepted": done,
            "rejected": rejected,
            "decisions": decisions,
            "interrupts": pushed,
            "latency_samples": len(latencies),
        },
    }
