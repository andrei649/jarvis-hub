# Hermes bucket prompts (ultracode)

Four self-contained prompts, one per ledger bucket, for a fresh Claude Code session with ultracode on
(`/effort ultracode`). Each computes its rows live from `scripts/hermes_status.py`, so the counts in it
are a snapshot, not a contract. Written 2026-09-28 at `abf0aebd` and checked against the repo.

| Bucket | Prompt | What the session does |
|---|---|---|
| missing | [missing.md](missing.md) | builds missing rows to equivalent, or an honest partial |
| partial | [partial.md](partial.md) | closes `remaining` items, nearest-to-equivalent first |
| equivalent | [equivalent.md](equivalent.md) | audits the 190, the 108 inherited 7 September rows first; downgrades honestly |
| needs_review | [needs-review.md](needs-review.md) | records work: re-reads and restamps stale rows, assesses reopened ones |

Launch one with: `Read docs/prompts/hermes/<bucket>.md from branch claude/cto-session-recovery-qinvkg and execute it.`

All four push to the same branch and edit the same ledger (`docs/hermes/assessment.json`) and generated
reports. Each prompt merges and regenerates before every push, but running them in parallel still
costs merge work. Run at most two at a time, and prefer pairing a records bucket (equivalent or
needs_review) with a build bucket (missing or partial).

Owner-only work stays out of all four:
- every path in `selfdev-policy.json` → `protected_paths`, including `agents/core/kernel/**`,
  `agents/core/security/**`, `agents/core/secrets/**`, `AGENTS.md` and `.github/workflows/**`;
- rows that need network or hardware;
- the decisions in `docs/OWNER_TASKS.md`.

A single driver session can run all four in order: see `docs/handoff/2026-09-28-handover/PROMPT.md`.
