# Brand Review — Jarvis Hub (2026-06-11)

> A consistency audit of the brand across every surface a buyer or contributor sees, measured
> against [`docs/BRAND_BOOK.md`](../../docs/BRAND_BOOK.md). Goal: find drift before launch, fix the
> cheap ones, flag the owner-only ones. Scored, dated, actionable.

---

## Verdict

**Strong and coherent — launch-ready on brand, with a short fix list.** The brand book is real and
followed; the HUD visually embodies the identity (verified by screenshot: void/cyan, mono labels,
honest empty states); voice is consistent (calm, specific, butler-not-hype). The drift that exists
is **stale numbers** — the exact failure mode the brand book warns about ("stale stats here are a
brand bug"). Two were fixed in this pass; the rest are owner-gated (live GitHub settings) or
deliberate (license).

**Brand health: 8.5 / 10.** −1 for the numeric drift found, −0.5 for the unset repo metadata.

---

## 1. Identity consistency

| Element | Brand book says | Reality | Status |
|---|---|---|---|
| Product name | "Jarvis Hub" (two words, kebab repo) | Consistent across docs/repo | ✅ |
| Founder-instance flavor | "Andrei's Cabinet" / "your AI cabinet" | README title "Jarvis Hub — your AI cabinet" | ✅ (de-personalized correctly) |
| Wordmark | `JARVIS HUB`, cyan on void, mono sub-line | Matches the HUD top bar | ✅ |
| Primary tagline | "The AI that works while you sleep." | Used in README, MOONSHOT, all marketing | ✅ |
| Agent count | 17 active | **Drifted: GO_LIVE_PLAN tagline said "15", GTM said "16"** | 🔧 **fixed this pass** |
| "Jarvis" trademark risk | Flagged for Phase 2 | Noted in BRAND_BOOK §2 + OWNER_TASKS | ✅ tracked |

## 2. Visual identity (verified against the running HUD, 2026-06-10 screenshots)

| Token | Spec | In the product | Status |
|---|---|---|---|
| Void background | `#04070E` | Matches | ✅ |
| Signal cyan accent | `#2BB8F0` | Matches (one accent, disciplined) | ✅ |
| Type | Space Grotesk + JetBrains Mono | Used; mono micro-labels are a signature | ✅ |
| Honesty visuals | DATA OFFLINE / DEMO / verified states | All present and correct — *the honesty is on-brand* | ✅ |
| Texture | thin scanline / dot-grid, restrained | Present, subtle | ✅ |

> The single most on-brand thing about the product: it never fakes data. The "seeded sample, not
> your live backend" banner and the Merkle-verified audit chain are brand assets, not just features.

## 3. Voice & tone

- Calm, specific, declarative across README/MOONSHOT/marketing. ✅
- Numbers over adjectives — held (the new marketing pack quotes conservative verified counts). ✅
- Avoided words ("revolutionary", "magic", "AI employee") — absent. ✅
- One residual: **RO/EN mix in internal planning docs** (GTM_PLAN, BACKLOG) — fine for internal,
  but never let RO strings leak into a buyer-facing asset. (The installers were already EN-ized.)

## 4. Messaging consistency

- The spine ("works while you sleep" + local-first + governed) is consistent everywhere. ✅
- Proof-points align across BRAND_BOOK §5, GTM, the competitive brief, and the new content. ✅
- **Category discipline:** the old "vs 8 dev frameworks" table in GO_LIVE_PLAN §3 is the one
  off-category comparison — already flagged in-doc; the competitive brief is now the canonical
  buyer-facing comparison. ⚠️ *don't reuse the dev-framework table in marketing.*

---

## 5. Findings & actions

| # | Finding | Severity | Action |
|---|---------|----------|--------|
| 1 | GO_LIVE_PLAN tagline "15 agents", GTM "16 agents" — stale vs 17 | **Med** (stale stat = brand bug) | ✅ **Fixed** → both now "17 agents" |
| 2 | GitHub repo description still "Personal AI"; topics unset | **Med** (first impression) | 🔒 Owner — paste from BRAND_BOOK §9 (Settings → General) |
| 3 | No demo GIF / social-preview image yet | **Med** (launch asset) | 🔒 Owner — produce from DESIGN_BRIEF specs; tracked OWNER_TASKS |
| 4 | License badge MIT; Apache-2.0 relicense decided but pending | Low | 🔒 Owner decision (pre-1.0) — tracked |
| 5 | Old dev-framework comparison table lives in GO_LIVE_PLAN §3 | Low | ⚠️ Use competitive brief for buyer copy; table is dev-context only |
| 6 | RO/EN mix in internal docs | Low | ✅ Acceptable internally; gate at the buyer-facing boundary |
| 7 | "Jarvis" trademark association | Low (Phase 2) | ✅ Tracked (BRAND_BOOK §2, OWNER_TASKS) |

**Fixed in this review:** #1 (the agent-count taglines). **Everything else is owner-gated or
already-tracked** — no silent changes to messaging or license without sign-off.

---

## 6. The 30-second brand summary (for a new teammate / agency)

> **Jarvis Hub** is a local-first, governed personal AI operating system. The brand is *calm
> competence — a premium dark cockpit you command, not a hype-y SaaS page.* Void-black + one signal-
> cyan accent, Space Grotesk + JetBrains Mono, real product data as texture. Voice: butler, not
> hype-man — numbers over adjectives, and **never claim what the repo can't back** (honesty is the
> whole pitch). The one tagline: *"The AI that works while you sleep."* The one differentiator:
> *governed autonomy you can audit, on hardware you own.*

---

## 7. Re-review cadence

Re-run this audit at: every public launch milestone, any agent-count/test-count change (sweep the
taglines), and quarterly for the competitive claims. The numeric-drift check is the highest-value
recurring item — it's bitten twice now (docs in the June reconciliation, taglines here).

> Source of truth for all counts: [`BACKLOG.md`](../../BACKLOG.md). Brand foundations:
> [`docs/BRAND_BOOK.md`](../../docs/BRAND_BOOK.md).
