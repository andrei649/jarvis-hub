# Full code & project analysis — 2026-06-10

> Scope: whole-repo code analysis, docs-vs-code accuracy audit, and a HUD V2 ↔ backend parity
> re-audit. Companion to the pre-1.0 audit gate ([AUDIT.md](AUDIT.md)). Numbers verified against
> the working tree at `2c3711b` (post-#180).

---

## 1. Shape of the codebase (verified)

| Component | Size | Notes |
|---|---|---|
| `agents/` (backend) | ~37k LOC Python, 226 files | `web.py` 4,967 LOC (~253 routes), `core/orchestrator.py` 2,180 LOC |
| `tests/` | ~27k LOC, 210 files, 2,088 `def test_` (2,156 passed w/ parametrize, 1 skipped) | + 184 frontend JS tests (Vitest) |
| `frontend/` (HUD V2) | ~4.2k LOC TS/React, 24 files | Vite-bundled, default UI at `/` since 2026-06-08 |
| `worldview/` | ~15.6k LOC TS | Standalone Next.js + Deck.gl + Fastify stack (H19, 33/33 ✅) |
| `skills/` | 13 skills, ~1.8k LOC | Loader-pattern plugins |
| `mobile/` | ~2.3k LOC | + `PARITY.md` ledger (current) |
| `rust/`, `desktop/` | minimal / Tauri source | H11 items — compile host-side, not in CI |
| Agents | **17 active** (incl. Argus, Howard) + 17 bench | `agents/_system/agents.yaml` |

## 2. Architecture verdict

**Strengths:** clean channel-adapter gateway (7 channels); security-first web layer (token guards
with `secrets.compare_digest`, per-IP rate limiting, trusted-proxy fail-closed, secret masking);
hybrid LLM router with tiering + graceful degradation; deep observability (traces, cost, run
history, Merkle audit); test discipline mapped to backlog IDs.

**Top debt (all already tracked):**
1. **CLN-2** — `Orchestrator` god object (2,180 LOC, 20+ plugins hardcoded in ctor). In progress
   (`ComponentRegistry`, `ChannelManager` extracted); next: AgentManager/PluginManager.
2. **CLN-3** — `web.py` god module (4,967 LOC). In progress (8 domains extracted to
   `core/routers/`); continue the per-domain `APIRouter` split.
3. Silent generic `except Exception` in several endpoints (chat, dashboard, ticker) — log before
   degrading.
4. `_AGENT_META` hardcoded in `web.py` — belongs in `agents.yaml`.
5. `learning_loop.py` vs `learning/` dual structure — consolidate or document.

None of these block the 1.0 audit gate; items 3–5 are good audit-pass fixes.

## 3. Docs-vs-code audit (fixed in this PR)

| Doc | Was | Now |
|---|---|---|
| `README.md` | 16 agents · 1,894-test badge · "1,764 tests" · "~166/186 (82%)" | 17 agents (Argus + Howard listed) · 2,156 · 194/196 (≈99% SP) + HUD-gap pointer |
| `JARVIS.md` | "16 agents" ×3 · ~203 routes · "active: ORIZONT 8" | 17 · ~253 · pre-1.0 audit gate |
| `STATUS.md` | header 1,764 tests / ~203 routes / 82%; agent table missing Argus+Howard | updated; old endpoint table marked as historical snapshot |
| `GO_LIVE_PLAN.md` | H11 "0/4", H12 "10/15", H13–17 "12/20", metrics 1,764 / ~203 / 82%, gap "~189 SP" | H11 4/4 ✅, H12 24/25, H13–17 19/20, metrics current, gap ~13 SP (GPU-bound) |
| `docs/design/HUD_V2_REMAINING.md` | said v2 is opt-in at `/v2` | cutover noted; §10 re-audit added |
| `BACKLOG.md`, `MOONSHOT.md`, `docs/ARCHITECTURE.md`, `mobile/PARITY.md`, `CHANGELOG.md` | — | **accurate, no changes needed** |

Single source of truth held: BACKLOG.md was right everywhere; the satellites had drifted.

## 4. HUD V2 ↔ backend parity (the headline question)

**Verdict: yes — the backend moved ahead of HUD V2 again, but visibly this time, not silently.**

- The coverage gate (`tests/test_hud_v2_parity.py`) is green: all ~253 routes are classified to a
  HUD surface or `NOT_IN_HUD`, so nothing is *lost*.
- The **depth** gap regrew: HUD V2 actively calls ~50 endpoints, ~10 more read-only; **~37
  write/recent endpoints have no UI control**, including the 2026-06-09 wave
  (`/api/cognition/stream` SSE, sender pairing H12.19, auth-profile rotation H12.20, transcript
  ingest H12.25, A2A inbox H16.2, payment lifecycle actions H16.3) plus carried-over depth items
  (Settings DB editor, prompt rollback, Data Spaces CRUD, heartbeat control, sandbox UI, bench
  promotion, preference suggestions).
- Root cause: the P4 "depth pass" of the HUD V2 plan was deliberately deferred at cutover
  (2026-06-08), and the backend kept shipping. The browser↔mobile parity rule in `AGENTS.md`
  covers mobile but there was **no equivalent ledger for HUD depth** — that's why it happened
  "again".

**Fixes applied:** the gap is now a tracked backlog task (**TASK-2**, P2, 13 SP) with the full
punch-list in `HUD_V2_REMAINING.md` §10. Estimated 3–5 PRs (~2–3 weeks part-time) to "nothing
missed". **Recommendation:** extend the AGENTS.md parity rule so a PR adding a user-facing
endpoint must also touch the HUD (or add to TASK-2's list) — same mechanism that keeps
`mobile/PARITY.md` honest.

## 5. Recommendations (priority order)

1. **Run the audit gate** (AUDIT.md + MANUAL_TESTING.md on the RTX box) — it's the only thing
   between 9.9.9 and the 1.0 tag besides two GPU-bound items (H12.14, H13.3).
2. **TASK-2 wave 1** (1 PR): cognition SSE in cockpit, payment approve/reject cards in Trust,
   LIVE/SEED indicator — highest visibility per effort.
3. **Adopt the HUD-parity PR rule** (AGENTS.md §bridge, one paragraph) to prevent recurrence.
4. Continue CLN-2/CLN-3 incrementally; fold the silent-exception logging fix into audit fixes.
5. Pre-1.0: execute the planned MIT → Apache-2.0 relicense + TRADEMARKS.md, and revisit the
   "Jarvis" naming risk (see `docs/BRAND_BOOK.md` §2) before Phase 2.

---

*Marketing artifacts produced from this analysis: [`docs/BRAND_BOOK.md`](BRAND_BOOK.md) (brand
book incl. repo title/description/topics) — repo metadata itself must be applied manually in
GitHub Settings (no API surface in this session).*
