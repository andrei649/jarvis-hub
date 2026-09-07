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
  "night_shift": {                   // P1 — "works while you sleep" as a number
    "done": 2,                       // accepted actions that COMPLETED in the night window
    "pct": 0.5,                      // overnight share of accepted; null if none accepted
    "window": [23, 6]                // local-time [start, end] used (autonomy.night_start/end)
  },
  "counter_metrics": {
    "interrupt_rate_per_day": 0.286, // tasks pushed to the inbox / days  (budget ≤4/day)
    "reject_rate": 0.2,              // rejected / (done + rejected); null if no decisions
    "local_pct": 80,                 // RunHistory.locality(since=cutoff) — % served on-device IN THE WINDOW; null if no routed runs
    "p95_latency_ms": 48.0           // 95th pct of per-turn non-LLM total_ms; null if no traces
  },
  "interrupt_budget": { "per_day": 4, "remaining": 3 }, // null if the budget isn't wired
  "proposal_funnel": {                  // P1 diagnostic — cohort over proposals CREATED in the window
    "proposed": 4, "surfaced": 2,       // surfaced = a decision card reached the inbox (pushed)
    "accepted": 2, "rejected": 1, "pending": 1,
    "surface_rate": 0.5,                // surfaced / proposed  (null if none proposed)
    "accept_rate": 0.6667               // accepted / (accepted + rejected)  (null if none resolved)
  },                                     // null if no queue
  "raw": { "accepted": 4, "rejected": 1, "decisions": 5, "interrupts": 2, "latency_samples": 5 }
}
```

> **`proposal_funnel` localizes a low north-star.** The north-star counts *accepted* actions; the
> funnel says **where proposals drop off** — too few proposed (watchers quiet), proposed-but-never-
> surfaced (policy auto-handling / not pushed), or surfaced-but-rejected (proposals not useful). It is
> a *created-in-window cohort* (so `proposed` uses `created_at`, unlike `raw.accepted` which is
> resolved-in-window by `updated_at`).

> **`night_shift` makes "works while you sleep" a reported number.** Of the accepted actions, how many
> *completed* during the local night window — the headline P1 claim, now backed by a count and a share
> instead of a slogan. It buckets each `done` task by the **local** hour of its `updated_at` (the
> stored UTC stamp converted to the server's zone — the user's clock on a single-user box), reusing the
> worker's `is_night_window()` so the split matches the same window that gated the overnight tier caps.
> `window` echoes the `[start, end]` applied (from `autonomy.night_start`/`night_end`, default 23→6).

## Sources (reused, not duplicated)

| Metric | Source | File |
|---|---|---|
| accepted / rejected / interrupts | autonomy `TaskQueue` (`status`, `pushed`, `updated_at`) | `agents/core/autonomy/queue.py` |
| % local vs cloud | `RunHistory.locality()` | `agents/core/run_history.py` |
| p95 per-turn latency | `Tracer.list()` → `timings.total_ms` | `agents/core/observability/tracer.py` |
| interrupt budget | `InterruptBudget` (≤4/day) | `agents/core/autonomy/worker.py` |
| activation (time to first governed action) | `first_action.activation_state()` | `agents/core/first_action.py` |

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
