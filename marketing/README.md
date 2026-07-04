# marketing/ — the launch & growth suite

Everything a marketing team, a coworker, or Claude Design needs to take Jarvis Hub to market.
All material is grounded in the repo's own research and verified facts; all visual direction
inherits from [`../docs/BRAND_BOOK.md`](../docs/BRAND_BOOK.md).

> **Note on layout:** the *foundational* brand + ready-to-paste copy assets live in
> [`../docs/marketing/`](../docs/marketing/) (announcement, teaser pack, design brief — created
> first). This `marketing/` tree is the *operational* layer the owner asked for: review, plan,
> intel, and a content calendar that schedules the copy.

## The four folders

| Folder | File | What it's for | Hand to |
|--------|------|---------------|---------|
| [`brand-review/`](brand-review/) | `BRAND_REVIEW.md` | Consistency audit vs. the brand book — drift found + fixed, scored 8.5/10, with a re-review cadence | You / an agency onboarding |
| [`campaign-plan/`](campaign-plan/) | `CAMPAIGN_PLAN.md` | The executable launch playbook — audiences, message ladder, channel plan, T-minus timeline, metrics, pre-mortem | You / a growth lead |
| [`competitive-brief/`](competitive-brief/) | `COMPETITIVE_BRIEF.md` | The honest, sourced field map — vs OpenClaw / Bee / Khoj / big-tech; objection handling; lines not to cross | Sales / positioning / comment threads |
| [`content/`](content/) | `CONTENT_CALENDAR.md` | Ready-to-schedule copy bank — teaser arc, launch posts, the 7-tweet thread, long-form outline, evergreen cadence | Social scheduler / a writer |
| [`landing/`](landing/) | `index.html` + `demo-shot-list.md` | Static, self-contained landing page dev half plus owner-facing demo capture checklist | Static host / owner recording pass |

## Companion assets (in `docs/marketing/`)

- [`ANNOUNCEMENT.md`](../docs/marketing/ANNOUNCEMENT.md) — the release post (TL;DR → long-form + boilerplate).
- [`TEASER_PACK.md`](../docs/marketing/TEASER_PACK.md) — taglines, social posts, 60s video script, landing snippets.
- [`DESIGN_BRIEF.md`](../docs/marketing/DESIGN_BRIEF.md) — creative brief with exact specs + the **approved-proof-points allowlist** (§5).
- [`landing/index.html`](landing/index.html) — offline-safe landing page built from the same copy spine and Brand Book tokens.

## Three rules everyone using this suite follows

1. **Numbers trace to the repo.** The approved proof points are `DESIGN_BRIEF.md` §5; the source of
   truth for any count is [`BACKLOG.md`](../BACKLOG.md). A stale stat on an asset is a brand bug
   (it's bitten twice — see BRAND_REVIEW §7).
2. **Honesty is the marketing.** Never stage fake data — use real or the clearly-badged demo mode.
   The product's pitch is that it doesn't lie; the marketing can't either.
3. **Stay in category.** Compare against Khoj / OpenClaw / Bee / the big-tech assistants — never the
   developer frameworks (competitive brief §2).

## Where to start, by goal

- *"Write a launch post"* → `content/CONTENT_CALENDAR.md` + `docs/marketing/ANNOUNCEMENT.md`.
- *"Make a graphic / hand to Claude Design"* → `docs/marketing/DESIGN_BRIEF.md`.
- *"Plan the launch"* → `campaign-plan/CAMPAIGN_PLAN.md`.
- *"Answer 'how are you different from X?'"* → `competitive-brief/COMPETITIVE_BRIEF.md`.
- *"Check we're on brand"* → `brand-review/BRAND_REVIEW.md`.

---
*Strategy source: [`docs/GTM_PLAN.md`](../docs/GTM_PLAN.md) · vision: [`MOONSHOT.md`](../MOONSHOT.md) ·
launch gate: [`GO_LIVE_PLAN.md`](../GO_LIVE_PLAN.md).*
