# H34.7 — Live System Map: the architecture diagram as a realtime monitoring surface

> **Status:** EXECUTED M0–M5 in the same PR (owner request 2026-08-31); M6 mobile card remains
> open, recorded in `mobile/PARITY.md`. · Author: Claude session 2026-08-31 ·
> Base: `main` @ `42b2ad1` · BACKLOG anchor: ORIZONT 34 / H34.7.
> Provenance: an Archify (`tt-a1i/archify`, MIT) system map of Nerva was authored and validated
> on 2026-08-31 (9/9 artifact checks, showcase composition pass, containment/readability green at
> four desktop viewports). This plan turns that one-off artifact into a product feature.

---

## 1. Vision

The architecture diagram becomes a monitoring surface: **the map of what Nerva *is*, lit by what
Nerva is *doing*.** Twelve subsystem nodes — HUD, Channels, FastAPI shell, Orchestrator, Agent
Cabinet, Hybrid LLM Router, Local LLM, Cloud LLM, Memory, Plugins, Autonomy Cortex, Action
Kernel — each carrying a live health state and two-to-four headline stats; edges carrying real
traffic counters. One glance answers "is every organ healthy, where is traffic flowing, what is
degraded or mock" — spatially, not as another list of numbers.

## 2. Relationship to existing surfaces (no parallel system)

| Surface | Question it answers | This feature's relation |
|---|---|---|
| `/brain` Neural Mesh (`routers/brain.py`) | *Which agents/models are firing right now?* | Reuses its standalone-page pattern + tracer rollups; does not replace it |
| `/mission-control` + `SwarmPanel` (H34.1/H34.4, `routers/swarm.py`) | *What is the swarm doing — queue, missions, approvals, dev locks?* | Reuses the read-only aggregator pattern; Mission Control keeps ALL steering/HITL |
| **System Map (this plan)** | ***Is each subsystem healthy, and where is traffic flowing?*** | The missing topology/health lens — read-only, additive |

Builds ON: `brain.py` page pattern · `swarm.py` bounded-aggregator pattern · `plugins/honesty.py`
verdicts · `observability/tracer.py` rollups · egress monitor · kernel metrics · autonomy queue
stats. **Zero new mutating surface.**

## 3. Design decisions

1. **Topology is a checked-in contract, not code.** `agents/core/system_map/topology.json` holds
   nodes/edges (ids, labels, positions, types) mirroring the validated Archify spec, plus, per
   node, a declared `health_source` (the internal reader that produces its status). A parity test
   pins every node/edge to a real module or route — a vanished source fails CI, so the map can
   never silently go stale (the DRA lesson: shape-checked claims rot).
2. **Native render in the HUD; Archify stays out-of-band.** The product renders the topology as
   plain React SVG (no Node/Archify runtime dependency). Archify remains the *export* path: a
   script regenerates the shareable standalone HTML snapshot from the same topology contract.
3. **One bounded read.** A single new `GET /api/system-map` composes *existing* cached readers —
   never a live network probe on the request path (#949/#950 lesson: request-path blocking I/O
   froze the loop). Anything not already cached reports `unknown`, honestly.
4. **Honesty invariants (non-negotiable, from the 2026-07-28 bug hunt):** every cell is a proven
   value or `—`; `unknown` never renders green; degraded/mock nodes carry the amber MOCK
   treatment from the plugin registry; **no synthesized motion** (the `useLiveSys` sine-wave
   precedent is the anti-pattern); payload-free everywhere (titles/counts only — H34.6's
   no-tier-leak discipline).

## 4. Data contract

### `GET /api/system-map` (user_guard, read-only, `_NO_STORE_PATHS`)

```jsonc
{
  "version": 1,
  "topology_version": "2026-08-31",        // from topology.json — client detects drift
  "generated_at": "…",
  "nodes": {
    "orch":    { "status": "ok",        "stats": { "uptime_s": 86400, "turns_today": 41 }, "evidence": "readyz+session_log" },
    "llm":     { "status": "ok",        "stats": { "backend": "lmstudio", "model": "gemma-4-31b", "deep_slot": "loaded" }, "evidence": "hybrid_router.state" },
    "cloud":   { "status": "off",       "stats": { "configured": false, "calls_today": 0 }, "evidence": "egress_monitor" },
    "plugins": { "status": "degraded",  "stats": { "live": 3, "degraded": 2, "off": 20 }, "evidence": "plugins.honesty" },
    "kernel":  { "status": "ok",        "stats": { "grants": 12, "queued": 1, "denied": 0, "kill_switch": "armed" }, "evidence": "metrics.kernel" },
    "autonomy":{ "status": "attention", "stats": { "pending": 3, "failed": 1, "interrupts_left": 4 }, "evidence": "task_queue" }
    // … one entry per topology node; absent reader ⇒ "unknown"
  },
  "edges": {
    "orch-to-agents": { "count_60s": 4 },     // tracer rollup; absent ⇒ edge renders static
    "llm-to-cloud":   { "count_today": 0 }    // egress monitor tally
  }
}
```

