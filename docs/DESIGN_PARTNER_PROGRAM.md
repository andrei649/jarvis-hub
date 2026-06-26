# Design-Partner Program

> The 1.0 gate isn't "the code works" — it's **real people getting real value** (MOONSHOT
> §4). This is the lightweight program to get Jarvis in front of **1–3 design partners**
> and learn from actual usage. The in-app feedback loop that powers it is built and local.

## Why design partners

The offline test suite proves the *machine* works; it can't prove the *product* is useful.
Three engaged partners using Jarvis on their own machines, for their own work, surface the
gaps a green CI never will — and produce the north-star signal (accepted actions / week)
that the metrics layer tracks.

## Who to recruit (1–3, no more)

- People whose work overlaps the cabinet's strengths (engineering, research, ops, personal
  automation) and who are comfortable running a local-first tool.
- Small on purpose: 1–3 partners give depth over breadth. Add more only after the first
  cohort is getting value.

## The in-app feedback loop (built — H23.21)

A footer widget posts to a **first-party, local** store — feedback never leaves the
partner's machine:

- **`POST /api/feedback`** — `{kind: "nps" | "comment" | "bug", score?: 0–10, message?, session_id?}`.
- **`GET /api/feedback/summary`** (owner, admin-guarded) — **NPS** (%promoters − %detractors)
  + per-kind counts + the most recent items.

NPS bands: promoters 9–10, passives 7–8, detractors 0–6. The score is `null` until at
least one NPS response exists — we never fabricate it.

## Support SLA

- **48-hour** response to any bug/feedback item during the program.
- Triage: bugs → a fix or a clear "won't-fix + why"; feature asks → logged against the
  backlog with a yes/no/later.

## What to measure

- **North-star:** accepted autonomous actions per active user per week (`GET /api/metrics/north-star`).
- **Counter-metrics / guardrails:** interrupt rate (≤4/day), reject rate, %-local, p95 —
  the same call surfaces `guardrail_breaches` so a partner's experience can't be gamed.
- **NPS + qualitative feedback** from the widget.

## Privacy

Partners run Jarvis on their own machines; their data and feedback stay local (see
[`PRIVACY.md`](PRIVACY.md)). Nothing is collected centrally — you ask partners to share
what they choose, when they choose.

## Exit → 1.0

When the cohort is getting repeated value, the north-star is moving on real usage, and the
manual-test/audit pass is green, the 1.0 tag is justified (MOONSHOT §4 / `GO_LIVE_PLAN.md`).
