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


def _local_hour(value: str) -> int | None:
    """Local wall-clock hour (0–23) of an ISO timestamp, or None if unparseable.

    The autonomy worker defines the night window in *local* time
    (`autonomy_coordinator` calls `is_night_window(datetime.now().hour, …)`), so
    the night-shift split converts the stored **UTC** stamp (`TaskQueue._now()`)
    back to the server's local zone — which, on a single-user box, is the user's
    own clock. A naive stamp (no tzinfo) is read as-is.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone()  # → server local zone
    return dt.hour


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


def _proposal_funnel(
    queue,
    cutoff: float,
    fetch_limit: int,
    *,
    surfaced_task_ids: set[int] | None = None,
):
    """P1 diagnostic — where proactive proposals drop off. A *cohort* funnel over the
    proposals **created** in the window: of those, how many surfaced (a decision card
    reached the inbox), were accepted (``done``), rejected, or are still pending.
    ``surface_rate``/``accept_rate`` localize the drop-off, so a low north-star is
    diagnosable: not enough proposed? proposed but never surfaced? surfaced but rejected?
    Returns ``None`` with no queue."""
    if queue is None:
        return None
    proposed = surfaced = accepted = rejected = 0
    for t in queue.list(limit=fetch_limit):
        if not _in_window_iso(getattr(t, "created_at", None), cutoff):
            continue
        proposed += 1
        surfaced_from_ledger = surfaced_task_ids is not None and t.id in surfaced_task_ids
        if surfaced_from_ledger or (
            surfaced_task_ids is None and getattr(t, "pushed", 0)
        ):
            surfaced += 1
        st = str(getattr(t, "status", "")).lower()
        if st == "done":
            accepted += 1
        elif st == "rejected":
            rejected += 1
    resolved = accepted + rejected
    return {
        "proposed": proposed,
        "surfaced": surfaced,
        "accepted": accepted,
        "rejected": rejected,
        "pending": proposed - accepted - rejected,   # still-open (or failed)
        "surface_rate": round(surfaced / proposed, 4) if proposed else None,
        "accept_rate": round(accepted / resolved, 4) if resolved else None,
    }


def compute_north_star(
    queue,
    run_history=None,
    tracer=None,
    *,
    budget=None,
    attention_ledger=None,
    ambient_store=None,
    ambient_night_ledger=None,
    owner_timezone: str = "UTC",
    days: int = 7,
    now: float | None = None,
    fetch_limit: int = 100_000,
    night_window: tuple[int, int] = (23, 6),
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
    night_window:
        ``(start_hour, end_hour)`` of the local-time night shift (default
        ``(23, 6)`` — same as the worker's ``autonomy.night_start/end``). Drives
        the ``night_shift`` split: how many *accepted* actions completed overnight
        ("works while you sleep" as a reported number).

    Returns a JSON-safe dict; every metric is ``None`` rather than a fabricated
    value when its source has no data.
    """
    from agents.core.autonomy.worker import (
        is_night_window,  # lazy: no autonomy import at module load
    )

    days = max(1, int(days))
    now = time.time() if now is None else float(now)
    cutoff = now - days * _DAY_SECONDS

    # ── autonomy decisions in window ────────────────────────────────────────
    done = rejected = pushed = night_done = 0
    if queue is not None:
        for t in queue.list(status="done", limit=fetch_limit):
            if not _in_window_iso(t.updated_at, cutoff):
                continue
            done += 1
            # "works while you sleep" — bucket the accepted action by the local
            # hour it *completed* (`updated_at`, the terminal-state proxy).
            h = _local_hour(t.updated_at)
            if h is not None and is_night_window(h, *night_window):
                night_done += 1
        rejected = sum(
            1 for t in queue.list(status="rejected", limit=fetch_limit)
            if _in_window_iso(t.updated_at, cutoff)
        )
        pushed = sum(
            1 for t in queue.list(limit=fetch_limit)
            if getattr(t, "pushed", 0) and _in_window_iso(t.updated_at, cutoff)
        )

    # H33.4: when the persistent attention ledger is available, committed
    # provider deliveries are the truth. TaskQueue.pushed remains only the
    # backwards-compatible fallback for older stores.
    attention = None
    surfaced_task_ids: set[int] | None = None
    if attention_ledger is not None:
        pushes = calls = failures = released = downgraded = samples = 0
        surfaced_task_ids = set()
        try:
            records = attention_ledger.records(limit=fetch_limit)
        except Exception:
            records = []
        for record in records:
            reserved_at = record.get("reserved_at")
            if not isinstance(reserved_at, (int, float)) or float(reserved_at) < cutoff:
                continue
            samples += 1
            channel = str(record.get("channel_class") or "")
            state = str(record.get("state") or "")
            category = str(record.get("failure_category") or "")
            spent = record.get("spent") == 1
            if state == "delivered" and channel == "decision_push":
                pushes += 1
                delivery_id = str(record.get("delivery_id") or "")
                parts = delivery_id.split("-")
                if len(parts) >= 2 and parts[0] == "task" and parts[1].isdigit():
                    surfaced_task_ids.add(int(parts[1]))
            elif state == "delivered" and channel == "call":
                calls += 1
            elif state == "failed" and category == "budget_exhausted":
                downgraded += 1
            elif state == "failed" and spent:
                failures += 1
            elif state == "failed":
                released += 1
        pushed = pushes
        attention = {
            "pushes": pushes,
            "calls": calls,
            "failures": failures,
            "released_reservations": released,
            "downgraded_interrupts": downgraded,
            "samples": samples,
        }

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

    ambient_night_shift = None
    if ambient_store is not None and ambient_night_ledger is not None:
        from agents.core.ambient.night import ambient_night_report

        ambient_night_shift = ambient_night_report(
            ambient_store=ambient_store,
            night_ledger=ambient_night_ledger,
            timezone_name=owner_timezone,
            start_hour=night_window[0],
            end_hour=night_window[1],
            cutoff=cutoff,
        )

    return {
        "period": "weekly",
        "days": days,
        "north_star": {
            # weekly autonomous actions accepted per active user (MOONSHOT §6)
            "accepted_per_active_user": accepted_per_active_user,
            "total_accepted": done,
            "active_users": active_users,
        },
        # P1 proof-gap: "works while you sleep" as a *number*. Of the accepted
        # actions, how many completed during the local night window — and what
        # share. `pct` is None when nothing was accepted (no fabrication).
        "night_shift": {
            "done": night_done,
            "pct": round(night_done / done, 4) if done else None,
            "window": list(night_window),  # [start, end] local hours, for transparency
        },
        "ambient_night_shift": ambient_night_shift,
        "counter_metrics": counter_metrics,
        # V4 — MOONSHOT §6 guardrails: which counter-metrics are out of bounds (empty when
        # healthy or when a metric has no data yet). `guardrails_ok` is the merge-gate bit.
        "guardrail_breaches": breaches,
        "guardrails_ok": not breaches,
        "interrupt_budget": budget_block,
        "attention": attention,
        # P1 proof-gap: the proposal funnel — diagnoses *where* proactive proposals drop off.
        "proposal_funnel": _proposal_funnel(
            queue,
            cutoff,
            fetch_limit,
            surfaced_task_ids=surfaced_task_ids,
        ),
        "raw": {
            "accepted": done,
            "rejected": rejected,
            "decisions": decisions,
            "interrupts": pushed,
            "latency_samples": len(latencies),
        },
    }
