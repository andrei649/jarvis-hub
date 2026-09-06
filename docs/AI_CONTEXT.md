# AI Context Map — loading this repo into a 1M-token assistant

> How to feed Nerva (repo: jarvis-hub) to a large-context model (Claude Fable 5, 1M tokens) without wasting
> the window or missing the load-bearing files. Humans: this is also the fastest "what do I read
> first" guide.
>
> **Re-measured 2026-08-27 with a real tokenizer** (`tiktoken` `o200k_base`, ±10% vs Claude's).
> The previous figures were `chars ÷ 4` estimates and understated reality by **2.7×–6.4×** — every
> number below is now counted, not estimated. To re-measure, tokenize the `export_repo.py` output
> per profile rather than dividing characters.
>
> **Ground rules** (same as [AGENTS.md](../AGENTS.md)): `BACKLOG.md` is the single source of
> truth for priorities · `MOONSHOT.md` for vision/principles · `docs/ARCHITECTURE.md` for "where
> does code live". When docs disagree, BACKLOG wins and the others are stale — fix them.

---

## TL;DR for an assistant with 1M context

The whole tracked repo as text is **~6.9M tokens** — do NOT load it raw. Load **Tier 0 + Tier 1**
(~243K tokens) for any task, then add the **one task bundle** you need.

**No `export_repo.py` profile fits a 1M window.** This is the headline correction of the
2026-08-27 re-measure: the profiles were previously believed to fit, and none of them do. Tiered
loading is not the convenient option, it is the only one.

| Profile | Contents | tokens (measured) | Fits 1M? |
|---|---|---|---|
| `--core` | `--research` minus `tests/` — the smallest useful code+docs bundle | **2.96M** | ❌ no, ~3× over |
| `--research` | **The whole hub product, junk-free**: `agents/` Python + `frontend/src` TS + `tests/` + `skills/` + current docs (incl. `docs/contracts/worldview-bridge.md` — everything the hub needs to know about WorldView without loading it). Excludes the standalone stacks (worldview/mobile/desktop/rust) and provenance archives (docs/superpowers, docs/research, docs/internal) | **4.15M** | ❌ no, ~4× over |
| *(none)* | everything incl. WorldView + provenance | **5.37M** | ❌ no, ~5× over |

Use a profile only to *grep* offline or to feed a model with a window measured in millions. For a
1M assistant, compose Tier 0 + Tier 1 + one bundle by hand.

---

## Tier 0 — always load first (45K tokens measured)

Order matters: each file assumes the previous ones.

| # | File | tokens | Why |
|---|------|-------:|-----|
| 1 | `CLAUDE.md` | 1.0K | Entry point — routing rules to everything else |
| 2 | `AGENTS.md` | 1.9K | Non-negotiable conventions, parity rules, multi-agent workflow |
| 3 | `docs/ARCHITECTURE.md` | 13.9K | Entry points, request lifecycle, module index, how-to recipes |
| 4 | `MOONSHOT.md` | 4.5K | Vision, principles, phase gates — the drift check; links onward to `NERVA_VISION.md` (Tier 1) for the capability detail |
| 5 | `STATUS.md` | 16.1K | Current snapshot (version, counts, agent roster). **The biggest Tier 0 file** — most of it is the ORIZONT 26 history table; skim the header block if you only need counts |
| 6 | `README.md` | 4.3K | Public framing, run instructions |
| 7 | `NERVA.md` | 3.4K | Architecture overview + directory tree |

## Tier 1 — project state (198K tokens measured; load for any planning/backlog/docs task)

| File | tokens | Why |
|------|-------:|-----|
| `BACKLOG.md` | 176K | THE priority truth, and **73% of this tier on its own**. Do not load it whole for a quick task — read the header through "Status General" (~94K, itself large) or better, jump straight to the one section you're touching |
| `NERVA_VISION.md` | 10.7K | The capability vision — six pillars, target architecture, capability registry, graduated autonomy, the Hermes superiority bar (S1–S8). Load for any strategy/roadmap/capability task |
| `GO_LIVE_PLAN.md` | 6.5K | Features, marketing brief, v1.0 launch checklist |
| `docs/NERVA_2_ROADMAP.md` | ~5K | The 1.1.0 … 2.0.0 milestone sequence with exit gates and the owner lane — load for any "what next / roadmap" task; the driver prompt is `docs/prompts/BACKLOG_DRIVER.md` |
| `docs/2026-06-10-full-project-analysis.md` | 1.6K | Whole-repo audit snapshot: stats, debt, parity verdict (dated — provenance, not current truth) |
| `docs/REVIEW_YEAR_ONE.md` | 5.0K | Candid year-one review: status, the 12 learnings, gap to a desirable product, next-90-days plan |

**Tier 0 + Tier 1 = 243K tokens.** That is a quarter of a 1M window before you have opened a single
source file — budget accordingly, and skip Tier 1 entirely for pure code tasks.

## Task bundles — add exactly one (Tier 2)

| Task | Load | tokens |
|------|------|-------:|
| **Backend work** (`agents/`) | `agents/core/<touched module>` + `agents/web.py` (or the relevant `agents/core/routers/*`) + matching `tests/test_*.py`. **Full backend = 1.15M — it does not fit a 1M window on its own**, so the module index in ARCHITECTURE §3 is mandatory, not a convenience. For metrics/observability work also load `docs/METRICS.md` | 10K–1.15M |
| **HUD v2 / frontend** | `frontend/src/**` (330K, excluding the generated `schema.gen.ts`) + `docs/design/HUD_V2_REMAINING.md` + `HUD_V2_COVERAGE_AND_PLAN.md` + `tests/test_hud_v2_parity.py` | ~345K |
| **WorldView** | `worldview/README.md` + `worldview/{frontend,backend-api}/src` + **`docs/contracts/worldview-bridge.md`** (the only hub coupling) — standalone stack, nothing else needed | ~235K |
| **Mobile parity** | `mobile/**` + `mobile/PARITY.md` + the endpoint list from ARCHITECTURE | ~101K |
| **Security/audit** | `agents/core/security/**` (29K) + `docs/AUDIT.md` + `docs/MANUAL_TESTING.md` + `SECURITY.md` | ~45K |
| **QA / manual testing** | `docs/TEST_MANUAL.md` (entry point + rules + run record) + **only the `docs/test-manual/` chapters for the areas you're testing** — all 15 chapters together are **453K**, averaging ~30K each, and chapter 14 is generated. Add `docs/COWORK_QA_RUNBOOK.md` when an agent drives the run and the newest `docs/qa-runs/*` as the baseline | 8K + ~30K per chapter |
| **Marketing/brand** | `docs/BRAND_BOOK.md` + `GO_LIVE_PLAN.md` §3 + `docs/VALUATION_AND_PRICING.md` + `docs/GTM_PLAN.md` | ~25K |
| **Voice** | `docs/VOICE.md` + `agents/core/voice/**` (11K) + `frontend/src/voice.ts` | ~20K |
| **Tests** | `tests/**` is **1.21M** across 642 files — load the matching `test_*.py` for what you touch, never the tree | 5K–1.21M |
| **Whole-codebase sweep** | `python export_repo.py --research` → `repo_export.txt` (gitignored, regenerate on demand). **No profile fits 1M** — see the table above. Use these for offline grep or a multi-million-token window only | 2.96M–5.37M |

**History / research** (`docs/HISTORY.md`, `docs/research/*`, `docs/superpowers/*`,
`CHANGELOG.md` below the Unreleased block) is provenance — load only when investigating *why*
something is the way it is. Dated reports are immutable snapshots; never "fix" their numbers.

## What NOT to load

- `frontend/src/api/schema.gen.ts` — **545KB / ~109K tokens of generated OpenAPI types.** The
  committed copy exists purely as a CI drift gate (`ci.yml` diffs it; `test_openapi_ts_typegen_gate.py`
  reads its content), so it must stay tracked, but no assistant ever needs to read it. Excluded from
  every `export_repo.py` profile since 2026-08-27 — which also means it will **not** appear in the
  export's directory tree, so remember it exists when doing OpenAPI contract work.
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
4. **Count tokens, never estimate them.** This file carried `chars ÷ 4` estimates from 2026-06-10
   until 2026-08-27; they had drifted 2.7×–6.4× low (STATUS.md read "2.5K" against a real 16.1K),
   which meant every load decision in the repo was made on wrong numbers. Re-measure with a real
   tokenizer when a bundle grows by >25%:
   ```bash
   python export_repo.py --research           # or --core / no flag
   python -c "import tiktoken;print(len(tiktoken.get_encoding('o200k_base').encode(open('repo_export.txt',encoding='utf-8',errors='replace').read(),disallowed_special=())))"
   ```
