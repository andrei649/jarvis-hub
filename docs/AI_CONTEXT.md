# AI Context Map — loading this repo into a 1M-token assistant

> How to feed Jarvis Hub to a large-context model (Claude Fable 5, 1M tokens) without wasting
> the window or missing the load-bearing files. Humans: this is also the fastest "what do I read
> first" guide. Generated 2026-06-10 · sizes are estimates (chars ÷ 4), re-check when stale.
>
> **Ground rules** (same as [AGENTS.md](../AGENTS.md)): `BACKLOG.md` is the single source of
> truth for priorities · `MOONSHOT.md` for vision/principles · `docs/ARCHITECTURE.md` for "where
> does code live". When docs disagree, BACKLOG wins and the others are stale — fix them.

---

## TL;DR for an assistant with 1M context

The whole repo as text is **~2M tokens** — do NOT load it raw. Load **Tier 0 + Tier 1**
(~75K tokens) for any task, then add the **one task bundle** you need (each ≤350K). For code +
docs at once, `python export_repo.py --core` → `repo_export.txt` (**~730K tokens**: the Python
hub + all docs, skipping tests/worldview/mobile/desktop/rust) fits a 1M window with headroom;
the full export without `--core` is **~1.1M** and does NOT fit once you add prompt overhead.
*(Numbers re-measured 2026-06-10 after fixing the exporter — it used to swallow lockfiles and
its own previous output.)*

---

## Tier 0 — always load first (~25K tokens)

Order matters: each file assumes the previous ones.

| # | File | ≈ tokens | Why |
|---|------|----------|-----|
| 1 | `CLAUDE.md` | 0.2K | Entry point — routing rules to everything else |
| 2 | `AGENTS.md` | 1.6K | Non-negotiable conventions, parity rules, multi-agent workflow |
| 3 | `docs/ARCHITECTURE.md` | 9K | Entry points, request lifecycle, module index, how-to recipes |
| 4 | `MOONSHOT.md` | 3K | Vision, principles, phase gates — the drift check |
| 5 | `STATUS.md` | 2.5K | Current snapshot (version, counts, agent roster) |
| 6 | `README.md` | 2.5K | Public framing, run instructions |
| 7 | `JARVIS.md` | 3K | Architecture overview + directory tree |

## Tier 1 — project state (~50K tokens; load for any planning/backlog/docs task)

| File | ≈ tokens | Why |
|------|----------|-----|
| `BACKLOG.md` | 42K | THE priority truth. Large because it's the full ledger — for quick tasks read only the header through "Status General" (~3K) plus the section you're touching |
| `GO_LIVE_PLAN.md` | 5.5K | Features, marketing brief, v1.0 launch checklist |
| `docs/2026-06-10-full-project-analysis.md` | 1.5K | Latest whole-repo audit: stats, debt, parity verdict |

## Task bundles — add exactly one (Tier 2)

| Task | Load | ≈ tokens |
|------|------|----------|
| **Backend work** (`agents/`) | `agents/core/<touched module>` + `agents/web.py` (or the relevant `agents/core/routers/*`) + matching `tests/test_*.py`. Full backend = ~330K — prefer the module index in ARCHITECTURE §3 to pick files | 10–330K |
| **HUD v2 / frontend** | `frontend/src/**` (~67K) + `docs/design/HUD_V2_REMAINING.md` + `HUD_V2_COVERAGE_AND_PLAN.md` + `tests/test_hud_v2_parity.py` | ~80K |
| **WorldView** | `worldview/README.md` + `worldview/{frontend,api}/src` — standalone stack, nothing else needed | ~150K |
| **Mobile parity** | `mobile/**` + `mobile/PARITY.md` + the endpoint list from ARCHITECTURE | ~25K |
| **Security/audit** | `agents/core/security/**` + `docs/AUDIT.md` + `docs/MANUAL_TESTING.md` + `SECURITY.md` | ~40K |
| **Marketing/brand** | `docs/BRAND_BOOK.md` + `GO_LIVE_PLAN.md` §3 + `docs/VALUATION_AND_PRICING.md` + `docs/GTM_PLAN.md` | ~25K |
| **Voice** | `docs/VOICE.md` + `agents/core/voice/**` + `frontend/src/voice.ts` | ~25K |
| **Whole-codebase sweep** | `python export_repo.py --core` → `repo_export.txt` (hub + docs; regenerate on demand — the file is gitignored, never committed). Full export (no flag) ≈1.1M — too big for 1M with overhead | ~730K |

**History / research** (`docs/HISTORY.md`, `docs/research/*`, `docs/superpowers/*`,
`CHANGELOG.md` below the Unreleased block) is provenance — load only when investigating *why*
something is the way it is. Dated reports are immutable snapshots; never "fix" their numbers.

## What NOT to load

- `package-lock.json`, `repo_export.txt` (unless regenerated for a sweep), `agents/web/v2/assets/*`
  (built bundle — read `frontend/src` instead), `agents/web/static/*` (legacy v1 HUD),
  `memory_logs/`, `training/`, `worldview/**/dist`, `docs/internal/` (archived scratch — design
  handoff, one-shot session prompts, superseded v0.2.x docs; see its README for what's there).
- `BACKLOG.md` middle sections for unrelated horizons — use the header + your section.

## Keeping this map healthy (rules for every PR)

1. **One truth per fact.** Counts (tests/agents/routes/SP) live in BACKLOG; the satellites quote
   it. If you change a count, sweep README/STATUS/JARVIS/GO_LIVE_PLAN in the same PR
   (the 2026-06-10 reconciliation is the cautionary tale).
2. **Date your reports** (`docs/YYYY-MM-DD-*.md`) and mark historical tables as snapshots, so an
   AI can tell *current* from *provenance* without git archaeology.
3. **New doc → register it** in CLAUDE.md (if it's a routing target), MOONSHOT §8 (if canon),
   and this map (if it changes a bundle).
4. Keep this file's token estimates honest when a bundle grows by >25%.