`status ∈ ok | degraded | attention | off | unknown` — reduced per node by a small pure function
with its own unit tests; `off` = deliberately not configured (honest, not alarming); `attention`
= a real signal (failed tasks, loop-breaker tripped, kill-switch halted, local LLM unreachable,
egress violation on a LOCAL_ONLY plugin).

### Source inventory (all existing; nothing new is measured)

readiness/lifespan state · `brain.build_summary` tracer rollups · `HybridRouter` active
backend/model/slots (last-known) · egress-monitor per-plugin tallies + `local_only_violations` ·
`plugins/honesty.py` verdicts · memory stats (vector count, graph entities, recall flag,
checkpoint age) · kernel metrics + kill-switch + loop-breaker · autonomy queue counts + interrupt
budget + night-shift · channel adapter registry + inbox counts + send-rate snapshot.

## 5. UI

- **`SystemMapPanel`** (Console → Observe): React SVG topology, 2–3 s `useApi` polling. Status →
  node treatment (ok: subtle · degraded: amber + reason tooltip · attention: red emphasis · off:
  muted · unknown: dashed gray). Edge counters render as small labels; a zero/absent counter is a
  static line, never a fake pulse. Click a node → stats popover + deep link to its existing
  detailed panel (kernel → `KernelMetricsPanel`, plugins → Admin registry, autonomy → Decision
  Inbox, memory → Memory panels, swarm surfaces for agents).
- **Standalone `/map` page** (brain.html pattern) for the wall-screen/second-monitor case.
- Honest empty state when the API is unreachable (the padlock-from-missing-data bug class is the
  anti-pattern). Dark/light via existing HUD tokens.

## 6. Archify export path (out-of-band, owner-optional)

`scripts/gen_system_map.py` converts `topology.json` → Archify architecture JSON;
`npx`-invoked Archify (`tt-a1i/archify`, MIT — attribution in `LICENSES/` if vendored)
validates and delivers `docs/diagrams/nerva.architecture.html` — the presentable, shareable
snapshot (README share card, support-bundle candidate). Dev/CI tooling only; never a product
runtime dependency; the 2026-08-31 validated spec is the seed.

## 7. Phases — one reversible PR each

| # | Slice | SP | Risk | Tests |
|---|-------|----|------|-------|
| M0 | `topology.json` contract + loader + **topology↔code parity test** | 2 | R1 | contract shape, parity pins, stale-source failure |
| M1 | `routers/system_map.py` aggregator + status reducers | 3 | R2 | offline fakes per source; unknown-on-absent; payload-free assertion; route/OpenAPI/auth snapshots re-seeded |
| M2 | `SystemMapPanel` — topology render + status overlays | 3 | R1 | vitest: status treatments, honest offline, no-fake-motion guard |
| M3 | Edge counters + click-through deep links + attention emphasis | 2 | R1 | edge absent ⇒ static; deep-link targets exist (panel-chip coverage) |
| M4 | Standalone `/map` page (brain pattern) | 2 | R1 | page serves, same feed, parity snapshots |
| M5 | Archify export script + `docs/diagrams/` snapshot + attribution | 1 | R0/R1 | script round-trips topology → valid Archify spec |
| M6 | Mobile read-only status card (list, not SVG) + `PARITY.md` | 1 | R1 | mobile API test + jest |

Total ≈ 14 SP. M1 blocks M2–M4; M5/M6 independent after M0/M1. Each PR: BACKLOG tick +
`status_sync.py` in the same PR; classify risk properly against
`.github/ai-development-policy.json` at build time (the table above is the plan's estimate).

## 8. Non-goals

No steering or mutations from the map (Mission Control owns HITL) · no per-request trace
inspector (tracer/`/api/traces` exists) · no fleet/multi-install view (post-1.0) · no replacement
of `/brain` or Mission Control · no new measurement infrastructure.

## 9. Rollback & risk posture

Read-only and additive throughout; each phase is a single revert. The only R2 surface is the M1
route contract. Failure mode to design against is *dishonest green* — hence the reducers'
unit tests, the parity gate, and the unknown-never-green rule.

## 10. Owner decisions

None blocking. Optional later: whether `/map` joins the cinema/wall rotation as a stage, and
whether the Archify snapshot job runs in CI (needs `npx` network) or stays a local dev script.
