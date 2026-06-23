# ORIZONT 24 · P1 — Proactive Autonomy Core (design)

> Spec for the first capability pack — the one that **directly moves the north-star** ("weekly
> autonomous actions accepted per active user", MOONSHOT §6). P1 does **not** build the proactive loop
> (it exists and is wired); it drives that loop **SEAM→VERIFIED** on the Track-K/V substrate and closes
> the three gaps that keep *"works while you sleep"* from being **real and measured**.
> Owner: Andrei · Track P (pack #1, do first) · ~8 SP · Priority: P0 · Phase C.
> Dep: Track K (K1–K4, mediation) + Track V (V1–V2, harness + readiness) · Direction:
> [BACKLOG.md → ORIZONT 24](../../../BACKLOG.md) · vocabulary: [Horizon-6 autonomy spec](2026-05-31-horizon6-autonomous-jarvis-design.md).
> **Compose, don't rebuild:** the loop is code-complete end-to-end; P1 is *instrumentation + reality-
> proof + substrate-wiring*, not new autonomy.

## Today (what exists, grounded)

The ambient loop (Horizon-6's "trigger → queue → gated execution → decision inbox") is **wired end-to-end**:

- **Watchers ("finds its own work")** — `autonomy/observer.py:207` (`ProactiveObserver`: Resource/Service
  probes) + `autonomy/watchers.py:36` (`EventWatcher`: Email/Calendar/Finance/Health/WorldView probes),
  both called every ~60s by `autonomy_coordinator.py:89`. State-change **debounce** (fire only on a
  health transition) + **durable dedupe** across restarts (`watchers.py:595`, 12h window).
- **Propose → gate** — `AutonomyWorker.submit()` (`worker.py:82`) runs `policy.decide()` (`policy.py`:
  READ_ONLY/REVERSIBLE→ACT, EXTERNAL→NOTIFY, IRREVERSIBLE/money→ASK) → enqueues to the `TaskQueue`
  state machine (`queue.py`, `PROPOSED→APPROVED/BLOCKED/REJECTED→DONE/FAILED`).
- **Decision inbox** — `inbox.py:31` builds the Telegram card (✅ Aprob / ✏️ Editez / ❌ Resping / 🕓 Amân);
  `worker.py:101` `_maybe_push` spends the **`InterruptBudget`** (`worker.py:43`, `per_day=4` — the
  MOONSHOT §5.4 law) and `mark_pushed`es the task.
- **Execute (governed write-back)** — `TaskExecutor` (prefix dispatch, wired in
  `autonomy_coordinator.py:109`) → `WriteBackBroker` (`writeback.py:72`, allow-listed catalog + SSRF
  host set + `SecretBroker` injection at the approval boundary), `SocialBroker` (`social.py:188`),
  `CallBroker` (`call_broker.py:139`, itself interrupt-budget-aware).
- **Measure** — `observability/north_star.py:71` `compute_north_star`: **only `TaskStatus.DONE` in the
  trailing window counts** as `total_accepted` / `accepted_per_active_user`; `reject_rate` from
  REJECTED; `interrupt_rate_per_day` from `pushed`; exposed at `GET /api/metrics/north-star`.

**What's actually missing** (the loop runs; the *proof* doesn't), per the code map:

- **G1 — no unified "Today in Jarvis" timeline (theme 0.38).** `autonomy/digest.py:28` (task recap) and
  `memory/digest.py` (learnings) are **separate**; nothing fuses "what Jarvis did *and* learned" into one
  chronological feed.
- **G2 — "works while you sleep" is unmeasured.** `is_night_window()` exists (gates night-shift *tier
  caps*) but `north_star.py` counts DONE without splitting by night window — so the headline claim has
  **no number behind it**.
- **G3 — no proposal-funnel observability.** Each hop logs separately; there's no single view of
  *signals → findings → submitted → approved → done* to show where proactive work drops, or to tune
  probe thresholds.
- **SEAM reality:** the personal watchers depend on **live plugins** (Gmail/Calendar/Finance/Health/
  WorldView) that return null-client stubs without keys — so most proactive *sources* are SEAM today.

## Approach

Drive the existing loop to **VERIFIED** on the substrate, and turn the three gaps into instrumentation.

```
 watchers (SEAM→WIRED→VERIFIED per source)        ── Track V: each rail gets a reality-harness;
   observer.py · watchers.py  ──┐                    readiness state per probe/broker in the registry
                                ▼
   policy.decide ─► TaskQueue ─► inbox (≤4/day) ─► TaskExecutor ─► write-back/social/call
                                                        │            └─ Track K: executor calls
                                                        │               kernel.authorize(action,
                                                        ▼               capability, budget) — the
                                  TaskStatus.DONE ──► north_star        pack proves the kernel on
                                       │                 │              real write-backs
                                       │                 ├─ G2: split_by_window → night-shift number
                                       │                 └─ counter-metrics (reject/interrupt/%local/p95)
                                       └─ G1: timeline.build_unified_digest(tasks + learnings)
                                       └─ G3: /autonomy/debug proposal funnel
```

### What P1 actually delivers

1. **Substrate wiring (the pack's real job).**
   - **Through Track K:** route `TaskExecutor` handlers through `kernel.authorize(action, capability,
     budget)` so every write-back/social/call is kernel-mediated — P1 is the kernel's first real
     proving ground on *irreversible external* actions (`SecretBroker` injection stays the credential
     gate, now behind one front door).
   - **Through Track V:** give each watcher→executor rail a **reality-harness** (e.g. a real-protocol
     Notion/GitHub/Calendar write against a hermetic-but-real endpoint) and a **readiness state** in the
     V2 registry. A source/broker is `VERIFIED` only when its harness is green *and* it's kernel-mediated.
2. **G1 — unified "Today in Jarvis" timeline.** New `memory/timeline.py:build_unified_digest(queue,
   memory_store, window)` fusing done-tasks (autonomy) + new facts/preferences (memory) into one
   timestamp-ordered feed; surface at `GET /api/dashboard/today` + a HUD panel. Reuses `digest.py` and
   `memory/digest.py` as sources — no new capture.
3. **G2 — night-shift measurement.** Add `split_by_window=True` to `compute_north_star` so the response
   carries `night_shift: {done, pct}` using the existing `is_night_window()`. Now "works while you
   sleep" is a **reported number**, and the HUD north-star meter (#300) can show the overnight share.
4. **G3 — proposal-funnel diagnostics.** New `GET /autonomy/debug?days=N` returning the funnel
   *signals → findings → submitted → approved → done → rejected* (counts + drop-off) plus each probe's
   live thresholds, so the loop is tunable and its health is visible. Built from `queue.list(...)` +
   probe `status()` — no new storage.

### Metric wiring (tie the pack to the north-star, precisely)

| Signal | Source transition | Where |
|--------|-------------------|-------|
| `total_accepted` ↑ (the north-star) | `→ DONE` after a real execution | `worker.py:tick` → `north_star.py:done` |
| `reject_rate` (counter) | `→ REJECTED` from the inbox | `apply_decision` → `north_star.py:rejected` |
| `interrupt_rate_per_day` (counter, ≤budget) | `mark_pushed` on a decision-card send | `_maybe_push` → `north_star.py:pushed` |
| **night-shift share (new, G2)** | DONE whose `updated_at` ∈ night window | `north_star.py:split_by_window` |

P1 "wins" when `accepted_per_active_user` rises **while** `interrupt_rate ≤ 4/day` and `reject_rate`
stays flat (trust held), with a non-zero, growing **night-shift share** — i.e. the moonshot claim,
measured, not asserted.

### Gating & safety (reuse, don't relax)

- **Interrupt budget is law** (`InterruptBudget`, ≤4/day) — unchanged; G2/G3 are read-only instrumentation.
- **Autonomy stays conservative by default** — new action classes start at ASK; night-shift runs
  reversible/read-only only (Horizon-6 H6.6), now *measured* via G2.
- **Kill-switch (K4)** halts new grants and quarantines credentials mid-loop; the funnel (G3) shows the halt.
- **No new egress surface** — write-backs keep the allow-listed catalog + SSRF host set; the kernel only
  *adds* mediation, never widens reach (MOONSHOT §5.1–5.2).

## Acceptance

1. The loop runs end-to-end against **≥1 real rail** (e.g. a live Notion/GitHub/Calendar write) and that
   capability shows `VERIFIED` in the V2 registry (harness-green **and** kernel-mediated).
2. `GET /api/metrics/north-star?split_by_window=1` returns a `night_shift` share; the HUD meter renders it.
3. `GET /api/dashboard/today` returns one chronological feed fusing autonomy actions + memory learnings.
4. `GET /autonomy/debug` shows the full funnel (signals→findings→submitted→approved→done→rejected) with
   drop-off, and each probe's thresholds.
5. Over a measured week: `accepted_per_active_user > 0` and rising, `interrupt_rate ≤ 4/day`, `reject_rate`
   within budget — proven by the metrics endpoint, not by assertion.
6. Engaging the kill-switch mid-loop halts grants + quarantines creds, visible in the funnel and audited.

## Phasing

G1 (timeline) + G2 (night metric) + G3 (funnel) are **cheap, high-signal, and add no external risk** —
land them first so the loop becomes *legible and measured* immediately. Then route the executor through
`kernel.authorize` (Track-K dep) and stand up the per-rail reality-harness (Track-V dep) to carry the
first broker to `VERIFIED`. Only then progressively turn on more live watchers (more proactive sources),
each gated SEAM→VERIFIED. This keeps "works while you sleep" honest: it's claimed only once the night-
shift number is real and at least one rail is harness-proven and kernel-mediated.
