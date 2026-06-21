# Metrics — North-Star & Counter-Metrics

The [MOONSHOT.md](../MOONSHOT.md) §6 metric set, computed in one place and exposed
read-only. This is the meter the review (`docs/REVIEW_YEAR_ONE.md` §9.5) asked for:
the thing that turns "prove value to a user" from a slogan into a number.

- **Computation:** `agents/core/observability/north_star.py` →
  `compute_north_star(queue, run_history, tracer, *, budget=None, days=7, now=None)`.
  A pure function over existing stores — no new tables, no behaviour change,
  unit-tested offline (`tests/test_north_star.py`).
- **Endpoint:** `GET /api/metrics/north-star?days=7` (default 7, clamped 1–90).
  Open, like the sibling `/api/analytics/locality`, `/api/traces`, `/api/cost`
  meters — non-sensitive aggregate counts, and the whole app is localhost-only
  until a token is set.

## Fields

```jsonc
{
  "period": "weekly",
  "days": 7,
  "north_star": {
    "accepted_per_active_user": 4.0, // total_accepted / active_users (the north-star)
    "total_accepted": 4,             // autonomy tasks that reached `done` in the window
    "active_users": 1                // see the n=1 caveat below
  },
  "counter_metrics": {
    "interrupt_rate_per_day": 0.286, // tasks pushed to the inbox / days  (budget ≤4/day)
    "reject_rate": 0.2,              // rejected / (done + rejected); null if no decisions
    "local_pct": 80,                 // RunHistory.locality() — % served on-device; null if no routed runs
    "p95_latency_ms": 48.0           // 95th pct of per-turn non-LLM total_ms; null if no traces
  },
  "interrupt_budget": { "per_day": 4, "remaining": 3 }, // null if the budget isn't wired
  "raw": { "accepted": 4, "rejected": 1, "decisions": 5, "interrupts": 2, "latency_samples": 5 }
}
```

## Sources (reused, not duplicated)

| Metric | Source | File |
|---|---|---|
| accepted / rejected / interrupts | autonomy `TaskQueue` (`status`, `pushed`, `updated_at`) | `agents/core/autonomy/queue.py` |
| % local vs cloud | `RunHistory.locality()` | `agents/core/run_history.py` |
| p95 per-turn latency | `Tracer.list()` → `timings.total_ms` | `agents/core/observability/tracer.py` |
| interrupt budget | `InterruptBudget` (≤4/day) | `agents/core/autonomy/worker.py` |

## Honesty caveats (by design)

- **n = 1 today.** The system is single-user, so the meter does **not** fabricate a
  fleet: `active_users` is `1` only when there is real activity in the window, else
  `0`, and `accepted_per_active_user` collapses to the raw accepted count. The
  function signature already carries `now`/`days`, so a real multi-user split slots
  in later without a rewrite.
- **No fabricated splits.** Every counter is `null` rather than a made-up value when
  its source has no data (`local_pct` until a routed run exists; `p95_latency_ms`
  until a trace exists; `reject_rate` until a decision is made).
- **Window proxy.** Decisions are windowed by each task's `updated_at` (its
  terminal/decision time) — the best available proxy; no decision-time column was
  added.
