# Backlog Daily Brief — AI Agent Prompt Template

> Use this prompt to orient an AI agent on backlog status and next priorities each morning.
> Customizable; fill in brackets with current numbers/dates.

---

## Context

You are working on **Nerva 1.0** — a governed personal AI OS. Today is **[DATE]**. The repo is `andrei649/jarvis-hub`; north star is in `MOONSHOT.md`; roadmap is `BACKLOG.md`.

## Current Status Snapshot

- **Version:** 0.11.0 (feature-complete; proof track is the remaining road to 1.0)
- **Test count:** [BACKEND_TESTS] backend, [FRONTEND_TESTS] frontend, [MOBILE_TESTS] mobile
- **Open routes:** [ROUTE_COUNT]
- **Active agents:** [AGENT_COUNT]
- **Open release gates:** A1–A9 (see `project-status.json`; A1 ⭐B0 is the critical path)

### Finished (as of today)
- H1–H17 feature horizons: ~99% (194/196 items)
- H23 productionization spine: ~95% (owner-runtime-gated UI = 5%)
- Nerva 2.0 E0 gate + M1 slices: accepted (E5/E8 blocked on #906 authority)
- Max runs 000–012: security residues closed (last: B7 dispatch-authority repair)

### In Flight
- **#929** (this PR or recent): docs backlog sync + cloud testing chapter
- **#921–#927:** chapter-15 reconciliation + Dependabot batches
- **#906, #912, #918:** Nerva authority slices (draft/holding on integrator review)

### Blocked (owner-side)
- **A1 ⭐B0:** governed-autonomy demo on RTX box (manual testing gate)
- **A2:** 72h soak + AUD-0 instrument
- **A3–A5:** Dependabot triage, GitHub settings, license flip
- **A6–A7:** demo video + recruit design partners
- **A8–A9:** AI-OS host proof + 1.0 tag

## Agent Task: Prioritize & Identify Next 3–5 Unblocked Items

**Rules:**
1. **Only unblocked items** — skip anything waiting on #906 or owner gates.
2. **Maximum 3–5 items** — focus over breadth.
3. **Next-in-queue order** — follow `MAX.md` §3.1 + `BACKLOG.md` run ledger.
4. **Bounded slice** — each item fits in a single PR with no stacking.

**Look at:**
- `docs/MAX_RUNS.md` — the run ledger, last row's `next` pointer
- `BACKLOG.md` — "Accepted M1 slices" section + "🟡 E1/E6/E9 authority-ceiling" footnotes
- `AGENTS.md` — agent-side responsibilities (what can AI tackle vs. owner-only)
- GitHub issues #757, #778, #818, #906, etc. — current blockers

**Output format:**
```
## Next 3–5 Unblocked Items

1. **[Item name / issue #XYZ]** — [one-line why it's next]
   - Slice: [bounded scope, ~1 PR]
   - Blocker check: [what would block this if not listed]
   - Confidence: [HIGH/MEDIUM/LOW + brief reason]

2. ...
```

Then, for the **#1 item**, draft a **standalone, self-contained prompt** (suitable for passing to an AI agent) that:
- Names the issue/item clearly
- Lists acceptance criteria from the backlog / issue body
- Provides file paths to read first (use `jarvis-load-context` skill if backend/security/WorldView)
- Specifies branch (`claude/[item-codename]`)
- Notes any known gotchas or prior art (e.g., "similar to #XYZ, which landed in PR #ABC")

---

## Why This Matters

The backlog update is synchronized daily so:
- No decision is stale (merged PRs are recorded same-day)
- Competing priorities are visible (this week vs. next vs. A8 owner-parallel track)
- Authority/scope boundaries are clear (what the AI can ship vs. owner-only)

Run this prompt **every morning at 08:00 UTC** and share the output with the owner so they know what's ready to tackle.
