# Cognition (ORIZONT 21) — Continuation / Resume Guide

> **Read this first** to pick the work up in a future session. It's the entry point;
> the three canonical artifacts below hold the depth. Status as of **2026-06-07**.

## Where we are
- **Design + code-validated plan complete and merged to `main`.** No implementation yet.
- Tracked as **`BACKLOG.md` → ORIZONT 21 — Cognition (Living Memory & Human-Like Personality)**.
- The plan was **verified against the real code** (4-agent seam sweep) — it's code-grounded, not aspirational.
- Sits **next to ORIZONT 20 (Hermes Mining)** and is **complementary**: Hermes leads on *actuation*;
  Cognition deepens *memory / personality / governance*. H21.4 **feeds + governs** Hermes's skill loop
  (H20.5 / H20.4) rather than duplicating it.

## Read first (canonical artifacts)
1. **`docs/COGNITION.md`** — the schematic & diagnostic map (~35 brain analogies → modules/stores/flags,
   memory-tier + data-flow diagrams, and a symptom→cause→remedy troubleshooting playbook).
2. **`docs/research/2026-06-07-cognition-and-tools-session.md`** — the full session record. Especially
   **§6 (the file:line seam map)** and **§7 (the refined plan v2)**.
3. **`BACKLOG.md` → ORIZONT 21** — the phased task list (H21.0–H21.5 + adjacents H21.A–D).

## The plan in one screen
- **Architecture (the long-term-quality spine):** one `agents/core/cognition/` package behind a single
  **`CognitionFacade`** registered via `ComponentRegistry` (1 line in orchestrator + 2/handler → **no
  god-object growth**). Transient per-turn state on a **`TurnContext`** (this also **fixes BUG-5**);
  durable state in **locked, keyed `JsonStore`s** `(agent,user)`/`session`. **Master `cognition.enabled`
  OFF = measurable no-op.** Reuses the already-shipped **H14** memory primitives (`decay`/`bitemporal`/
  `consolidation`/`entity`).
- **Phases:** 0 scaffold+BUG-5 · 1 honesty keystone · 2 affect+personality · 3 unbounded/neuroplastic
  memory · 4 governed learning (feeds Hermes skill loop) · 5 ensemble+maturation.
- **Memory principle:** **unbounded, append-only**; forgetting = reduced accessibility + tier demotion,
  **never deletion** (only the user erases); **neuroplastic** (re-embed on better models).
- **Honesty load-bearing:** anti-sycophancy judge in `QualityMonitor`; HEXACO Honesty-Humility frozen.
- **North-star metric (conjunctive, can't be gamed):** per-KC mastery↑ while calibration-error↓;
  first-pass acceptance↑ *while gold-correctness holds*; trait mean tracks μ with live variance *and*
  pushback-reversal ≤0.05 at high warmth; blind ensemble-ID ≥80% gated by a truth-audit.

## ▶ START HERE next session — Phase 0 + 1 (minimal high-value slice)
Lowest risk, ships no behavior change, **fixes BUG-5**, lands the honesty keystone everything else depends on.

**Phase 0 — `H21.0` scaffold + BUG-5 fix**
- Create `agents/core/cognition/` + `CognitionFacade`; register **one** component via `ComponentRegistry`
  (next to `orchestrator.py:247-267`).
- Add **`TurnContext`** (per-request; resolved `session_id`/`agent_id`/`user_id`) and route `session_id`
  through it instead of mutating `self.session_id` (fixes **BUG-5**, see `orchestrator.py:871-876`).
- Add a locked keyed `JsonStore` base for durable cognition state.
- Add a `cognition` settings category in `settings_db.DEFAULTS`, **all OFF**, with master `cognition.enabled`.
- `facade.pre_turn(ctx)` returns "" and `post_turn` no-ops when master off. Splice `pre_turn` like the
  existing `_runtime_state_block` (`orchestrator.py:1113-1120`) — **patch BOTH prompt builders**
  (`agent.process` *and* the streaming path at `orchestrator.py:1115`).
- Tests: facade no-op; `TurnContext` isolation under simulated concurrent turns.

**Phase 1 — `H21.1` honesty keystone**
- Anti-sycophancy/persona axis in `QualityMonitor.signals` (deterministic) + optional LLM judge wired at
  registration (`orchestrator.py:252` passes none today) but run **deferred** off the tracer ring (NOT
  inline at `:1306`).
- `synthesize()` (`agent.py:193-197`): replace *"Do not mention internal agent IDs"* with in-character
  attribution (preserve specialist voices).
- Surface the **Sycophancy Index** counter-metric.

## Non-negotiable guardrails
1. No per-turn state as orchestrator/`Agent` instance attrs (they're shared across concurrent turns).
2. Orchestrator touches the subsystem only through the one facade. 3. No new routes in `web.py` — use an
`APIRouter`. 4. Every behavior gated, default-OFF, under one `cognition` category, master-resolved.
5. Hot path cheap; all heavy/LLM work deferred (`asyncio.to_thread` / idle loop). 6. Durable state via
locked `JsonStore`, one store per concept; avoid SQLite sprawl. 7. Idle jobs gated-inside + try/except→warn
+ `to_thread` + honor `JARVIS_TESTING`. 8. Deterministic-default + optional injected LLM (offline-testable).
9. Drift/self-mod reversible + human-gated (decision inbox). 10. One offline `tests/test_cognition_*.py` per module.

## Prerequisites / known bugs to handle in-flight
- **BUG-5** — fixed *by* `H21.0`'s `TurnContext`.
- **BUG-11** — re-gate *edited* payloads (`policy.decide()` on the edit), required before `H21.4` governs
  the Hermes skill loop.
- **HF-6** — the skill tester must force the Docker sandbox path; require Docker in prod.
- **BUG-10** — confirm the daily-budget reset cron is actually invoked at startup (`orchestrator.py:563`).

## Relationship to Hermes (ORIZONT 20) — do NOT duplicate
- Hermes owns **skill self-improvement (H20.5)** + **self-evolution DSPy/GEPA (H20.4)**. Cognition
  **H21.4** supplies KC/calibration/correction **signals** and **governs** them — it does not reimplement.
- Hermes **H20.3 ContextCompressor** = *hot-path* compression; Cognition **H21.3** = *nightly* consolidation
  + tiering + unbounded retention. Complementary.
- **BUG-13** (the `hermes-agent` importer) is **already fixed on `main`** (PR #166). Reuse the
  YAML-frontmatter parser it added (`loader._parse_manifest`) for the `SOUL.md` front-matter parser (H21.2).

## Open doc-truth task
- Reconcile `NERVA.md` hardware section (Windows desktop / 192GB) with the actual **System76 Bonobo laptop**
  (mobile RTX 5090, 24GB) now in use.

## Resume checklist
- [ ] Read the 3 canonical artifacts.
- [ ] Branch from the latest `main`.
- [ ] Implement Phase 0 (`H21.0`); offline tests green.
- [ ] Implement Phase 1 (`H21.1`).
- [ ] Update `docs/COGNITION.md` component statuses (🟢→✅) as pieces land.
